"""Tests dédiés à `rag_bridge.py` (RagBridge, RagSyncError).

Couverture :
- Construction : chemins worker, interpréteur
- sync_run : happy path (embedded valide)
- sync_run : failure path (exit code != 0)
- sync_run : index-only fallback
- _parse_result : validation des champs obligatoire (rapport embedded)
- _parse_failure : extraction JSON depuis stderr/stdout
- _parse_failure : fallback si pas de JSON
- Sécurité : redaction des secrets dans le message

Tous les subprocess sont mockés — pas de dépendance Ollama en test.

NOTE sur le sha256 : pour les tests de sync_run, on injecte un mock qui
calcule le sha256 AU MOMENT de l'appel (puisque sync_run re-génère la
timeline entre finalize() et _parse_result). Pour les tests purs de
_parse_result, on utilise un Path factice stable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

from goal_cascade.audit_journal import AuditJournal
from goal_cascade.orchestrator import state_manager
from goal_cascade.rag import (
    default_ollama_embed_model,
    default_ollama_embed_url,
)
from goal_cascade.rag_bridge import RagBridge, RagSyncError


# ── Helpers ──────────────────────────────────────────────────────


def _make_bridge_with_runner(
    tmp_path: Path,
    runner,
    interpreter_name: str = "fake_python",
    worker_name: str = "fake_worker.py",
) -> RagBridge:
    """Construit un RagBridge avec worker/interpréteur factices et runner injecté."""
    worker = tmp_path / worker_name
    worker.write_text("# worker", encoding="utf-8")
    interpréteur = tmp_path / interpreter_name
    interpréteur.write_text("", encoding="utf-8")
    return RagBridge(
        worker_path=worker,
        interpreter=interpréteur,
        runner=runner,
    )


def _reçu_complet(
    timeline_path: Path | None = None,
    *,
    id_document: int = 4242,
    chunks: int = 6,
    status: str = "embedded",
    run_id: str = "x",
    **overrides: Any,
) -> dict[str, Any]:
    """Construit un reçu valide (tous les champs stricts). sha256 = hash du fichier."""
    payload = {
        "status": status,
        "document_id": id_document,
        "chunks": chunks,
        "dimensions": 1024,
        "model": default_ollama_embed_model(),
        "endpoint": default_ollama_embed_url(),
        "cosine_similarity": 1.0,
        "postgres_indexed": True,
        "sha256": "x",  # placeholder
        "source": f".goal/runs/{run_id}/timeline.md",
    }
    if timeline_path is not None:
        payload["sha256"] = hashlib.sha256(
            timeline_path.read_bytes()
        ).hexdigest()
    payload.update(overrides)
    return payload


# ── _parse_result : tests purs (pas de sync_run) ──────────────────


class TestParseResult:
    """Tests directs de _parse_result, sans sync_run (timeline contrôlée)."""

    @staticmethod
    def _reçu_dans_stdout(timeline_path: Path, run_id: str = "x", **overrides) -> str:
        """Génère une ligne JSON pour stdout comme le worker le ferait."""
        payload = _reçu_complet(timeline_path, run_id=run_id, **overrides)
        return json.dumps(payload)

    def test_accepte_rechu_minimal_avec_tous_champs(self, tmp_path: Path) -> None:
        timeline = tmp_path / "timeline.md"
        timeline.write_text("contenu")
        stdout = json.dumps(_reçu_complet(timeline))
        result = RagBridge._parse_result(
            stdout,
            run_id="x",
            timeline_path=timeline,
            expected_model=default_ollama_embed_model(),
            expected_endpoint=default_ollama_embed_url(),
        )
        assert result["status"] == "embedded"
        assert result["document_id"] == 4242

    def test_accepte_derniere_ligne_si_plusieurs_json(self, tmp_path: Path) -> None:
        """Si plusieurs lignes JSON, _parse_result garde la dernière 'embedded'."""
        timeline = tmp_path / "timeline.md"
        timeline.write_text("contenu")
        ligne_bruit = json.dumps({"status": "ignored", "message": "noise"})
        ligne_bonne = json.dumps(_reçu_complet(timeline))
        stdout = ligne_bruit + "\n" + ligne_bonne
        result = RagBridge._parse_result(
            stdout,
            run_id="x",
            timeline_path=timeline,
            expected_model=default_ollama_embed_model(),
            expected_endpoint=default_ollama_embed_url(),
        )
        assert result["status"] == "embedded"

    def test_rejette_si_aucun_json(self) -> None:
        with pytest.raises(RagSyncError, match="Reçu embedded invalide"):
            RagBridge._parse_result(
                "pas de json ici",
                run_id="x",
                timeline_path=Path("/dev/null"),
                expected_model=default_ollama_embed_model(),
                expected_endpoint=default_ollama_embed_url(),
            )

    def test_rejette_si_document_id_manquant(self, tmp_path: Path) -> None:
        timeline = tmp_path / "timeline.md"
        timeline.write_text("c")
        stdout = self._reçu_dans_stdout(timeline_path=timeline)
        d = json.loads(stdout)
        del d["document_id"]
        with pytest.raises(RagSyncError, match="document_id"):
            RagBridge._parse_result(
                json.dumps(d),
                run_id="x",
                timeline_path=timeline,
                expected_model=default_ollama_embed_model(),
                expected_endpoint=default_ollama_embed_url(),
            )

    def test_rejette_si_dimensions_incorrectes(self, tmp_path: Path) -> None:
        timeline = tmp_path / "timeline.md"
        timeline.write_text("c")
        stdout = self._reçu_dans_stdout(
            timeline_path=timeline, dimensions=768  # ≠ 1024
        )
        with pytest.raises(RagSyncError, match="dimensions"):
            RagBridge._parse_result(
                stdout,
                run_id="x",
                timeline_path=timeline,
                expected_model=default_ollama_embed_model(),
                expected_endpoint=default_ollama_embed_url(),
            )

    def test_rejette_si_cosine_hors_bornes(self, tmp_path: Path) -> None:
        timeline = tmp_path / "timeline.md"
        timeline.write_text("c")
        stdout = self._reçu_dans_stdout(
            timeline_path=timeline, cosine_similarity=0.5  # trop bas
        )
        with pytest.raises(RagSyncError, match="cosine_similarity"):
            RagBridge._parse_result(
                stdout,
                run_id="x",
                timeline_path=timeline,
                expected_model=default_ollama_embed_model(),
                expected_endpoint=default_ollama_embed_url(),
            )

    def test_rejette_si_sha256_ne_correspond_pas(self, tmp_path: Path) -> None:
        """Tampering détecté : sha256 forgé ne matche pas le fichier."""
        timeline = tmp_path / "timeline.md"
        timeline.write_text("contenu authentique")
        # Payload avec sha256 forgé
        stdout = self._reçu_dans_stdout(timeline_path=timeline)
        d = json.loads(stdout)
        d["sha256"] = "f" * 64  # Forgé
        with pytest.raises(RagSyncError, match="sha256"):
            RagBridge._parse_result(
                json.dumps(d),
                run_id="x",
                timeline_path=timeline,
                expected_model=default_ollama_embed_model(),
                expected_endpoint=default_ollama_embed_url(),
            )

    def test_rejette_si_model_ne_correspond_pas(self, tmp_path: Path) -> None:
        timeline = tmp_path / "timeline.md"
        timeline.write_text("c")
        d = _reçu_complet(timeline, model="wrong-model-name")
        with pytest.raises(RagSyncError, match="model"):
            RagBridge._parse_result(
                json.dumps(d),
                run_id="x",
                timeline_path=timeline,
                expected_model=default_ollama_embed_model(),
                expected_endpoint=default_ollama_embed_url(),
            )


# ── _parse_failure : extraction JSON depuis stderr/stdout ──────────


class TestParseFailure:

    def test_extrait_json_valide(self) -> None:
        output = '{"status": "failed", "message": "ia-general off", "code": 503}'
        parsed = RagBridge._parse_failure(output)
        assert parsed["status"] == "failed"
        assert parsed["message"] == "ia-general off"
        assert parsed["code"] == 503

    def test_extrait_derniere_ligne_json(self) -> None:
        output = (
            "log inutile 1\n"
            "log inutile 2\n"
            + json.dumps({"status": "failed", "message": "real"})
        )
        parsed = RagBridge._parse_failure(output)
        assert parsed["status"] == "failed"
        assert parsed["message"] == "real"

    def test_fallback_si_pas_de_json(self) -> None:
        parsed = RagBridge._parse_failure("stderr non-JSON")
        assert parsed["status"] == "failed"
        assert "stderr non-JSON" in parsed["message"]


# ── sync_run : tests d'intégration avec subprocess mocké ──────────


@pytest.fixture
def env_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Environnement complet pour tester sync_run : RUNS_DIR, journal, run_id."""
    rep = tmp_path / "runs" / "sync-test"
    rep.mkdir(parents=True)
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("sync-test")
    journal.finalize({"status": "stopped", "objective": "x"})
    return {"journal": journal, "tmp_path": tmp_path}


