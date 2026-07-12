"""CLI entry point — G.O.A.L. Cascade.

Usage:
    goal run --objective "..." [--provider mock|kimi-cli|kimi-code]
    goal status [run_id]
    goal list
    goal versions <run_id>
    goal diff <run_id_1> <run_id_2>
    goal inspect <run_id>
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import datetime as _dt
import json

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import DEFAULT_CONFIG_PATH, ProvidersConfig, load_goal_config
from .audit_journal import redact_sensitive
from .orchestrator.budget_tracker import BudgetConfig, BudgetTracker
from .orchestrator.cascade_executor import CascadeExecutor
from .orchestrator.state_manager import RUNS_DIR, list_runs, load_state
from .providers.base import BaseProvider
from .providers.kimi_command import KimiBackend, KimiCommandProvider
from .providers.mock import MockProvider
from .providers.router import RoleMappedProvider
from .rag_bridge import RagBridge, RagSyncError
from .multicascade.module_graph import ModuleGraph
from .schemas.models import Variant
from .schemas.plan import CascadePlan
from .schemas.versioning import RunVersion, VersionDiff

app = typer.Typer(
    name="goal",
    help="G.O.A.L. Cascade — Multi-agent cascade framework",
    no_args_is_help=True,
)
console = Console()

__all__ = [
    "app",
    "DEFAULT_CONFIG_PATH",
    "ProviderChoice",
    "run",
    "status",
    "list_cmd",
    "versions",
    "diff",
    "inspect_run",
    "rag_status",
    "rag_sync",
    "init",
    "cascade_plan",
]


class ProviderChoice(str, Enum):
    MOCK = "mock"
    KIMI_CLI = "kimi-cli"
    KIMI_CODE = "kimi-code"


def _print_config_summary(config_path: Path, providers: ProvidersConfig) -> None:
    """Affiche un résumé lisible de la config TOML chargée."""

    console.print(f"[green]✅ Config chargée[/green] — {config_path.expanduser()}")
    available_count = len(set(providers.enabled))
    if providers.degraded:
        console.print(
            f"[yellow]⚠️  Mode dégradé : {available_count}/3 provider(s) "
            f"disponible(s)[/yellow]"
        )
        console.print("   Mapping effectif :")
        for row in providers.mapping_rows():
            if row.auto_switched:
                status = f"configuré: {row.configured} ✗ → auto-switch"
            else:
                status = f"configuré: {row.configured} ✓"
            console.print(f"     {row.role:<11} → {row.effective} ({status})")
        console.print(
            "   [yellow]La diversité multi-provider est réduite. "
            "Les erreurs seront corrélées.[/yellow]"
        )
    else:
        console.print(
            f"   Providers : {', '.join(providers.enabled)} "
            f"({available_count}/3 ✓)"
        )
        console.print("   Diversité : optimale")


def _build_provider(
    provider_id: str,
    *,
    synthesizer_model: str | None = None,
    config: "GoalConfig | None" = None,
) -> BaseProvider:
    """Construit l'instance de provider effective pour un identifiant résolu.

    Refuse explicitement les providers non implémentés dans ce jalon pour
    éviter tout appel API involontaire.
    """

    if provider_id == "mock":
        return MockProvider()
    if provider_id == "kimi-cli":
        return KimiCommandProvider(
            backend=KimiBackend.CLI,
            work_dir=Path.cwd(),
            model=synthesizer_model,
        )
    if provider_id == "kimi-code":
        return KimiCommandProvider(
            backend=KimiBackend.CODE,
            work_dir=Path.cwd(),
            model=synthesizer_model,
        )
    if provider_id in {"anthropic", "openai", "google"}:
        try:
            from .providers.mirascope_provider import (
                Backend,
                MirascopeProvider,
                RateLimitConfig,
            )
        except ImportError as exc:
            raise typer.BadParameter(
                "Les providers réels nécessitent l'extra llm. "
                "Installez avec: pip install goal-cascade[llm]"
            ) from exc
        available_backends: set[Backend] | None = None
        if config is not None:
            available_backends = {
                Backend(name)
                for name in config.providers.enabled
                if name in {"anthropic", "openai", "google"}
            }
        return MirascopeProvider(
            backend=Backend(provider_id),
            rate_limit_config=(
                RateLimitConfig(**config.ratelimit.model_dump())
                if config is not None
                else RateLimitConfig()
            ),
            enable_cache=True,
            available_backends=available_backends,
        )
    raise typer.BadParameter(
        f"Provider {provider_id!r} configuré mais non implémenté dans ce jalon. "
        "Providers disponibles : mock, kimi-cli, kimi-code, anthropic, openai, google."
    )


@app.command()
def run(
    objective: str = typer.Option(
        ..., "--objective", "-o",
        help="L'objectif du livrable (une phrase claire)"
    ),
    variant: Variant = typer.Option(
        Variant.A, "--variant", "-v",
        help="Variante : A (redactionnel) ou B (technique)"
    ),
    provider: ProviderChoice = typer.Option(
        ProviderChoice.MOCK, "--provider", "-p",
        help="Provider : mock, kimi-cli ou kimi-code"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help=(
            "Chemin du fichier config TOML. "
            f"Par défaut : {DEFAULT_CONFIG_PATH} si présent."
        ),
    ),
    audience: str = typer.Option(
        "", "--audience", "-a",
        help="Public cible"
    ),
    constraints: str = typer.Option(
        "", "--constraints", "-c",
        help="Contraintes (format, longueur, etc.)"
    ),
    synthesizer_model: str | None = typer.Option(
        None,
        "--synthesizer-model",
        envvar="GOAL_SYNTHESIZER_MODEL",
        help="Modèle small/cheap dédié aux synthèses (obligatoire avec Kimi)",
    ),
    no_synth: bool = typer.Option(
        False,
        "--no-synth",
        help="Désactiver la synthèse orientée objectif (debug : la sortie brute est passée telle quelle)",
    ),
):
    """Lance une cascade G.O.A.L. complete."""

    if synthesizer_model is not None:
        synthesizer_model = synthesizer_model.strip()

    # Resolution de la config TOML : charge si --config est fourni OU si
    # le chemin par defaut existe. Sinon, retombe sur la selection legacy.
    candidate_config_path = config or DEFAULT_CONFIG_PATH
    should_load_config = config is not None or candidate_config_path.exists()
    budget_tracker: BudgetTracker | None = None
    if should_load_config:
        # Si l'utilisateur a passe --config PATH explicitement et que le
        # fichier n'existe pas, on remonte une erreur CLI claire plutot
        # qu'un FileNotFoundError brut issu de tomllib.
        if config is not None and not candidate_config_path.exists():
            console.print(
                f"[bold red]Config introuvable : "
                f"{candidate_config_path.expanduser()}[/bold red]"
            )
            raise typer.Exit(2)
        try:
            goal_config = load_goal_config(candidate_config_path)
        except (ValidationError, ValueError) as exc:
            console.print(
                f"[bold red]Config invalide ({candidate_config_path}): "
                f"{exc}[/bold red]"
            )
            raise typer.Exit(1) from exc
        _print_config_summary(candidate_config_path, goal_config.providers)

        # Les providers Kimi exigent un modele explicite pour le synthetiseur
        # (meme exigence que le mode legacy).
        if (
            goal_config.providers.resolved_synthesizer in ("kimi-cli", "kimi-code")
            and not synthesizer_model
        ):
            typer.echo(
                "Erreur : --synthesizer-model est requis avec un provider Kimi",
                err=True,
            )
            raise typer.BadParameter(
                "requis avec un provider Kimi",
                param_hint="--synthesizer-model",
            )

        provider_names = set(goal_config.providers.resolved_role_mapping.values())
        providers_by_name = {
            provider_name: _build_provider(provider_name, config=goal_config)
            for provider_name in provider_names
        }
        selected_provider = RoleMappedProvider(
            providers_by_name=providers_by_name,
            role_mapping=goal_config.providers.resolved_role_mapping,
        )
        selected_synthesizer_provider = _build_provider(
            goal_config.providers.resolved_synthesizer,
            synthesizer_model=synthesizer_model,
            config=goal_config,
        )
        provider_label = "Mapping TOML adaptatif"
        synthesizer_label = goal_config.providers.resolved_synthesizer
        # Activer le kill switch budgetaire si la section [budget] est definie.
        budget_tracker = BudgetTracker(
            config=goal_config.budget,
            daily_total_path=RUNS_DIR.parent / "budget_daily.json",
        )
    elif provider == ProviderChoice.MOCK:
        # Selection du provider. Chaque appel Kimi omet volontairement les
        # options de reprise : une iteration = une nouvelle session.
        selected_provider = MockProvider()
        selected_synthesizer_provider = MockProvider()
        provider_label = "Mock (pas d'API)"
        synthesizer_label = "Mock small (instance isolée)"
    elif provider == ProviderChoice.KIMI_CLI:
        if not synthesizer_model:
            typer.echo(
                "Erreur : --synthesizer-model est requis avec un provider Kimi",
                err=True,
            )
            raise typer.BadParameter(
                "requis avec un provider Kimi",
                param_hint="--synthesizer-model",
            )
        selected_provider = KimiCommandProvider(
            backend=KimiBackend.CLI,
            work_dir=Path.cwd(),
        )
        selected_synthesizer_provider = KimiCommandProvider(
            backend=KimiBackend.CLI,
            work_dir=Path.cwd(),
            model=synthesizer_model,
        )
        provider_label = "Kimi CLI 1.x (sessions non interactives)"
        synthesizer_label = f"Kimi CLI 1.x / {synthesizer_model}"
        console.print(
            "[bold yellow]⚠  Attention : le provider Kimi CLI utilise --print "
            "qui auto-approuve les outils (shell, fichiers). "
            "Risque d'injection de prompt. "
            "Utilisez dans un environnement contrôlé.[/bold yellow]"
        )
    else:
        if not synthesizer_model:
            typer.echo(
                "Erreur : --synthesizer-model est requis avec un provider Kimi",
                err=True,
            )
            raise typer.BadParameter(
                "requis avec un provider Kimi",
                param_hint="--synthesizer-model",
            )
        selected_provider = KimiCommandProvider(
            backend=KimiBackend.CODE,
            work_dir=Path.cwd(),
        )
        selected_synthesizer_provider = KimiCommandProvider(
            backend=KimiBackend.CODE,
            work_dir=Path.cwd(),
            model=synthesizer_model,
        )
        provider_label = "Kimi Code 0.x (sessions non interactives)"
        synthesizer_label = f"Kimi Code 0.x / {synthesizer_model}"
        console.print(
            "[bold yellow]⚠  Attention : le provider Kimi Code utilise --print "
            "qui auto-approuve les outils (shell, fichiers). "
            "Risque d'injection de prompt. "
            "Utilisez dans un environnement contrôlé.[/bold yellow]"
        )

    # Afficher l'en-tete
    header = Panel.fit(
        f"[bold]G.O.A.L. Cascade[/bold]\n"
        f"Objectif : {objective}\n"
        f"Variante : {variant.value} "
        f"({'redactionnel' if variant == Variant.A else 'technique'})\n"
        f"Provider : {provider_label}\n"
        f"Synthèse : {synthesizer_label}",
        border_style="cyan",
    )
    console.print(header)

    # Initialiser et executer
    executor = CascadeExecutor(
        provider=selected_provider,
        synthesizer_provider=selected_synthesizer_provider,
        rag_bridge=RagBridge(),
        budget_tracker=budget_tracker,
    )
    state = executor.init_state(objective=objective, variant=variant)
    run_dir = RUNS_DIR / state.run_id

    console.print(f"\n[cyan]Run #{state.run_id} demarre...[/cyan]")
    console.print(f"Dossier permanent : [cyan]{run_dir}[/cyan]")
    console.print(f"Journal temps réel : [cyan]{run_dir / 'events.jsonl'}[/cyan]")
    console.print(f"Statut RAG : [cyan]{run_dir / 'rag-status.json'}[/cyan]")

    try:
        state = executor.run(
            state,
            audience=audience,
            constraints=constraints,
            verbose=True,
            no_synth=no_synth,
        )
    except Exception as exc:
        console.print(f"\n[bold red]Cascade en erreur : {exc}[/bold red]")
        console.print(f"Trace complète : [cyan]{run_dir / 'timeline.md'}[/cyan]")
        console.print(f"Événements bruts : [cyan]{run_dir / 'events.jsonl'}[/cyan]")
        console.print(f"Statut RAG : [cyan]{run_dir / 'rag-status.json'}[/cyan]")
        raise typer.Exit(1) from exc

    # Afficher le resultat
    console.print()
    if state.status == "stopped":
        console.print(
            f"[bold green]Cascade terminee en {state.current_iteration} "
            f"iterations[/bold green]"
        )
    elif state.status == "forced_stop":
        console.print(
            f"[bold yellow]Cascade stoppee (limite atteinte) "
            f"apres {state.current_iteration} iterations[/bold yellow]"
        )

    if state.final_verdict:
        verdict = state.final_verdict
        color = "green" if verdict.decision == "STOP" else "yellow"
        console.print(
            f"\nVerdict : [{color}]{verdict.decision}[/{color}]"
        )
        console.print(f"Justification : {verdict.justification}")

    if state.accumulated_cost > 0:
        cost_str = f"${state.accumulated_cost:.4f}"
    elif provider == ProviderChoice.MOCK:
        cost_str = "gratuit (mock)"
    else:
        cost_str = "non communiqué par le CLI Kimi"
    console.print(f"Cout total : {cost_str}")

    # Recu detaille du run (transparence radicale des couts, section 9 plan v2)
    receipt_path = RUNS_DIR / state.run_id / "receipt.json"
    if receipt_path.exists():
        try:
            from .schemas.models import RunReceipt
            receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt = RunReceipt.model_validate(receipt_data)
            console.print()
            for line in receipt.summary_lines():
                console.print(f"[dim]{line}[/dim]")
            console.print(f"  Recu complet : [dim]{receipt_path}[/dim]")
        except (OSError, json.JSONDecodeError, Exception):
            # Fallback : affichage minimal si le reçu ne peut pas être parsé
            console.print(f"[dim]Recu : {receipt_path}[/dim]")

    # Afficher les details du run
    console.print(f"\nRun ID : [cyan]{state.run_id}[/cyan]")
    console.print(
        f"Livrable : {RUNS_DIR / state.run_id / 'final_output.md'}"
    )
    console.print(f"Cheminement : {run_dir / 'timeline.md'}")
    console.print(f"Événements : {run_dir / 'events.jsonl'}")
    console.print(f"Preuve RAG : {run_dir / 'rag-status.json'}")

    # Afficher le tableau des appels
    if state.history:
        table = Table(title="\nDetails des appels LLM")
        table.add_column("Etape", style="cyan")
        table.add_column("Role")
        table.add_column("Provider")
        table.add_column("Modele")
        table.add_column("In tok", justify="right")
        table.add_column("Out tok", justify="right")
        table.add_column("Cout", justify="right")

        for call in state.history:
            if call.cost_usd > 0:
                cost = f"${call.cost_usd:.4f}"
            elif call.provider == "mock":
                cost = "gratuit"
            else:
                cost = "non mesuré"
            input_tokens = str(call.input_tokens)
            output_tokens = str(call.output_tokens)
            if call.token_count_estimated:
                input_tokens = f"~{input_tokens}"
                output_tokens = f"~{output_tokens}"
            table.add_row(
                str(call.iteration),
                call.role,
                call.provider,
                call.model,
                input_tokens,
                output_tokens,
                cost,
            )

        console.print(table)


def _print_velocity_dashboard(
    history: list[LLMCallRecord], run_id: str
) -> None:
    """Affiche un dashboard ASCII de vitesse de la cascade.

    Barre horizontale par itération : rôle, coût, indicateur visuel.
    █ pour les itérations coûteuses, ░ pour les légères.
    Le coût maximum sert de référence pour la largeur des barres.
    """
    if not history:
        return

    # Déterminer la métrique : coût si dispo, sinon tokens
    max_cost = max((c.cost_usd for c in history), default=0.0)
    use_tokens = max_cost <= 0.0
    if use_tokens:
        max_value = float(
            max((c.input_tokens + c.output_tokens for c in history), default=1)
        )
    else:
        max_value = max_cost

    if max_value <= 0:
        return

    bar_width = 30
    separator = "─" * 78

    console.print()
    console.print("[bold]Dashboard de vitesse[/bold]")
    console.print(separator)

    for call in history:
        value = (
            float(call.input_tokens + call.output_tokens)
            if use_tokens
            else call.cost_usd
        )
        ratio = min(value / max_value, 1.0)
        filled = max(1, int(ratio * bar_width)) if value > 0 else 0
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty

        if use_tokens:
            metric_str = f"{call.input_tokens + call.output_tokens} tok"
        else:
            metric_str = f"${call.cost_usd:.4f}"

        console.print(
            f"{call.iteration:>2}  {call.role:<10} {metric_str:>9}  {bar}"
        )

    console.print(separator)

    # Cache hit rate depuis receipt.json
    from .schemas.models import RunReceipt

    receipt_path = RUNS_DIR / run_id / "receipt.json"
    if receipt_path.exists():
        try:
            receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt = RunReceipt.model_validate(receipt_data)
            rate = receipt.cache_hit_rate
            console.print(f"  Cache hit rate : {rate:.0%}")
        except (OSError, json.JSONDecodeError, Exception):
            pass


@app.command()
def status(
    run_id: str = typer.Argument(None, help="ID du run a inspecter"),
):
    """Affiche le statut d'un run."""

    if not run_id:
        # Si pas d'ID, afficher la liste des runs
        list_cmd()
        return

    state = load_state(run_id)
    if not state:
        console.print(f"[red]Run #{run_id} introuvable.[/red]")
        raise typer.Exit(1)

    # Panneau de resume
    status_color = {
        "running": "yellow",
        "stopped": "green",
        "forced_stop": "yellow",
        "failed": "red",
    }.get(state.status, "white")

    panel = Panel.fit(
        f"[bold]Run #{state.run_id}[/bold]\n"
        f"Statut : [{status_color}]{state.status}[/{status_color}]\n"
        f"Objectif : {state.objective}\n"
        f"Iterations : {state.current_iteration}/{state.max_iterations}\n"
        f"Cout : ${state.accumulated_cost:.4f}",
        border_style="cyan",
    )
    console.print(panel)

    # Tableau des iterations
    if state.history:
        table = Table(title="Iterations")
        table.add_column("#", style="cyan")
        table.add_column("Role")
        table.add_column("Provider")
        table.add_column("In tok", justify="right")
        table.add_column("Out tok", justify="right")
        table.add_column("Latence (ms)", justify="right")

        for call in state.history:
            table.add_row(
                str(call.iteration),
                call.role,
                call.provider,
                str(call.input_tokens),
                str(call.output_tokens),
                str(call.latency_ms),
            )

        console.print(table)

    # Dashboard de vitesse
    _print_velocity_dashboard(state.history, state.run_id)

    if state.final_verdict:
        color = "green" if state.final_verdict.decision == "STOP" else "yellow"
        console.print(
            f"\nVerdict : [{color}]{state.final_verdict.decision}[/{color}]"
        )
        console.print(f"  {state.final_verdict.justification}")


