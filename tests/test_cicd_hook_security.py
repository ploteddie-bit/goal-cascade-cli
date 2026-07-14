"""Tests de sécurité A1-A6 pour CICDHook et InterfaceChecker.

A1 : timeout borné (≤30 s) dans l'exécution des vérificateurs.
A2 : pas d'interpolation du contenu utilisateur dans une commande shell.
A3 : pas de ``shell=True`` ; subprocess isolé avec une liste d'arguments.
A4 : ``FileNotFoundError`` et ``TimeoutExpired`` attrapés et logués.
A5 : ``InterfaceChecker.check()`` exécute d'abord la phase déterministe.
A6 : aucun appel à ``SemanticCache.lookup()`` dans le chemin d'exécution.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from goal_cascade.multicascade.interface_checker import InterfaceChecker
from goal_cascade.orchestrator.cicd_hook import CICDHook
from goal_cascade.orchestrator.semantic_cache import SemanticCache
from goal_cascade.schemas.models import (
    CascadeState,
    ImmutableArtifact,
    InterfaceContract,
)


def _make_artifact(
    content: str,
    artifact_type: str = "code",
) -> ImmutableArtifact:
    return ImmutableArtifact(
        artifact_type=artifact_type,  # type: ignore[arg-type]
        content=content,
        source_iteration=1,
    )


def _make_contract() -> InterfaceContract:
    return InterfaceContract(
        contract_id="test-contract",
        producer_module="mod-a",
        consumer_module="mod-b",
        output_description="sortie test",
        input_description="entree test",
    )


# ── A1 : timeout borné ─────────────────────────────────────────────


def test_run_checker_uses_30s_timeout() -> None:
    """La commande de vérification doit être lancée avec un timeout de 30 s."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        hook.run_deterministic_checks(contract, [artifact])

    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs.get("timeout") == 30


# ── A2 : pas d'injection shell ─────────────────────────────────────


def test_no_shell_injection_via_content() -> None:
    """Un contenu malveillant ne doit pas être interprété par un shell."""
    malicious = '; rm -rf / #\nprint("survived")\n'
    artifact = _make_artifact(content=malicious)
    hook = CICDHook()
    contract = _make_contract()

    # Avec shell=True + .format(), cette charge aurait pu exécuter ``rm -rf /``.
    # Ici elle doit être traitée comme du contenu Python (syntaxiquement invalide).
    result = hook.run_deterministic_checks(contract, [artifact])

    # Le contenu n'est jamais passé à un shell ; seule la syntaxe Python est évaluée.
    assert result.passed is False
    assert any("invalid syntax" in f.get("error", "").lower() for f in result.failures)


# ── A3 : pas de shell=True ─────────────────────────────────────────


def test_subprocess_run_without_shell() -> None:
    """``subprocess.run`` doit être appelé sans ``shell=True``."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        hook.run_deterministic_checks(contract, [artifact])

    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs.get("shell") is not True


def test_command_is_argument_list() -> None:
    """La commande doit être une liste d'arguments, pas une chaîne shell."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        hook.run_deterministic_checks(contract, [artifact])

    assert mock_run.called
    args, _ = mock_run.call_args
    assert isinstance(args[0], list)
    assert args[0][0] == "python" or Path(args[0][0]).name.startswith("python")


# ── A4 : gestion des erreurs de subprocess ─────────────────────────


def test_timeout_expired_is_caught() -> None:
    """``TimeoutExpired`` doit être attrapé et transformé en échec déterministe."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=30)
        result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert "timeout" in result.failures[0]["error"].lower()


def test_file_not_found_is_caught() -> None:
    """``FileNotFoundError`` doit être attrapé et transformé en échec déterministe."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("python")
        result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert "not found" in result.failures[0]["error"].lower()


# ── A5 : vérification hybride déterministe d'abord ─────────────────


def test_interface_checker_runs_deterministic_first() -> None:
    """InterfaceChecker doit exécuter la phase déterministe avant toute phase LLM."""
    checker = InterfaceChecker()
    contract = InterfaceContract(
        contract_id="c1",
        producer_module="producer",
        consumer_module="consumer",
        output_description="JSON",
        input_description="JSON",
    )
    artifact = _make_artifact(content="{broken", artifact_type="json_schema")
    state = CascadeState(
        run_id="run-1",
        objective="test",
        artifacts=[artifact],
    )

    result = checker.check([contract], {"producer": state}, current_module_id="consumer")

    assert result.passed is False
    assert all(f.method == "deterministic" for f in result.failures)


# ── A6 : pas de cache sémantique intra-cascade ─────────────────────


def test_interface_checker_never_calls_semantic_cache() -> None:
    """Le vérificateur d'interface ne doit jamais interroger le cache sémantique."""
    checker = InterfaceChecker()
    contract = InterfaceContract(
        contract_id="c1",
        producer_module="producer",
        consumer_module="consumer",
        output_description="code",
        input_description="code",
    )
    artifact = _make_artifact(content="x = 1\n")
    state = CascadeState(
        run_id="run-1",
        objective="test",
        artifacts=[artifact],
    )

    with patch.object(SemanticCache, "lookup") as mock_lookup:
        result = checker.check([contract], {"producer": state}, current_module_id="consumer")

    assert result.passed is True
    mock_lookup.assert_not_called()
