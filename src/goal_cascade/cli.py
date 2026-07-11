"""CLI entry point — G.O.A.L. Cascade.

Usage:
    goal run --objective "..." [--provider mock|kimi-cli|kimi-code]
    goal status [run_id]
    goal list
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

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
from .schemas.models import Variant

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
    "rag_status",
    "rag_sync",
    "init",
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

    if state.final_verdict:
        color = "green" if state.final_verdict.decision == "STOP" else "yellow"
        console.print(
            f"\nVerdict : [{color}]{state.final_verdict.decision}[/{color}]"
        )
        console.print(f"  {state.final_verdict.justification}")


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


if __name__ == "__main__":
    app()