@app.command(name="versions")
def versions(
    run_id: str = typer.Argument(..., help="ID du run dont lister les versions"),
):
    """Liste les versions d'un run depuis le répertoire ~/.goal/runs/<run_id>/."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        console.print(f"[red]Run '{run_id}' introuvable : {run_dir}[/red]")
        raise typer.Exit(1)

    state_file = run_dir / "state.json"
    receipt_file = run_dir / "receipt.json"

    if not state_file.exists():
        console.print(f"[red]Aucun state.json pour le run '{run_id}'.[/red]")
        raise typer.Exit(1)

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    receipt_data: dict | None = None
    if receipt_file.exists():
        receipt_data = json.loads(receipt_file.read_text(encoding="utf-8"))

    iterations = state_data.get("current_iteration", 0)
    status_val = state_data.get("status", "unknown")
    objective = state_data.get("objective", "")

    # Chaque itération = une "version" du run
    versions_list: list[RunVersion] = []
    for it in range(1, iterations + 1):
        iter_file = run_dir / f"iteration_{it}.txt"
        if iter_file.exists():
            iter_stat = iter_file.stat()
            created_at = _dt.datetime.fromtimestamp(
                iter_stat.st_mtime, tz=_dt.timezone.utc
            ).isoformat()
        else:
            created_at = ""

        # Coût par itération depuis l'historique
        cost_for_iter = 0.0
        for call in state_data.get("history", []):
            if call.get("iteration") == it:
                cost_for_iter += call.get("cost_usd", 0.0)

        # Durée par itération depuis le receipt
        duration_s = 0.0
        if receipt_data:
            for call in receipt_data.get("calls", []):
                if call.get("iteration") == it:
                    duration_s += call.get("latency_ms", 0) / 1000.0

        verdict_val = (
            state_data.get("final_verdict", {}).get("decision", "CONTINUE")
            if it == iterations
            else "CONTINUE"
        )

        versions_list.append(
            RunVersion(
                version_id=f"v{it}",
                run_id=run_id,
                created_at=created_at,
                iteration_count=it,
                final_verdict=verdict_val,
                total_cost_usd=cost_for_iter,
                status=status_val if it == iterations else "running",
                objective=objective,
            )
        )

    if not versions_list:
        console.print(
            f"[yellow]Aucune version trouvée pour le run '{run_id}'.[/yellow]"
        )
        return

    table = Table(title=f"Versions du run {run_id}")
    table.add_column("Version", style="cyan")
    table.add_column("Itération", justify="right")
    table.add_column("Statut")
    table.add_column("Coût (USD)", justify="right")
    table.add_column("Verdict")
    table.add_column("Durée (s)", justify="right")

    for v in versions_list:
        verdict_color = "green" if v.final_verdict == "STOP" else "yellow"
        cost_display = f"${v.total_cost_usd:.4f}" if v.total_cost_usd > 0 else "—"
        duration_display = (
            f"{receipt_data['total_duration_s']:.1f}"
            if receipt_data and v.version_id == f"v{iterations}"
            else "—"
        )
        table.add_row(
            v.version_id,
            str(v.iteration_count),
            v.status,
            cost_display,
            f"[{verdict_color}]{v.final_verdict}[/{verdict_color}]",
            duration_display,
        )

    console.print(table)


@app.command(name="diff")
def diff(
    run_id_1: str = typer.Argument(..., help="Premier run ID à comparer"),
    run_id_2: str = typer.Argument(..., help="Deuxième run ID à comparer"),
):
    """Compare deux runs : delta coûts, delta itérations, verdict changé."""
    state_1 = load_state(run_id_1)
    state_2 = load_state(run_id_2)

    if not state_1:
        console.print(f"[red]Run '{run_id_1}' introuvable.[/red]")
        raise typer.Exit(1)
    if not state_2:
        console.print(f"[red]Run '{run_id_2}' introuvable.[/red]")
        raise typer.Exit(1)

    cost_delta = state_2.accumulated_cost - state_1.accumulated_cost
    iter_delta = state_2.current_iteration - state_1.current_iteration

    verdict_a = (
        state_1.final_verdict.decision if state_1.final_verdict else state_1.status
    )
    verdict_b = (
        state_2.final_verdict.decision if state_2.final_verdict else state_2.status
    )
    verdict_changed = verdict_a != verdict_b

    # Artefacts
    artifacts_1 = len(state_1.artifacts)
    artifacts_2 = len(state_2.artifacts)
    new_artifacts = max(0, artifacts_2 - artifacts_1)
    removed_artifacts = max(0, artifacts_1 - artifacts_2)

    summary_parts = []
    summary_parts.append(
        f"Coût : {'+' if cost_delta >= 0 else ''}{cost_delta:.4f} USD"
    )
    summary_parts.append(
        f"Itérations : {'+' if iter_delta >= 0 else ''}{iter_delta}"
    )
    if verdict_changed:
        summary_parts.append(f"Verdict changé : {verdict_a} → {verdict_b}")
    else:
        summary_parts.append(f"Verdict inchangé : {verdict_a}")
    if new_artifacts or removed_artifacts:
        summary_parts.append(
            f"Artefacts : +{new_artifacts}/-{removed_artifacts}"
        )

    version_diff = VersionDiff(
        run_id=f"{run_id_1}..{run_id_2}",
        version_a=run_id_1,
        version_b=run_id_2,
        cost_delta_usd=cost_delta,
        iteration_delta=iter_delta,
        verdict_changed=verdict_changed,
        verdict_a=verdict_a,
        verdict_b=verdict_b,
        new_artifacts=new_artifacts,
        removed_artifacts=removed_artifacts,
        summary=", ".join(summary_parts),
    )

    # Affichage
    panel = Panel.fit(
        f"[bold]Diff : {run_id_1} vs {run_id_2}[/bold]\n"
        f"Coût Δ : {'[green]' if cost_delta <= 0 else '[red]'}"
        f"{'+' if cost_delta >= 0 else ''}{cost_delta:.4f} USD[/]\n"
        f"Itérations Δ : {'+' if iter_delta >= 0 else ''}{iter_delta}\n"
        f"Verdict : "
        f"{'[red]' if verdict_changed else '[green]'}"
        f"{verdict_a} → {verdict_b}{' (changé)' if verdict_changed else ' (inchangé)'}[/]\n"
        f"Artefacts : +{new_artifacts}/-{removed_artifacts}",
        border_style="cyan",
        title="Comparaison",
    )
    console.print(panel)
    console.print(f"\n[dim]{version_diff.summary}[/dim]")


@app.command(name="inspect")
def inspect_run(
    run_id: str = typer.Argument(..., help="ID du run à inspecter"),
):
    """Affiche les détails complets d'un run : état, appels, artefacts, synthèse."""
    state = load_state(run_id)
    if not state:
        console.print(f"[red]Run '{run_id}' introuvable.[/red]")
        raise typer.Exit(1)

    run_dir = RUNS_DIR / run_id

    # ── État ─────────────────────────────────────────────────────
    status_color = {
        "running": "yellow",
        "stopped": "green",
        "forced_stop": "yellow",
        "failed": "red",
        "budget_exceeded": "red",
    }.get(state.status, "white")

    header_lines = [
        f"[bold]Run #{state.run_id}[/bold]",
        f"Statut       : [{status_color}]{state.status}[/{status_color}]",
        f"Objectif     : {state.objective}",
        f"Variante     : {state.variant.value}",
        f"Itérations   : {state.current_iteration}/{state.max_iterations}",
        f"Coût total   : ${state.accumulated_cost:.4f}",
    ]
    if state.final_verdict:
        v_color = "green" if state.final_verdict.decision == "STOP" else "yellow"
        header_lines.append(
            f"Verdict      : [{v_color}]{state.final_verdict.decision}[/{v_color}]"
        )
        header_lines.append(f"Justification: {state.final_verdict.justification}")
    if state.last_error:
        header_lines.append(f"Erreur       : [red]{state.last_error}[/red]")

    console.print(
        Panel.fit("\n".join(header_lines), border_style="cyan", title="État")
    )

    # ── Historique des appels ────────────────────────────────────
    if state.history:
        table = Table(title="Historique des appels LLM")
        table.add_column("#", style="cyan")
        table.add_column("Rôle")
        table.add_column("Provider")
        table.add_column("Modèle")
        table.add_column("In tok", justify="right")
        table.add_column("Out tok", justify="right")
        table.add_column("Coût", justify="right")
        table.add_column("Latence", justify="right")

        for call in state.history:
            cost_str = (
                f"${call.cost_usd:.4f}" if call.cost_usd > 0 else "—"
            )
            in_tok = (
                f"~{call.input_tokens}"
                if call.token_count_estimated
                else str(call.input_tokens)
            )
            out_tok = (
                f"~{call.output_tokens}"
                if call.token_count_estimated
                else str(call.output_tokens)
            )
            table.add_row(
                str(call.iteration),
                call.role,
                call.provider,
                call.model,
                in_tok,
                out_tok,
                cost_str,
                f"{call.latency_ms}ms",
            )
        console.print(table)
    else:
        console.print("[dim]Aucun appel LLM enregistré.[/dim]")

    # ── Artefacts ────────────────────────────────────────────────
    if state.artifacts:
        console.print()
        console.print(Panel("[bold]Artefacts immuables[/bold]", border_style="blue"))
        for i, art in enumerate(state.artifacts, 1):
            art_type = art.artifact_type
            lang = f" ({art.language})" if art.language else ""
            content_preview = art.content[:120].replace("\n", " ")
            if len(art.content) > 120:
                content_preview += "…"
            console.print(
                f"  [{i}] {art_type}{lang} — itération {art.source_iteration}"
            )
            console.print(f"      {content_preview}")
    else:
        console.print("[dim]Aucun artefact.[/dim]")

    # ── Synthèse ─────────────────────────────────────────────────
    if state.last_synthesis:
        synth = state.last_synthesis
        synth_lines = [
            f"Objectif   : {synth.objective}",
            f"Décisions  : {'; '.join(synth.key_decisions)}",
        ]
        if synth.uncertainties:
            synth_lines.append(
                f"Incertain  : {'; '.join(synth.uncertainties)}"
            )
        synth_lines.append(
            f"Itérations : {synth.iteration_from} → {synth.iteration_to}"
        )
        synth_lines.append(f"Prochaine  : {synth.next_instruction}")
        console.print()
        console.print(
            Panel.fit(
                "\n".join(synth_lines),
                border_style="green",
                title="Dernière synthèse",
            )
        )
    else:
        console.print("[dim]Aucune synthèse enregistrée.[/dim]")

    # ── Fichiers du run ──────────────────────────────────────────
    if run_dir.exists():
        files = sorted(p.name for p in run_dir.iterdir() if p.is_file())
        if files:
            console.print()
            console.print(Panel("[bold]Fichiers du run[/bold]", border_style="dim"))
            for f in files:
                console.print(f"  {f}")


