"""Tests pour le hook CI/CD (CICDHook / DeterministicCheckResult)."""

from __future__ import annotations

from unittest.mock import patch

from goal_cascade.orchestrator.cicd_hook import CICDHook, DeterministicCheckResult
from goal_cascade.schemas.models import ImmutableArtifact, InterfaceContract

# ── Helpers ─────────────────────────────────────────────────────────


def _make_artifact(
    content: str,
    artifact_type: str = "code",
) -> ImmutableArtifact:
    """Crée un artefact minimal avec le contenu fourni."""
    return ImmutableArtifact(
        artifact_type=artifact_type,  # type: ignore[arg-type]
        content=content,
        source_iteration=1,
    )


def _make_contract() -> InterfaceContract:
    """Crée un InterfaceContract minimal pour les tests."""
    return InterfaceContract(
        contract_id="test-contract",
        producer_module="mod-a",
        consumer_module="mod-b",
        output_description="sortie test",
        input_description="entree test",
    )


# ── Test 1 : Python valide → passe ────────────────────────────────


def test_run_checks_passes_valid_python() -> None:
    """Un contenu Python syntaxiquement valide doit passer les checks."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    result = hook.run_deterministic_checks(contract, [artifact])

    assert isinstance(result, DeterministicCheckResult)
    assert result.passed is True
    assert result.failures == []


# ── Test 2 : JSON invalide → échoue ───────────────────────────────


def test_run_checks_fails_invalid_json() -> None:
    """Un contenu JSON malformé doit faire échouer les checks."""
    artifact = _make_artifact(
        content="{pas du json valide",
        artifact_type="json_schema",
    )
    hook = CICDHook()
    contract = _make_contract()

    result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0]["artifact_type"] == "json_schema"


# ── Test 3 : Timeout → rapporté correctement ──────────────────────


def test_run_checks_timeout() -> None:
    """Un TimeoutExpired de subprocess doit produire un échec contenant 'timeout'."""
    artifact = _make_artifact(content="x = 1\n")
    hook = CICDHook()
    contract = _make_contract()

    with patch("goal_cascade.orchestrator.cicd_hook._run_checker") as mock_run:
        mock_run.return_value = {
            "artifact_type": "code",
            "checker": "py_compile",
            "error": "timeout after 30s",
        }
        result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert "timeout" in result.failures[0]["error"].lower()


# ── Test 4 : Checker personnalisé ─────────────────────────────────


def test_custom_checker_overrides_default() -> None:
    """Un checker personnalisé doit pouvoir remplacer un checker natif."""
    calls: list[ImmutableArtifact] = []

    def custom_checker(artifact: ImmutableArtifact) -> dict[str, str] | None:
        calls.append(artifact)
        return None

    hook = CICDHook(custom_checkers={"code": custom_checker})
    artifact = _make_artifact(content="x = 1\n")
    contract = _make_contract()

    result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is True
    assert len(calls) == 1
    assert calls[0] is artifact


def test_custom_checker_failure_reported() -> None:
    """Un échec dans un checker personnalisé doit être rapporté."""

    def failing_checker(artifact: ImmutableArtifact) -> dict[str, str]:
        return {
            "artifact_type": artifact.artifact_type,
            "checker": "custom",
            "error": "custom failure",
        }

    hook = CICDHook(custom_checkers={"json_schema": failing_checker})
    artifact = _make_artifact(content='{"ok": true}', artifact_type="json_schema")
    contract = _make_contract()

    result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0]["error"] == "custom failure"
