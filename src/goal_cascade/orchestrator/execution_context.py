"""Factory pour la construction du contexte d'exécution partagé entre les commandes CLI.

But : factoriser le pattern dupliqué dans ``run()``, ``resume()`` et ``cascade_run()`` :

    RoleMappedProvider(multi-rôles)
        + provider synthétiseur (instance distincte)
        + BudgetTracker (daily_total_path standardisé)

Ce triplet est strictement identique entre les trois commandes ; seule la branche
fallback ``MockProvider`` (CLI-specific, dépend de ``--provider`` et de la présence
d'une config) reste inline dans ``cli.py``.

⚠️ CYCLE D'IMPORT — IMPORT DIFFÉRÉ (lazy) OBLIGATOIRE
=====================================================
``cli.py`` importe ``orchestrator.cascade_executor`` (lignes 29 et 1287 de ``cli.py``).
La factory doit appeler ``_build_provider``, défini dans ``cli.py:100``.

Si on importait ``from ..cli import _build_provider`` au top-level ici, on aurait :

    cli.py → orchestrator.cascade_executor → execution_context → cli._build_provider → cycle.

L'import à l'intérieur de la fonction ``build_execution_context`` n'est exécuté
qu'à l'appel, pas au chargement du module. Pas de cycle.

Test de non-régression (à exécuter avant chaque release) :

    python -c "import goal_cascade.orchestrator.execution_context; \
               import sys; assert 'goal_cascade.cli' not in sys.modules, \
               'cycle: cli chargé par execution_context'; print('OK')"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..providers.base import BaseProvider
from ..providers.router import RoleMappedProvider
from .budget_tracker import BudgetTracker
from .state_manager import RUNS_DIR

if TYPE_CHECKING:
    from ..config import GoalConfig
    from .cascade_executor import CascadeExecutor

# Rôles G.O.A.L. obligatoires — le framework exige ces 4 perspectives distinctes
# (Producteur, Critique, Adversaire, Arbitre) pour garantir la diversité cognitive.
REQUIRED_GOAL_ROLES: frozenset[str] = frozenset({"producer", "critic", "adversary", "arbiter"})


@dataclass(frozen=True)
class ExecutionContext:
    """Contexte d'exécution résolu pour une cascade.

    .. note:: Immuabilité partielle

        ``frozen=True`` empêche la **réassignation** des attributs
        (``ctx.provider = X`` lève ``FrozenInstanceError``). En revanche, les
        objets référencés (``provider``, ``synthesizer_provider``,
        ``budget_tracker``) restent **mutables** : leur état interne peut changer.
        C'est intentionnel — les providers et le budget tracker doivent accumuler
        de l'état (compteurs, coûts) pendant l'exécution.

    Attributes:
        provider: Provider multi-rôles (RoleMappedProvider) ou MockProvider
            (branche legacy, jamais retourné par ``build_execution_context`` —
            le fallback Mock est géré inline dans ``cli.py``).
        synthesizer_provider: Instance distincte du provider dédié à la synthèse.
            ``CascadeExecutor.__init__`` lève ``ValueError`` si identique au provider.
        budget_tracker: Kill switch budgétaire global (``BudgetTracker``) ou
            ``None`` si la section ``[budget]`` est absente de la config.
    """

    provider: BaseProvider
    synthesizer_provider: BaseProvider
    budget_tracker: BudgetTracker | None

    def create_executor(self, **kwargs) -> CascadeExecutor:
        """Construit un ``CascadeExecutor`` pré-câblé avec ce contexte.

        Transmet ``provider``, ``synthesizer_provider`` et ``budget_tracker``.
        Les kwargs supplémentaires (``prompt_loader``, ``rag_bridge``,
        ``cicd_hook``) sont transmis directement au constructeur.

        Returns:
            CascadeExecutor prêt à l'emploi.

        Raises:
            ValueError: Si ``synthesizer_provider is provider`` (refusé par
                ``CascadeExecutor.__init__``).
        """
        from .cascade_executor import CascadeExecutor

        return CascadeExecutor(
            provider=self.provider,
            synthesizer_provider=self.synthesizer_provider,
            budget_tracker=self.budget_tracker,
            **kwargs,
        )


def build_execution_context(
    config: GoalConfig,
    *,
    synthesizer_model: str | None = None,
) -> ExecutionContext:
    """Construit le triplet (provider, synthétiseur, budget) depuis une ``GoalConfig``.

    Reproduit fidèlement le bloc inline de ``run()``/``resume()``/``cascade_run()`` :

    - ``RoleMappedProvider`` avec un provider par rôle distinct (garantit
      ``require_diversity``).
    - Synthétiseur via ``_build_provider(resolved_synthesizer, ...)`` : instance
      distincte du provider de rôles (sinon ``CascadeExecutor`` lève ``ValueError``).
    - ``BudgetTracker`` avec ``daily_total_path = RUNS_DIR.parent / "budget_daily.json"``
      (standard identique à ``run()`` et ``resume()``).

    Ne gère **PAS** :
        - La branche fallback ``MockProvider`` (CLI-specific, dépend de ``--provider``
          et de la présence d'une config TOML).
        - Le ``rag_bridge`` (décision du caller, ajouté au ``CascadeExecutor``).
        - La validation Kimi ``--synthesizer-model obligatoire`` (CLI-specific,
          ``typer.BadParameter``).

    Raises:
        ValueError: Si des rôles G.O.A.L. obligatoires manquent dans la config,
            ou si la construction d'un provider échoue.
    """
    # ⚠️ Lazy import — voir docstring du module pour la justification du cycle.
    from ..cli import _build_provider

    # ── Validation G.O.A.L. : les 4 rôles explicites ────────────────────
    # On vérifie ``role_mapping`` (brut, saisi par l'utilisateur), PAS
    # ``resolved_role_mapping`` (auto-complété avec mock par la config).
    # Cela détecte les configurations où l'utilisateur a oublié un rôle et
    # obtiendrait silencieusement un mock dégradé.
    raw_role_mapping = config.providers.role_mapping
    missing_roles = REQUIRED_GOAL_ROLES - set(raw_role_mapping.keys())
    if missing_roles:
        raise ValueError(
            f"Rôles G.O.A.L. manquants dans la config : "
            f"{', '.join(sorted(missing_roles))}. "
            f"Configurez [providers.role_mapping] dans goal.toml."
        )

    # ── Construction des providers avec messages d'erreur contextuels ────
    # Utilise ``resolved_role_mapping`` (auto-complété) pour la construction
    # effective — garantit que tous les rôles ont un provider fonctionnel.
    resolved_mapping = config.providers.resolved_role_mapping
    provider_names = set(resolved_mapping.values())
    providers_by_name: dict[str, BaseProvider] = {}
    for provider_name in provider_names:
        try:
            providers_by_name[provider_name] = _build_provider(provider_name, config=config)
        except Exception as e:
            raise ValueError(f"Échec de construction du provider '{provider_name}' : {e}") from e

    provider = RoleMappedProvider(
        providers_by_name=providers_by_name,
        role_mapping=resolved_mapping,
    )

    try:
        synthesizer_provider = _build_provider(
            config.providers.resolved_synthesizer,
            synthesizer_model=synthesizer_model,
            config=config,
        )
    except Exception as e:
        raise ValueError(
            f"Échec de construction du provider synthétiseur "
            f"'{config.providers.resolved_synthesizer}' : {e}"
        ) from e

    budget_tracker = BudgetTracker(
        config=config.budget,
        daily_total_path=RUNS_DIR.parent / "budget_daily.json",
    )

    return ExecutionContext(
        provider=provider,
        synthesizer_provider=synthesizer_provider,
        budget_tracker=budget_tracker,
    )