@app.command(name="list")
def list_cmd():
    """Liste tous les runs connus."""
    runs = list_runs()

    if not runs:
        console.print("[yellow]Aucun run trouve.[/yellow]")
        console.print("Lancez votre premiere cascade avec : "
                      "[cyan]goal run --objective \"...\"[/cyan]")
        return

    table = Table(title="Runs G.O.A.L. Cascade")
    table.add_column("Run ID", style="cyan")
    table.add_column("Objectif")
    table.add_column("Statut")
    table.add_column("Iterations", justify="right")

    for run in runs:
        status_color = {
            "running": "yellow",
            "stopped": "green",
            "forced_stop": "yellow",
            "failed": "red",
        }.get(run["status"], "white")
        table.add_row(
            run["run_id"],
            run["objective"],
            f"[{status_color}]{run['status']}[/{status_color}]",
            str(run["iterations"]),
        )

    console.print(table)


@app.command(name="rag-status")
def rag_status(
    run_id: str = typer.Argument(..., help="ID du run à inspecter"),
):
    """Affiche la preuve d'indexation et d'embedding d'un run."""
    path = RUNS_DIR / run_id / "rag-status.json"
    if not path.exists():
        console.print(f"[red]Reçu RAG absent : {path}[/red]")
        raise typer.Exit(1)
    console.print(Panel(path.read_text(encoding="utf-8"), title=str(path)))


