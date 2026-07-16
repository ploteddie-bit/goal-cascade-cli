"""Cascade Executor — le moteur d'execution de la cascade G.O.A.L.

Phase 1 (POC) :
- Executeur lineaire (iteration 1 -> 4)
- State JSON persistant
- Limite absolue de 5 iterations
- Verdict STOP/CONTINUE

Phase ulterieures :
- Synthesizer (synthese orientee objectif)
- Detection de derive (cosinus)
- Budget tracker
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

if TYPE_CHECKING:
    from ..config import GoalConfig

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

from ..audit_journal import AuditJournal, redact_sensitive
from ..prompts import PromptLoader
from ..providers.base import BaseProvider
from ..schemas.models import (
    CascadeState,
    GoalOrientedSynthesis,
    InterfaceContract,
    IterationRole,
    LLMCallRecord,
    RunReceipt,
    Variant,
    Verdict,
)
from . import state_manager
from .budget_tracker import BudgetTracker
from .cicd_hook import CICDHook, DeterministicCheckResult
from .synthesizer import SynthesisError, Synthesizer

# Tiers de modele par role (pour la cascade ascendante)
ROLE_TIERS = {
    IterationRole.PRODUCER: "small",
    IterationRole.CRITIC: "medium",
    IterationRole.ADVERSARY: "large",
    IterationRole.ARBITER: "xlarge",
}

# Templates par variante et par role
ROLE_TEMPLATES = {
    Variant.A: {
        IterationRole.PRODUCER: "iteration_1.j2",
        IterationRole.CRITIC: "iteration_2.j2",
        IterationRole.ADVERSARY: "iteration_3.j2",
        IterationRole.ARBITER: "iteration_4.j2",
    },
    Variant.B: {
        IterationRole.PRODUCER: "technical_iteration_1.j2",
        IterationRole.CRITIC: "technical_iteration_2.j2",
        IterationRole.ADVERSARY: "technical_iteration_3.j2",
        IterationRole.ARBITER: "technical_iteration_4.j2",
    },
}

ROLE_LABELS = {
    IterationRole.PRODUCER: "Producteur",
    IterationRole.CRITIC: "Critique",
    IterationRole.ADVERSARY: "Adversaire",
    IterationRole.ARBITER: "Arbitre",
}


class CascadeExecutor:
    """Execute une cascade G.O.A.L. complete."""

    def __init__(
        self,
        provider: BaseProvider,
        synthesizer_provider: BaseProvider,
        prompt_loader: PromptLoader | None = None,
        rag_bridge=None,
        budget_tracker: BudgetTracker | None = None,
        cicd_hook: CICDHook | None = None,
        enable_prompt_overrides: bool = True,
    ):
        if synthesizer_provider is provider:
            raise ValueError("Le synthétiseur exige une instance de provider distincte")
        self.provider = provider
        self.synthesizer_provider = synthesizer_provider
        self.prompt_loader = prompt_loader or PromptLoader()
        self.synthesizer = Synthesizer(
            self.synthesizer_provider,
            self.prompt_loader,
        )
        self.rag_bridge = rag_bridge
        self._budget = budget_tracker
        # 🆕 A1-A6 — Hook CI/CD déterministe appliqué après chaque synthèse
        # et avant le verdict de l'arbitre. Ne JAMAIS déléguer au LLM une
        # vérification qu'un outil déterministe peut faire.
        self._cicd = cicd_hook or CICDHook()
        # 🆕 O4 — Hot-reload des prompts par run (overrides sauvegardés
        # par le dashboard dans ~/.goal/runs/{id}/prompts/*.j2)
        self._enable_prompt_overrides = enable_prompt_overrides
        self._prompt_resolver = None  # lazy-init (besoin de run_id)

    def init_state(
        self,
        objective: str,
        variant: Variant = Variant.A,
        audience: str = "",
        constraints: str = "",
    ) -> CascadeState:
        """Cree un nouvel etat de cascade."""
        return CascadeState(
            run_id=uuid.uuid4().hex[:8],
            objective=redact_sensitive(objective),
            variant=variant,
            current_iteration=0,
            max_iterations=5,
        )

    def run(
        self,
        state: CascadeState,
        audience: str = "",
        constraints: str = "",
        verbose: bool = True,
        no_synth: bool = False,
    ) -> CascadeState:
        """Execute la cascade jusqu'au verdict STOP ou la limite."""

        journal = AuditJournal(state.run_id)
        start_time = datetime.now()
        journal.record_event(
            "run_started",
            objective=state.objective,
            variant=state.variant.value,
            provider=self.provider.name,
            synthesizer_provider=self.synthesizer_provider.name,
            no_synth=no_synth,
        )
        state_manager.save_state(state)

        audience = redact_sensitive(audience)
        constraints = redact_sensitive(constraints)

        try:
            state = self._run_with_graph(
                state, audience, constraints, verbose, journal, no_synth=no_synth
            )
        except Exception as exc:
            state.status = "failed"
            state.last_error = redact_sensitive(str(exc))
            state_manager.save_state(state)
            journal.record_error(exc)
            raise
        finally:
            self._finalize_run(state, journal, start_time)

        return state

    def _finalize_run(
        self,
        state: CascadeState,
        journal: AuditJournal,
        start_time: datetime,
    ) -> None:
        """Finalise un run : état, métadonnées, reçu de coût et sync RAG.

        Partagé entre ``run()`` et ``resume()`` pour garantir que les deux
        chemins produisent exactement les mêmes artefacts de transparence
        (métadonnées du journal, receipt.json et preuve RAG).
        """
        state_manager.save_state(state)
        duration_s = (datetime.now() - start_time).total_seconds()
        metadata = {
            "objective": state.objective,
            "variant": state.variant.value,
            "provider": self.provider.name,
            "synthesizer_provider": self.synthesizer_provider.name,
            "status": state.status,
            "iterations": state.current_iteration,
            "verdict": (state.final_verdict.decision if state.final_verdict else "absent"),
            "last_error": state.last_error or "aucune",
        }
        journal.finalize(metadata)
        try:
            receipt = self.build_receipt(state, duration_s)
            receipt_path = state_manager.save_receipt(state.run_id, receipt)
            journal.record_file("receipt_saved", receipt_path)
            journal.refresh_timeline()
        except Exception as exc:
            journal.record_error(exc)
            journal.refresh_timeline()
        if self.rag_bridge is not None:
            try:
                self.rag_bridge.sync_run(state.run_id, journal=journal)
            except Exception as exc:
                journal.record_error(exc)
                journal.refresh_timeline()

    def _run_with_graph(
        self,
        state: CascadeState,
        audience: str,
        constraints: str,
        verbose: bool,
        journal: AuditJournal,
        no_synth: bool = False,
    ) -> CascadeState:
        """Exécute la cascade via le CascadeGraph 6 nœuds + checkpointing SQLite.

        Le graphe LangGraph à 6 nœuds (producer/synth/critic/synth/
        adversary/synth/arbiter/verdict) gère l'orchestration, le
        checkpointing et la détection de dérive. Le journal d'audit
        capture chaque transition.

        Args:
            state: État de cascade à exécuter.
            audience: Public cible (passé aux prompts).
            constraints: Contraintes format/longueur.
            verbose: Journalisation détaillée (côté CLI).
            journal: AuditJournal pour la traçabilité permanente.
            no_synth: Désactiver la synthèse orientée objectif.

        Returns:
            CascadeState final (status, verdict, history, etc.).
        """
        from .cascade_graph import CascadeGraph

        run_dir = state_manager.get_run_dir(state.run_id)
        checkpoint_dir = state_manager.ensure_private_dir(run_dir / ".checkpoints")
        checkpoint_path = checkpoint_dir / "checkpoint.db"

        graph_instance = CascadeGraph(
            provider=self.provider,
            synthesizer_provider=self.synthesizer_provider,
            synthesizer=self.synthesizer,
            budget_tracker=self._budget,
            prompt_loader=self.prompt_loader,
            journal=journal,
            cicd_hook=self._cicd,
            audience=audience,
            constraints=constraints,
            no_synth=no_synth,
            prompt_resolver=self._prompt_resolver,
        )

        app, checkpointer = graph_instance.compile_with_sqlite(checkpoint_path)

        # Q1 : fermer la connexion SQLite après chaque cascade terminée.
        # Le caller (run ou resume) doit appeler close_sqlite() dans finally.

        # État initial : CascadeState sérialisé en dict
        initial_state = state.model_dump()
        config = {"configurable": {"thread_id": state.run_id}}

        if verbose:
            print(f"\n  Cascade 6 nœuds démarrée pour {state.run_id}")

        try:
            result = app.invoke(initial_state, config)
        finally:
            # Q1 : fermer la connexion SQLite pour éviter les fuites
            # et les verrous persistants sur les runs dashboard.
            graph_instance.close_sqlite()

        # Le résultat est un dict conforme au schéma CascadeState
        return CascadeState.model_validate(result)

    def resume(
        self,
        run_id: str,
        config: GoalConfig | None = None,
        audience: str = "",
        constraints: str = "",
        verbose: bool = True,
        no_synth: bool = False,
    ) -> CascadeState:
        """Reprend une cascade interrompue depuis le dernier checkpoint SQLite.

        Args:
            run_id: ID du run à reprendre.
            config: Si fourni, reconstruit les providers depuis cette config
                au lieu de réutiliser ceux du constructeur.
            audience: Public cible.
            constraints: Contraintes format/longueur.
            verbose: Journalisation détaillée.
            no_synth: Désactiver la synthèse orientée objectif.

        Raises:
            TypeError: Si CascadeExecutor est frozen/slots (mutation impossible).
            FileNotFoundError: Si aucun checkpoint valide n'existe pour run_id.

        Q4 — LIMITATION DOCUMENTÉE : double comptage coût possible.
        ============================================================
        ``resume()`` recharge l'état depuis le checkpoint SQLite (via
        ``app.get_state()``) puis relance ``_run_with_graph()`` qui
        ré-exécute la cascade depuis le début du checkpoint. Si LangGraph
        ré-exécute des nœuds déjà terminés (bug connu de certaines versions),
        le coût des appels LLM peut être compté deux fois : une fois dans
        le checkpoint et une fois dans la re-exécution.

        Mitigation : ``state.accumulated_cost`` est repris du checkpoint AVANT
        la reprise. Si LangGraph ré-exécute les nœuds, les coûts SONT ajoutés
        une seconde fois à ``state.history``. Le budget_tracker n'a pas de
        mémoire persistante entre les sessions (il reprend à 0).

        Incertitude : ce comportement dépend de la version de LangGraph.
        Testé avec ``langgraph==1.2.9`` (see A6) et fonctionne correctement
        (ré-exécution propre). Mettre à jour la doc si LangGraph est upgradé.
        """
        from .cascade_graph import CascadeGraph

        # Reconstruction des providers depuis config si fournie.
        if config is not None:
            from .execution_context import build_execution_context

            if hasattr(self, "__slots__") or getattr(type(self), "__frozen__", False):
                raise TypeError(
                    "CascadeExecutor est frozen/slots — impossible de "
                    "reconstruire les providers dans resume(). "
                    "Retirez @dataclass(frozen=True) ou __slots__."
                )

            ctx = build_execution_context(config)
            self.provider = ctx.provider
            self.synthesizer_provider = ctx.synthesizer_provider
            self.synthesizer = Synthesizer(self.synthesizer_provider, self.prompt_loader)
            self._budget = ctx.budget_tracker

        run_dir = state_manager.get_run_dir(run_id)
        checkpoint_dir = run_dir / ".checkpoints"
        checkpoint_path = checkpoint_dir / "checkpoint.db"

        if not checkpoint_path.exists():
            raise FileNotFoundError(
                f"Aucun checkpoint trouvé pour le run {run_id} : {checkpoint_path}"
            )

        # Charger l'état depuis le checkpoint via un CascadeGraph de récupération.
        graph_instance = CascadeGraph(
            provider=self.provider,
            synthesizer_provider=self.synthesizer_provider,
            synthesizer=self.synthesizer,
            budget_tracker=self._budget,
            prompt_loader=self.prompt_loader,
        )
        app, checkpointer = graph_instance.compile_with_sqlite(checkpoint_path)

        config_dict = {"configurable": {"thread_id": run_id}}
        saved = app.get_state(config_dict)

        if not saved or not saved.values:
            raise FileNotFoundError(f"Checkpoint vide pour le run {run_id}")

        # Le state du graphe est directement un CascadeState (sérialisé en dict)
        try:
            state = CascadeState.model_validate(saved.values)
        except Exception as exc:
            raise FileNotFoundError(
                f"Pas de CascadeState valide dans le checkpoint du run {run_id} : {exc}"
            ) from exc

        journal = AuditJournal(run_id)
        start_time = datetime.now()
        journal.record_event(
            "resume_started",
            objective=state.objective,
            variant=state.variant.value,
            provider=self.provider.name,
            synthesizer_provider=self.synthesizer_provider.name,
            no_synth=no_synth,
        )

        audience = redact_sensitive(audience)
        constraints = redact_sensitive(constraints)

        # Relancer avec le vrai graphe, puis finaliser comme run() :
        # reçu de coût, métadonnées et sync RAG (angle mort corrigé).
        try:
            state = self._run_with_graph(
                state, audience, constraints, verbose, journal, no_synth=no_synth
            )
        except Exception as exc:
            state.status = "failed"
            state.last_error = redact_sensitive(str(exc))
            state_manager.save_state(state)
            journal.record_error(exc)
            raise
        finally:
            self._finalize_run(state, journal, start_time)

        return state

    def _build_prompt(
        self,
        state: CascadeState,
        role: IterationRole,
        audience: str = "",
        constraints: str = "",
    ) -> str:
        """Construit le prompt pour une iteration donnee.

        O4 : si ``self._enable_prompt_overrides`` est True et qu'un override
        existe dans ``~/.goal/runs/{state.run_id}/prompts/``, il est utilisé
        à la place du template par défaut. Permet le hot-reload.
        """
        template_name = ROLE_TEMPLATES[state.variant].get(role, "iteration_1.j2")

        # Contexte de rendu (commun override + défaut)
        context = self._build_prompt_context(state, role, audience, constraints)

        # O4 : tentative d'override par run
        if self._enable_prompt_overrides:
            override_source = self._get_override_source(template_name, state.run_id)
            if override_source is not None:
                # Rendu via Environment.from_string (la source est du
                # Jinja2 brut, pas un nom de template)
                try:
                    return (
                        self.prompt_loader.env.from_string(override_source)
                        .render(**context)
                    )
                except Exception as exc:
                    logger.warning(
                        "prompt_override_render_echec template=%s exc=%s — fallback",
                        template_name, exc,
                    )

        # Chemin standard : render par nom de template
        return self.prompt_loader.render(template_name, **context)

    def _build_prompt_context(
        self,
        state: CascadeState,
        role: IterationRole,
        audience: str = "",
        constraints: str = "",
    ) -> dict[str, Any]:
        """Construit le contexte (variables) pour le rendu du prompt.

        Variables exposées aux templates Jinja2 :
        - objective, audience, constraints, artifacts
        - previous_output (sortie brute de l'itération précédente, sauf pour l'arbitre)
        - last_synthesis (synthèse consolidée pour les itérations 2+)
        """
        previous_output = ""
        if state.history and role != IterationRole.ARBITER:
            previous_output = state.history[-1].raw_output

        last_synthesis = ""
        if state.last_synthesis:
            last_synthesis = state.last_synthesis.model_dump_json(indent=2)

        artifacts = ""
        if state.artifacts:
            blocks = []
            for artifact in state.artifacts:
                language = artifact.language or "text"
                blocks.append(f"```{language}\n{artifact.content}\n```")
            artifacts = "\n\n".join(blocks)

        return {
            "objective": state.objective,
            "previous_output": previous_output,
            "last_synthesis": last_synthesis,
            "audience": audience,
            "constraints": constraints,
            "artifacts": artifacts,
        }

    def _get_override_source(self, template_name: str, run_id: str) -> str | None:
        """Tente de charger l'override du run. Retourne None si absent/invalide.

        L'override permet de modifier le prompt SANS redémarrer la cascade
        (hot-reload). Le fichier est relu à chaque appel.
        """
        from .prompt_resolver import PromptResolver
        from ..orchestrator import state_manager

        if self._prompt_resolver is None:
            self._prompt_resolver = PromptResolver(runs_dir=state_manager.RUNS_DIR)
        try:
            source = self._prompt_resolver.charger(template_name, id_cascade=run_id)
            # Heuristique simple : si l'override == défaut, considérer qu'il n'y en a pas
            try:
                default_source, _, _ = self.prompt_loader.env.loader.get_source(
                    self.prompt_loader.env, template_name
                )
                if source == default_source:
                    return None
            except Exception:
                pass
            return source
        except Exception as exc:
            logger.debug(
                "prompt_resolver_echec run=%s template=%s exc=%s",
                run_id, template_name, exc,
            )
            return None

    def _run_cicd_checks(
        self,
        artifacts: list,
        journal: AuditJournal,
    ) -> DeterministicCheckResult:
        """Vérifie les artefacts via le hook CI/CD déterministe.

        La cascade unique n'a pas de contrat d'interface explicite (elle
        n'est pas dans un multi-cascade). On crée un contrat interne
        permissif qui accepte tout type d'artefact : c'est le hook qui
        décide quels types il sait vérifier.
        """
        if not artifacts:
            return DeterministicCheckResult(passed=True)

        contract = InterfaceContract(
            contract_id=f"cicd-{uuid.uuid4().hex[:6]}",
            producer_module="cascade",
            consumer_module="cascade",
            output_description="auto-detect",
            input_description="auto-detect",
            exchange_format="auto",
        )
        result = self._cicd.run_deterministic_checks(contract, list(artifacts))

        # Trace l'événement dans le journal pour auditabilité.
        journal.record_event(
            "cicd_checks",
            passed=result.passed,
            artifacts=len(artifacts),
            failures=len(result.failures),
        )
        return result

    def _parse_verdict(self, text: str) -> Verdict:
        """Valide l'objet JSON terminal conforme au schéma Verdict."""
        stripped = text.rstrip()
        if not stripped:
            raise ValueError("Verdict JSON invalide ou absent")

        try:
            if stripped.endswith("```"):
                closing_fence = len(stripped) - 3
                opening_fence = stripped.lower().rfind(
                    "```json",
                    0,
                    closing_fence,
                )
                if opening_fence == -1:
                    raise ValueError("Bloc JSON terminal absent")
                candidate = stripped[opening_fence + len("```json") : closing_fence]
                data = json.loads(candidate.strip())
            else:
                decoder = json.JSONDecoder()
                decoded: list[tuple[object, int]] = []
                cursor = 0
                while cursor < len(stripped):
                    start = stripped.find("{", cursor)
                    if start == -1:
                        break
                    try:
                        value, consumed = decoder.raw_decode(stripped[start:])
                    except json.JSONDecodeError:
                        cursor = start + 1
                        continue
                    end = start + consumed
                    decoded.append((value, end))
                    cursor = end

                if not decoded:
                    raise ValueError("Objet JSON terminal absent")
                data, end = decoded[-1]
                if stripped[end:].strip():
                    raise ValueError("Texte présent après le verdict JSON")

            return Verdict.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("Verdict JSON"):
                raise
            try:
                details = str(exc)
            except Exception:
                details = type(exc).__name__
            raise ValueError(f"Verdict JSON invalide ou absent : {details}") from exc

    def build_receipt(self, state: CascadeState, duration_s: float) -> RunReceipt:
        """Construit le RunReceipt depuis l'etat final de la cascade.

        Délègue la construction à RunReceipt.from_calls() qui calcule
        automatiquement total_cost, cache_hit_rate et projected_monthly_cost.
        """
        runs_per_day = (
            self._budget.config.runs_per_day_projection if self._budget is not None else 10
        )
        return RunReceipt.from_calls(
            run_id=state.run_id,
            objective=state.objective,
            verdict=(state.final_verdict.decision if state.final_verdict else "absent"),
            duration_s=duration_s,
            calls=list(state.history),
            runs_per_day=runs_per_day,
        )
