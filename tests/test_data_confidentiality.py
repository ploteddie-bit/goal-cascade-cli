"""Tests de confidentialité E1-E4.

E1 : pas de secrets dans les logs.
E2 : traces de run isolées (permissions 0o700).
E3 : cache sémantique local à l'utilisateur avec permissions restreintes.
E4 : .gitignore exclut les traces.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from goal_cascade.audit_journal import AuditJournal, redact_sensitive
from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.state_manager import ensure_private_dir, get_run_dir


# ── E1 : pas de secrets dans les logs ──────────────────────────────


def test_redact_sensitive_masks_common_secrets() -> None:
    """redact_sensitive masque les tokens, clés API et headers Bearer."""
    sample = (
        "Authorization: Bearer sk-abc123def456\n"
        "api_key='sk-live-51ABCDEFGHIJKLMNOPQRSTUVWXYZ'\n"
        "password=motdepasse123\n"
        "OPENAI_API_KEY=sk-xxxx\n"
    )
    redacted = redact_sensitive(sample)

    assert "sk-abc123def456" not in redacted
    assert "sk-live-51ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in redacted
    assert "motdepasse123" not in redacted
    assert "sk-xxxx" not in redacted
    assert "[MASQUÉ]" in redacted


def test_audit_journal_record_error_redacts_traceback() -> None:
    """record_error applique redact_sensitive au message et au traceback."""
    secret = "sk-secret-token-12345"
    journal = AuditJournal(run_id="run-001")

    try:
        raise ValueError(f"Provider failed with {secret}")
    except ValueError as exc:
        journal.record_error(exc)

    events = journal.events_path.read_text(encoding="utf-8").splitlines()
    last_event = events[-1]
    assert secret not in last_event


def test_semantic_cache_error_logs_do_not_leak_query() -> None:
    """Les erreurs de lookup du cache sémantique ne loguent pas la requête brute."""
    from goal_cascade.orchestrator.semantic_cache import SemanticCache

    secret_query = "Ma clé API est sk-cache-secret-999"
    mock_client = MagicMock()
    mock_client.embed.side_effect = RuntimeError(
        f"Connection failed for {secret_query}"
    )

    cache = SemanticCache(
        db_path=Path("/tmp/should_not_exist_for_test_semantic_cache.db"),
        embedding_client=mock_client,
    )

    with patch("goal_cascade.orchestrator.semantic_cache.logger.warning") as mock_log:
        result = cache.lookup(secret_query)

    assert result is None
    assert mock_log.called
    logged = mock_log.call_args.args[1] if len(mock_log.call_args.args) > 1 else ""
    assert "sk-cache-secret-999" not in logged


# ── E2 : permissions des répertoires de run ────────────────────────


def test_get_run_dir_creates_private_directory(tmp_path: Path) -> None:
    """Le répertoire d'un run est créé avec les permissions 0o700."""
    custom_goal = tmp_path / ".goal"
    with patch.object(state_manager, "RUNS_DIR", custom_goal / "runs"):
        run_dir = get_run_dir("run-test-e2")

    assert run_dir.exists()
    # On vérifie le mode en ignorant le sticky bit éventuel.
    assert (run_dir.stat().st_mode & 0o777) == 0o700


def test_ensure_private_dir_sets_mode(tmp_path: Path) -> None:
    """ensure_private_dir applique le mode demandé."""
    target = tmp_path / "private"
    ensure_private_dir(target, mode=0o700)
    assert (target.stat().st_mode & 0o777) == 0o700


def test_runs_dir_itself_is_0o700(tmp_path: Path) -> None:
    """RUNS_DIR lui-même a les permissions 0o700 après init du module.

    Régression : avant ce fix, RUNS_DIR pouvait rester en 0o755 si le umask
    par défaut du système était permissif, ce qui exposait les enfants en
    lecture aux autres utilisateurs.
    """
    custom_runs = tmp_path / "fresh-goal" / "runs"
    with patch.object(state_manager, "RUNS_DIR", custom_runs):
        # Simule le premier import en appelant directement l'init.
        state_manager._initialize_runs_dir()

    assert custom_runs.exists()
    assert (custom_runs.stat().st_mode & 0o777) == 0o700


# ── E3 : cache sémantique local et restreint ───────────────────────


def test_semantic_cache_path_is_user_local(tmp_path: Path) -> None:
    """La DB de cache sémantique est sous le home de l'utilisateur."""
    from goal_cascade.orchestrator.semantic_cache import CACHE_DB_PATH

    assert CACHE_DB_PATH.is_relative_to(Path.home())
    assert CACHE_DB_PATH.parent.name == ".goal"
    assert CACHE_DB_PATH.name == "semantic_cache.db"


def test_semantic_cache_creates_private_db(tmp_path: Path) -> None:
    """Le répertoire .goal et la DB SQLite ont des permissions restreintes."""
    from goal_cascade.orchestrator.semantic_cache import (
        CACHE_DB_MODE,
        SemanticCache,
    )

    db_path = tmp_path / ".goal" / "semantic_cache.db"
    cache = SemanticCache(db_path=db_path, embedding_client=MagicMock())

    assert db_path.exists()
    assert (db_path.parent.stat().st_mode & 0o777) == 0o700
    assert (db_path.stat().st_mode & 0o777) == CACHE_DB_MODE


# ── E4 : .gitignore exclut les traces ──────────────────────────────


def test_gitignore_excludes_run_traces() -> None:
    """.gitignore ignore les runs, le cache sémantique, les checkpoints et les env."""
    project_root = Path(__file__).parent.parent
    gitignore = project_root / ".gitignore"
    assert gitignore.exists()

    content = gitignore.read_text(encoding="utf-8")
    required = {
        ".goal/runs/",
        ".goal/semantic_cache.db",
        ".goal/checkpoints.db",
        ".goal/budget_daily.json",
        ".env",
    }
    for pattern in required:
        assert pattern in content, f"{pattern} manquant dans .gitignore"