@app.command(name="rag-sync")
def rag_sync(
    run_id: str = typer.Argument(..., help="ID du run à synchroniser"),
):
    """Relance l'indexation PostgreSQL et l'embedding sur ia-general."""
    try:
        result = RagBridge().sync_run(run_id)
    except RagSyncError as exc:
        path = RUNS_DIR / run_id / "rag-status.json"
        console.print(f"[bold red]Synchronisation RAG en échec : {exc}[/bold red]")
        console.print(f"Preuve locale : [cyan]{path}[/cyan]")
        raise typer.Exit(1) from exc
    console.print("[bold green]Synchronisation RAG vérifiée.[/bold green]")
    console.print_json(data=result)


@app.command()
def init(
    name: str = typer.Argument(..., help="Nom du projet"),
):
    """Initialise un nouveau projet G.O.A.L."""
    from pathlib import Path

    project_dir = Path(name)
    if project_dir.exists():
        console.print(f"[red]Le dossier '{name}' existe deja.[/red]")
        raise typer.Exit(1)

    project_dir.mkdir()
    (project_dir / ".goal").mkdir()
    (project_dir / "output").mkdir()

    # README minimal
    (project_dir / "README.md").write_text(
        f"# {name}\n\nProjet G.O.A.L. Cascade.\n",
        encoding="utf-8"
    )

    console.print(f"[green]Projet '{name}' cree.[/green]")
    console.print(f"\nStructure :")
    console.print(f"  {name}/")
    console.print(f"  ├── .goal/       (config locale)")
    console.print(f"  ├── output/      (livrables)")
    console.print(f"  └── README.md")