class TestSyncRun:

    def test_refuse_si_interpreteur_manquant(
        self, env_sync: dict[str, Any]
    ) -> None:
        bridge = RagBridge(
            worker_path=env_sync["tmp_path"] / "w.py",
            interpreter=env_sync["tmp_path"] / "absent_python",
            runner=lambda *a, **kw: CompletedProcess([], 0, "", ""),
        )
        with pytest.raises(RagSyncError, match="Interpréteur"):
            bridge.sync_run("sync-test", journal=env_sync["journal"])

    def test_refuse_si_worker_manquant(
        self, env_sync: dict[str, Any]
    ) -> None:
        interpréteur = env_sync["tmp_path"] / "python"
        interpréteur.write_text("")
        bridge = RagBridge(
            worker_path=env_sync["tmp_path"] / "absent_worker.py",
            interpreter=interpréteur,
            runner=lambda *a, **kw: CompletedProcess([], 0, "", ""),
        )
        with pytest.raises(RagSyncError, match="Worker"):
            bridge.sync_run("sync-test", journal=env_sync["journal"])

    def test_succes_embedded_met_a_jour_rag_status(
        self, env_sync: dict[str, Any]
    ) -> None:
        """Happy path : le worker retourne un reçu valide, rag-status passe à embedded."""
        journal = env_sync["journal"]
        timeline_path = journal.timeline_path

        def runner(command, **kwargs):
            # Calcule sha256 AU MOMENT de l'appel (la timeline a été re-rendue
            # par refresh_timeline dans sync_run). run_id extrait de la commande.
            run_id = command[command.index("--run-id") + 1]
            payload = _reçu_complet(timeline_path=timeline_path, run_id=run_id)
            return CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

        bridge = _make_bridge_with_runner(env_sync["tmp_path"], runner)

        resultat = bridge.sync_run("sync-test", journal=journal)
        assert resultat["status"] == "embedded"
        assert resultat["document_id"] == 4242

        # rag-status.json doit refléter le succès
        statut = json.loads(journal.rag_status_path.read_text(encoding="utf-8"))
        assert statut["status"] == "embedded"
        assert statut["document_id"] == 4242

    def test_echec_subprocess_leve_avec_secret_masque(
        self, env_sync: dict[str, Any]
    ) -> None:
        def runner(command, **kwargs):
            return CompletedProcess(
                command, 3, stdout="",
                stderr='{"status":"failed","message":"auth failed sk-proj-abcdefghij1234567890 password=hidden"}',
            )

        bridge = _make_bridge_with_runner(env_sync["tmp_path"], runner)

        with pytest.raises(RagSyncError) as excinfo:
            bridge.sync_run("sync-test", journal=env_sync["journal"])

        msg = str(excinfo.value)
        # Aucun secret visible
        assert "sk-proj-abcdefghij" not in msg
        assert "hidden" not in msg
        assert "[MASQUÉ]" in msg
        # Le contexte user est conservé
        assert "auth failed" in msg

        # Et dans le fichier rag-status.json
        statut_json = env_sync["journal"].rag_status_path.read_text(encoding="utf-8")
        assert "sk-proj-abcdefghij" not in statut_json

    def test_index_only_fallback_change_statut_en_indexed(
        self, env_sync: dict[str, Any]
    ) -> None:
        """Si la 2e tentative (index-only) retourne un reçu valide, le statut
        final est 'indexed_pending_embedding' et non 'failed'."""
        journal = env_sync["journal"]
        timeline_path = journal.timeline_path

        def runner(command, **kwargs):
            # Calculer sha256 au moment de l'appel (timeline peut avoir été
            # refresh entre la création du journal et l'appel worker).
            timeline_path_cmd = Path(command[command.index("--timeline") + 1])
            sha256_actuel = hashlib.sha256(timeline_path_cmd.read_bytes()).hexdigest()
            run_id_cmd = command[command.index("--run-id") + 1]
            payload_index_only = {
                "status": "indexed_pending_embedding",
                "document_id": 9999,
                "postgres_indexed": True,
                "sha256": sha256_actuel,
                "source": f".goal/runs/{run_id_cmd}/timeline.md",
            }
            if "--index-only" in command:
                return CompletedProcess(
                    command, 0, stdout=json.dumps(payload_index_only), stderr=""
                )
            return CompletedProcess(
                command, 1, stdout="",
                stderr=json.dumps({"status": "failed", "message": "ia-general off"}),
            )

        bridge = _make_bridge_with_runner(env_sync["tmp_path"], runner)

        with pytest.raises(RagSyncError, match="ia-general off"):
            bridge.sync_run("sync-test", journal=journal)

        statut = json.loads(journal.rag_status_path.read_text(encoding="utf-8"))
        assert statut["status"] == "indexed_pending_embedding"
        assert statut["document_id"] == 9999

