"""CLI entry point — G.O.A.L. Cascade.

Usage:
    goal run --objective "..." [--provider mock|kimi-cli|kimi-code]
    goal status [run_id]
    goal list
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .orchestrator.cascade_executor import CascadeExecutor
from .orchestrator.state_manager import RUNS_DIR, list_runs, load_state
from .providers.mock import MockProvider
from .providers.kimi_command import KimiBackend, KimiCommandProvider
from .rag_bridge import RagBridge, RagSyncError
from .schemas.models import Variant

app = typer.Typer(
    name="goal",
    help="G.O.A.L. Cascade — Multi-agent cascade framework",
    no_args_is_help=True,
)
console = Console()


class ProviderChoice(str, Enum):
    MOCK = "mock"
    KIMI_CLI = "kimi-cli"
    KIMI_CODE = "kimi-code"


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
    audience: str = typer.Option(
        "", "--audience", "-a",
        help="Public cible"
    ),
    constraints: str = typer.Option(
        "", "--constraints", "-c",
        help="Contraintes (format, longueur, etc.)"
    ),
):
    """Lance une cascade G.O.A.L. complete."""

    # Selection du provider. Chaque appel Kimi omet volontairement les
    # options de reprise : une iteration = une nouvelle session.
    if provider == ProviderChoice.MOCK:
        selected_provider = MockProvider()
        provider_label = "Mock (pas d'API)"
    elif provider == ProviderChoice.KIMI_CLI:
        selected_provider = KimiCommandProvider(
            backend=KimiBackend.CLI,
            work_dir=Path.cwd(),
        )
        provider_label = "Kimi CLI 1.x (sessions non interactives)"
    else:
        selected_provider = KimiCommandProvider(
            backend=KimiBackend.CODE,
            work_dir=Path.cwd(),
        )
        provider_label = "Kimi Code 0.x (sessions non interactives)"

    # Afficher l'en-tete
    header = Panel.fit(
        f"[bold]G.O.A.L. Cascade[/bold]\n"
        f"Objectif : {objective}\n"
        f"Variante : {variant.value} "
        f"({'redactionnel' if variant == Variant.A else 'technique'})\n"
        f"Provider : {provider_label}",
        border_style="cyan",
    )
    console.print(header)

    # Initialiser et executer
    executor = CascadeExecutor(provider=selected_provider, rag_bridge=RagBridge())
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


if __name__ == "__main__":
    app()