@app.command(name="plan")
def cascade_plan(
    spec: Path = typer.Argument(
        ..., help="Chemin vers le fichier de spécification (JSON/TOML/Markdown)"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help=(
            "Chemin du fichier config TOML. "
            f"Par défaut : {DEFAULT_CONFIG_PATH} si présent."
        ),
    ),
    provider: ProviderChoice = typer.Option(
        ProviderChoice.MOCK, "--provider", "-p",
        help="Provider : mock, kimi-cli ou kimi-code"
    ),
    output: Path = typer.Option(
        Path("plan.json"),
        "--output", "-o",
        help="Chemin de sortie pour le plan JSON (défaut : plan.json)",
    ),
    synthesizer_model: str | None = typer.Option(
        None,
        "--synthesizer-model",
        envvar="GOAL_SYNTHESIZER_MODEL",
        help="Modèle small/cheap dédié aux synthèses (obligatoire avec Kimi)",
    ),
):
    """Génère un plan de découpage modulaire depuis un fichier de spécification."""

    # ── 1. Vérifier que le fichier spec existe ───────────────────
    spec_path = spec.expanduser().resolve()
    if not spec_path.exists():
        console.print(
            f"[bold red]Fichier spec introuvable : {spec_path}[/bold red]"
        )
        raise typer.Exit(2)

    # ── 2. Charger la config TOML (optionnel) ───────────────────
    candidate_config_path = config or DEFAULT_CONFIG_PATH
    should_load_config = config is not None or candidate_config_path.exists()
    selected_provider: BaseProvider | None = None

    if should_load_config:
        if config is not None and not candidate_config_path.exists():
            console.print(
                f"[bold red]Config introuvable : "
                f"{candidate_config_path.expanduser()}[/bold red]"
            )
            raise typer.Exit(2)
        try:
            goal_config = load_goal_config(candidate_config_path)
        except (ValidationError, ValueError) as exc:
            console.print(
                f"[bold red]Config invalide ({candidate_config_path}): "
                f"{exc}[/bold red]"
            )
            raise typer.Exit(1) from exc
        _print_config_summary(candidate_config_path, goal_config.providers)

        # Les providers Kimi exigent un modèle explicite
        if (
            goal_config.providers.resolved_synthesizer in ("kimi-cli", "kimi-code")
            and not synthesizer_model
        ):
            typer.echo(
                "Erreur : --synthesizer-model est requis avec un provider Kimi",
                err=True,
            )
            raise typer.BadParameter(
                "requis avec un provider Kimi",
                param_hint="--synthesizer-model",
            )

        # Utiliser le synthesizer (tâche de planification = synthèse)
        selected_provider = _build_provider(
            goal_config.providers.resolved_synthesizer,
            synthesizer_model=synthesizer_model,
            config=goal_config,
        )

    # ── 3. Construire le provider (fallback) ─────────────────────
    if selected_provider is None:
        if synthesizer_model is not None:
            synthesizer_model = synthesizer_model.strip()
        selected_provider = _build_provider(
            provider.value,
            synthesizer_model=synthesizer_model,
        )

    # ── 4. Appeler ModuleGraph.from_spec ─────────────────────────
    console.print(
        f"[cyan]Analyse du spec : {spec_path}[/cyan]"
    )
    console.print(
        f"[cyan]Provider : {selected_provider.name}[/cyan]"
    )

    try:
        graph, plan = ModuleGraph.from_spec(spec_path, selected_provider)
    except Exception as exc:
        console.print(
            f"[bold red]Erreur lors de la planification : {exc}[/bold red]"
        )
        raise typer.Exit(1) from exc

    # ── 5. Sauvegarder le plan en plan.json ──────────────────────
    output_path = output.expanduser().resolve()
    plan_data = plan.model_dump()
    plan_data["_graph"] = graph.to_plan_dict()
    plan_data["_topological_order"] = graph.topological_order()
    plan_data["_batches"] = graph.parallel_batches()
    output_path.write_text(
        json.dumps(plan_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── 6. Afficher un résumé rich ───────────────────────────────
    batches = graph.parallel_batches()
    topo_order = graph.topological_order()
    total_lines = sum(m.estimated_lines for m in plan.modules)

    # Modules
    modules_table = Table(title="Modules")
    modules_table.add_column("ID", style="cyan")
    modules_table.add_column("Nom")
    modules_table.add_column("Lignes est.", justify="right")
    modules_table.add_column("Dépendances")
    modules_table.add_column("Invariants", justify="right")

    for mod in plan.modules:
        deps = ", ".join(mod.dependencies) if mod.dependencies else "—"
        modules_table.add_row(
            mod.module_id,
            mod.module_name,
            str(mod.estimated_lines),
            deps,
            str(len(mod.invariants)),
        )

    if plan.integration_module:
        im = plan.integration_module
        deps = ", ".join(im.dependencies) if im.dependencies else "—"
        modules_table.add_row(
            f"[bold]{im.module_id}[/bold]",
            f"[bold]{im.module_name}[/bold]",
            str(im.estimated_lines),
            deps,
            str(len(im.invariants)),
        )

    console.print(modules_table)

    # Résumé global
    summary_lines = [
        f"Modules        : {len(plan.modules)}"
        + (f" + intégration" if plan.integration_module else ""),
        f"Dépendances    : {len(plan.contracts)}",
        f"Batches        : {len(batches)}",
        f"Ordre topo     : {' → '.join(topo_order)}",
        f"Total lignes   : {total_lines:,}",
    ]
    if plan.integration_module:
        total_lines_all = total_lines + plan.integration_module.estimated_lines
        summary_lines.append(f"Avec intégr.   : {total_lines_all:,} lignes")

    console.print(
        Panel.fit(
            "\n".join(summary_lines),
            border_style="green",
            title="Résumé du plan",
        )
    )

    # Contrats
    if plan.contracts:
        contracts_table = Table(title="Contrats d'interface")
        contracts_table.add_column("ID", style="cyan")
        contracts_table.add_column("Producteur")
        contracts_table.add_column("Consommateur")
        contracts_table.add_column("Format")
        for c in plan.contracts:
            contracts_table.add_row(
                c.contract_id, c.producer, c.consumer, c.exchange_format
            )
        console.print(contracts_table)

    console.print(f"\n[green]✅ Plan sauvegardé : {output_path}[/green]")


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Run ID à reprendre"),
    audience: str = typer.Option(
        "", "--audience", "-a", help="Public cible"
    ),
    constraints: str = typer.Option(
        "", "--constraints", "-c", help="Contraintes (format, longueur, etc.)"
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help=(
            "Chemin du fichier config TOML. "
            f"Par défaut : {DEFAULT_CONFIG_PATH} si présent."
        ),
    ),
    synthesizer_model: str | None = typer.Option(
        None,
        "--synthesizer-model",
        envvar="GOAL_SYNTHESIZER_MODEL",
        help="Modèle small/cheap dédié aux synthèses (obligatoire avec Kimi)",
    ),
    no_synth: bool = typer.Option(
        False,
        "--no-synth",
        help="Désactiver la synthèse orientée objectif (debug : la sortie brute est passée telle quelle)",
    ),
):
    """Reprend une cascade interrompue depuis le dernier checkpoint SQLite."""
    from .orchestrator.cascade_executor import CascadeExecutor
    from .orchestrator.state_manager import RUNS_DIR, load_state

    if synthesizer_model is not None:
        synthesizer_model = synthesizer_model.strip()

    run_dir = RUNS_DIR / run_id
    checkpoint_dir = run_dir / ".checkpoints"
    checkpoint_path = checkpoint_dir / "checkpoint.db"

    if not checkpoint_path.exists():
        console.print(
            f"[bold red]Aucun checkpoint trouvé pour le run '{run_id}'[/bold red]"
        )
        console.print(f"  Chemin attendu : {checkpoint_path}")
        raise typer.Exit(1)

    # Charger l'état initial depuis le checkpoint
    console.print(
        f"[cyan]Reprise du run {run_id} depuis le checkpoint SQLite...[/cyan]"
    )
    console.print(f"  Checkpoint : [cyan]{checkpoint_path}[/cyan]")

    # --- Construction des providers (même logique que run()) ---
    candidate_config_path = config or DEFAULT_CONFIG_PATH
    should_load_config = config is not None or candidate_config_path.exists()
    budget_tracker: BudgetTracker | None = None

    if should_load_config:
        if config is not None and not candidate_config_path.exists():
            console.print(
                f"[bold red]Config introuvable : "
                f"{candidate_config_path.expanduser()}[/bold red]"
            )
            raise typer.Exit(2)
        try:
            goal_config = load_goal_config(candidate_config_path)
        except (ValidationError, ValueError) as exc:
            console.print(
                f"[bold red]Config invalide ({candidate_config_path}): "
                f"{exc}[/bold red]"
            )
            raise typer.Exit(1) from exc
        _print_config_summary(candidate_config_path, goal_config.providers)

        if (
            goal_config.providers.resolved_synthesizer in ("kimi-cli", "kimi-code")
            and not synthesizer_model
        ):
            typer.echo(
                "Erreur : --synthesizer-model est requis avec un provider Kimi",
                err=True,
            )
            raise typer.BadParameter(
                "requis avec un provider Kimi",
                param_hint="--synthesizer-model",
            )

        provider_names = set(goal_config.providers.resolved_role_mapping.values())
        providers_by_name = {
            provider_name: _build_provider(provider_name, config=goal_config)
            for provider_name in provider_names
        }
        selected_provider = RoleMappedProvider(
            providers_by_name=providers_by_name,
            role_mapping=goal_config.providers.resolved_role_mapping,
        )
        selected_synthesizer_provider = _build_provider(
            goal_config.providers.resolved_synthesizer,
            synthesizer_model=synthesizer_model,
            config=goal_config,
        )
        budget_tracker = BudgetTracker(
            config=goal_config.budget,
            daily_total_path=RUNS_DIR.parent / "budget_daily.json",
        )
    else:
        # Fallback Mock (comportement legacy)
        selected_provider = MockProvider()
        selected_synthesizer_provider = MockProvider()

    # Créer un executor avec les vrais providers
    executor = CascadeExecutor(
        provider=selected_provider,
        synthesizer_provider=selected_synthesizer_provider,
        budget_tracker=budget_tracker,
    )

    # ── Budget check fail fast (avant reprise) ──────────────────
    pre_state = load_state(run_id)
    if pre_state is not None and budget_tracker is not None:
        if budget_tracker.is_exceeded(run_id, pre_state.accumulated_cost):
            console.print(
                f"[bold yellow]⛔ Budget déjà dépassé pour le run '{run_id}' "
                f"(${pre_state.accumulated_cost:.4f} / "
                f"${budget_tracker.config.max_per_run_usd:.2f}).[/bold yellow]"
            )
            console.print(
                "[yellow]Reprise impossible : ajustez le budget dans la config TOML "
                "ou relancez un nouveau run.[/yellow]"
            )
            raise typer.Exit(1)

    # ── Contexte de reprise (avant exécution) ───────────────────
    if pre_state is not None:
        status_color = {
            "running": "yellow",
            "stopped": "green",
            "forced_stop": "yellow",
            "budget_exceeded": "red",
            "failed": "red",
        }.get(pre_state.status, "white")

        resume_lines = [
            f"[bold]Reprise du run {run_id}[/bold]",
            f"Itération : [cyan]{pre_state.current_iteration}[/cyan]"
            f"/{pre_state.max_iterations}",
            f"Statut : [{status_color}]{pre_state.status}[/{status_color}]",
            f"Coût accumulé : [yellow]${pre_state.accumulated_cost:.4f}[/yellow]",
        ]
        if pre_state.last_synthesis:
            resume_lines.append(
                f"Objectif synthèse : [dim]{pre_state.last_synthesis.objective}[/dim]"
            )
        console.print()
        console.print(
            Panel.fit(
                "\n".join(resume_lines),
                border_style="cyan",
                title="Contexte de reprise",
            )
        )

    try:
        state = executor.resume(
            run_id,
            audience=redact_sensitive(audience) if audience else "",
            constraints=redact_sensitive(constraints) if constraints else "",
            verbose=True,
            no_synth=no_synth,
        )
    except FileNotFoundError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(f"[bold red]Erreur lors de la reprise : {exc}[/bold red]")
        raise typer.Exit(1) from exc

    # Afficher le résultat
    console.print()
    if state.status == "stopped":
        console.print(
            f"[bold green]Cascade reprise et terminée en "
            f"{state.current_iteration} iterations[/bold green]"
        )
    elif state.status == "forced_stop":
        console.print(
            f"[bold yellow]Cascade reprise et stoppée (limite atteinte) "
            f"après {state.current_iteration} iterations[/bold yellow]"
        )
    else:
        console.print(
            f"[bold cyan]Cascade reprise — statut : {state.status}[/bold cyan]"
        )

    if state.final_verdict:
        verdict = state.final_verdict
        color = "green" if verdict.decision == "STOP" else "yellow"
        console.print(
            f"\nVerdict : [{color}]{verdict.decision}[/{color}]"
        )
        console.print(f"Justification : {verdict.justification}")

    console.print(f"\nRun ID : [cyan]{state.run_id}[/cyan]")
    console.print(f"Livrable : {run_dir / 'final_output.md'}")


@app.command(name="cascade-run")
def cascade_run(
    plan_path: str = typer.Argument(..., help="Chemin vers le fichier plan.json"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Logs détaillés"),
) -> None:
    """Exécute toutes les cascades d'un plan.json.

    Multi-cascade : exécuteur topologique + intégration finale.
    """
    import json as _json
    from .multicascade.module_graph import ModuleGraph
    from .multicascade.multi_executor import MultiCascadeExecutor

    plan_file = Path(plan_path)
    if not plan_file.exists():
        console.print(f"[red]Fichier plan introuvable : {plan_path}[/red]")
        raise typer.Exit(1)

    try:
        graph = ModuleGraph.from_plan_file(plan_file)
    except Exception as exc:
        console.print(f"[red]Plan invalide : {exc}[/red]")
        raise typer.Exit(1)

    plan_data = _json.loads(plan_file.read_text(encoding="utf-8"))
    module_count = len(plan_data.get("modules", []))
    batch_count = len(graph.parallel_batches())

    console.print(f"[blue]Exécution du plan : {module_count} modules, {batch_count} batches[/blue]")
    console.print(f"  Ordre topologique : {graph.topological_order()}")
    for i, batch in enumerate(graph.parallel_batches()):
        console.print(f"  Batch {i+1} : {batch}")

    # Construire l'exécuteur avec MockProvider comme fallback sûr
    provider = MockProvider()
    synthesizer_provider = MockProvider()
    cascade_executor = CascadeExecutor(
        provider=provider,
        synthesizer_provider=synthesizer_provider,
    )

    multi_executor = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=cascade_executor,
    )

    try:
        module_results = multi_executor.run_all()
    except Exception as exc:
        console.print(f"[red]Échec d'un module : {exc}[/red]")
        raise typer.Exit(1)

    console.print("\n[blue]Cascade d'intégration...[/blue]")
    try:
        integration_state = multi_executor.run_integration(module_results)
    except Exception as exc:
        console.print(f"[red]Intégration échouée : {exc}[/red]")
        raise typer.Exit(1)

    total_cost = sum(s.accumulated_cost for s in module_results.values())
    total_cost += integration_state.accumulated_cost
    total_iterations = sum(s.current_iteration for s in module_results.values())
    total_iterations += integration_state.current_iteration

    console.print(f"\n[green]Multi-cascade terminée[/green]")
    console.print(f"  Modules : {len(module_results)}")
    console.print(f"  Itérations totales : {total_iterations}")
    console.print(f"  Coût total : ${total_cost:.4f}")
    console.print(
        f"  Intégration : "
        f"{integration_state.final_verdict.decision if integration_state.final_verdict else 'N/A'}"
    )


if __name__ == "__main__":
    app()
