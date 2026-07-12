"""Tests pour le hook CI/CD (CICDHook / DeterministicCheckResult)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from goal_cascade.orchestrator.cicd_hook import CICDHook, DeterministicCheckResult
from goal_cascade.schemas.models import ImmutableArtifact, InterfaceContract


# ── Helpers ─────────────────────────────────────────────────────────


def _make_artifact(
    path: str,
    artifact_type: str = "code",
    content: str = "",
) -> SimpleNamespace:
    """Crée un artefact factice avec les attributs attendus par CICDHook.

    ImmutableArtifact (Pydantic) ne possède pas de champ ``path`` ;
    on utilise SimpleNamespace pour fournir l'interface attendue par le hook.
    """
    return SimpleNamespace(
        path=path,
        artifact_type=artifact_type,
        content=content,
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


def test_run_checks_passes_valid_python(tmp_path) -> None:
    """Un fichier Python syntaxiquement valide doit passer les checks."""
    valid_py = tmp_path / "valid.py"
    valid_py.write_text("x = 1\n", encoding="utf-8")

    artifact = _make_artifact(path=str(valid_py), artifact_type="code")
    hook = CICDHook()
    contract = _make_contract()

    result = hook.run_deterministic_checks(contract, [artifact])

    assert isinstance(result, DeterministicCheckResult)
    assert result.passed is True
    assert result.failures == []


# ── Test 2 : JSON invalide → échoue ───────────────────────────────


def test_run_checks_fails_invalid_json(tmp_path) -> None:
    """Un fichier JSON malformé doit faire échouer les checks."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{pas du json valide", encoding="utf-8")

    artifact = _make_artifact(path=str(bad_json), artifact_type="json_schema")
    hook = CICDHook()
    contract = _make_contract()

    result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0]["artifact"] == str(bad_json)


# ── Test 3 : Timeout → rapporté correctement ──────────────────────


def test_run_checks_timeout() -> None:
    """Un TimeoutExpired de subprocess doit produire un échec contenant 'timeout'."""
    artifact = _make_artifact(path="/tmp/fake.py", artifact_type="code")
    hook = CICDHook()
    contract = _make_contract()

    with patch("goal_cascade.orchestrator.cicd_hook.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="python -m py_compile /tmp/fake.py", timeout=30,
        )
        result = hook.run_deterministic_checks(contract, [artifact])

    assert result.passed is False
    assert len(result.failures) == 1
    assert "timeout" in result.failures[0]["error"].lower()
