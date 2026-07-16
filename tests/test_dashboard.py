"""Tests HTTP pour les endpoints du dashboard (TestClient FastAPI).

Couvre O1 du plan Phase 5 dashboard : tests d'intégration via TestClient.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from goal_cascade.dashboard import app
from goal_cascade.audit_journal import AuditJournal


@pytest.fixture
def client_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient FastAPI + RUNS_DIR redirigé vers tmp_path."""
    from goal_cascade.orchestrator import state_manager
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)
    return TestClient(app)


def test_root_sert_le_html(client_runs: TestClient) -> None:
    """GET / retourne le HTML du dashboard."""
    r = client_runs.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert b"G.O.A.L" in r.content


def test_api_cascades_liste_vide_si_aucune(client_runs: TestClient) -> None:
    """GET /api/cascades retourne une liste vide quand aucun run."""
    r = client_runs.get("/api/cascades")
    assert r.status_code == 200
    data = r.json()
    assert data["cascades"] == []
    assert data["total"] == 0


def test_api_cascades_run_id_manquant_retourne_404(client_runs: TestClient) -> None:
    """GET /api/cascades/{run_id} inexistant (hex valide) → 404."""
    r = client_runs.get("/api/cascades/aabbccdd")  # hex 8 chars valide
    assert r.status_code == 404


def test_api_cascades_run_id_path_traversal_bloque(client_runs: TestClient) -> None:
    """GET avec run_id malformé (path traversal URL-encoded) → rejeté (400 ou 404).

    Le path traversal est bloqué soit par FastAPI (URL matching → 404), soit
    par notre regex (run_id non-hex → 400). L'important est qu'on n'accède
    JAMAIS au filesystem avec un chemin malveillant.
    """
    r = client_runs.get("/api/cascades/..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)
    assert r.status_code != 200  # jamais OK


def test_api_cascades_prompts_retourne_dict(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """GET /api/cascades/{id}/prompts retourne 5 rôles (variant A)."""
    hex_id = "aabbccdd"
    (tmp_path / hex_id / ".checkpoints").mkdir(parents=True)
    AuditJournal(hex_id).finalize({"status": "stopped"})
    r = client_runs.get(f"/api/cascades/{hex_id}/prompts")
    assert r.status_code == 200
    data = r.json()
    for role in ["iteration_1", "iteration_2", "iteration_3", "iteration_4", "synthesis"]:
        assert role in data, f"rôle {role} manquant"


def test_api_cascades_put_prompt_taille_max_retourne_413(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """PUT avec contenu > 256 KB → 413 (Payload Too Large)."""
    hex_id = "aabbccdd"
    (tmp_path / hex_id / ".checkpoints").mkdir(parents=True)
    AuditJournal(hex_id).finalize({"status": "stopped"})
    r = client_runs.put(
        f"/api/cascades/{hex_id}/prompts/iteration_1",
        json={"contenu": "x" * 300_000},  # > 256 KB
    )
    assert r.status_code == 413


# ── O6 — Endpoint /api/sante (Tâche 2) ───────────────────────────


def test_api_sante_retourne_compteurs_et_malformes(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """GET /api/sante expose compteurs + liste runs malformés."""
    etat_min = {
        "run_id": "placeholder", "objective": "x", "variant": "A",
        "current_iteration": 0, "max_iterations": 5, "history": [],
        "last_synthesis": None, "artifacts": [], "final_verdict": None,
        "status": "stopped", "last_error": None, "accumulated_cost": 0.0,
        "last_raw_output": "", "frozen_spec": None, "interface_contracts": [],
    }

    # Run valide
    hex_ok = "aabbccdd"
    (tmp_path / hex_ok).mkdir()
    (tmp_path / hex_ok / "state.json").write_text(
        json.dumps(dict(etat_min, run_id=hex_ok))
    )

    # Run "malforme" : max_iterations=100 viole le=5 → ValidationError
    hex_bad = "11223344"
    (tmp_path / hex_bad).mkdir()
    (tmp_path / hex_bad / "state.json").write_text(
        json.dumps(dict(etat_min, run_id=hex_bad, max_iterations=100))
    )

    r = client_runs.get("/api/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["runs_total"] == 2
    assert data["runs_chargeables"] == 1  # le run sans champ étrange
    assert data["runs_malformes"] == 1    # le run avec champ supplémentaire
    assert "malformes_detail" in data
    assert "derniere_maj" in data
    # Le run malformé est détaillé
    assert any(m["id_cascade"] == hex_bad for m in data["malformes_detail"])


# ── O2 — Pagination /api/cascades (Tâche 3) ─────────────────────


def _creer_cascades_factices(tmp_path: Path, n: int) -> list[str]:
    """Helper : crée n cascades factices (hex IDs séquentiels) + state.json."""
    ids = []
    base = 0xA0000000
    etat_min = {
        "objective": "x", "variant": "A",
        "current_iteration": 0, "max_iterations": 5, "history": [],
        "last_synthesis": None, "artifacts": [], "final_verdict": None,
        "status": "stopped", "last_error": None, "accumulated_cost": 0.0,
        "last_raw_output": "", "frozen_spec": None, "interface_contracts": [],
    }
    for i in range(n):
        hex_id = f"{base + i:08x}"
        (tmp_path / hex_id).mkdir()
        (tmp_path / hex_id / "state.json").write_text(
            json.dumps(dict(etat_min, run_id=hex_id, objective=f"Test {i}"))
        )
        ids.append(hex_id)
    return ids


def test_api_cascades_pagination_defaut(client_runs: TestClient, tmp_path: Path) -> None:
    """GET /api/cascades sans param → liste paginée (defaut: 50)."""
    _creer_cascades_factices(tmp_path, 3)
    r = client_runs.get("/api/cascades")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["cascades"]) == 3  # 3 < defaut 50
    assert data["limite"] == 50
    assert data["decalage"] == 0


def test_api_cascades_pagination_limite_explicite(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """GET /api/cascades?limite=2&decalage=0 → 2 premières."""
    _creer_cascades_factices(tmp_path, 5)
    r = client_runs.get("/api/cascades?limite=2&decalage=0")
    data = r.json()
    assert data["total"] == 5
    assert len(data["cascades"]) == 2
    assert data["limite"] == 2


def test_api_cascades_pagination_decalage(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """GET /api/cascades?decalage=3 → skip les 3 premières."""
    ids = _creer_cascades_factices(tmp_path, 5)
    r = client_runs.get("/api/cascades?limite=10&decalage=3")
    data = r.json()
    assert data["total"] == 5
    assert len(data["cascades"]) == 2  # 5 - 3 = 2 restantes


def test_api_cascades_pagination_limite_plafond_100(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """limite > 100 doit être plafonnée à 100 (anti-DoS)."""
    _creer_cascades_factices(tmp_path, 1)
    r = client_runs.get("/api/cascades?limite=500")
    data = r.json()
    assert data["limite"] == 100  # plafonné par le serveur


def test_api_cascades_pagination_limite_min_1(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """limite=0 doit être remontée à 1 (anti-division-par-zero)."""
    _creer_cascades_factices(tmp_path, 3)
    r = client_runs.get("/api/cascades?limite=0")
    data = r.json()
    assert data["limite"] >= 1


# ── O5 — Filtrage sidebar (Tâche 4) ───────────────────────────────


def test_api_cascades_filtre_statut(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """GET /api/cascades?statut=stopped ne retourne que les stopped."""
    etat_min = {
        "objective": "x", "variant": "A",
        "current_iteration": 0, "max_iterations": 5, "history": [],
        "last_synthesis": None, "artifacts": [], "final_verdict": None,
        "last_error": None, "accumulated_cost": 0.0,
        "last_raw_output": "", "frozen_spec": None, "interface_contracts": [],
    }
    (tmp_path / "aabbccdd").mkdir()
    (tmp_path / "aabbccdd" / "state.json").write_text(
        json.dumps(dict(etat_min, run_id="aabbccdd", status="stopped"))
    )
    (tmp_path / "11223344").mkdir()
    (tmp_path / "11223344" / "state.json").write_text(
        json.dumps(dict(etat_min, run_id="11223344", status="forced_stop"))
    )

    r = client_runs.get("/api/cascades?statut=stopped")
    data = r.json()
    assert data["total"] == 1
    assert data["cascades"][0]["statut"] == "stopped"


def test_api_cascades_recherche_dans_objectif(
    client_runs: TestClient, tmp_path: Path
) -> None:
    """GET /api/cascades?q=refactor filtre par substring dans objectif (case-insensitive)."""
    etat_min = {
        "variant": "A", "current_iteration": 0, "max_iterations": 5,
        "history": [], "last_synthesis": None, "artifacts": [],
        "final_verdict": None, "status": "stopped", "last_error": None,
        "accumulated_cost": 0.0, "last_raw_output": "",
        "frozen_spec": None, "interface_contracts": [],
    }
    (tmp_path / "aabbccdd").mkdir()
    (tmp_path / "aabbccdd" / "state.json").write_text(
        json.dumps(dict(etat_min, run_id="aabbccdd", objective="Refactor module auth"))
    )
    (tmp_path / "11223344").mkdir()
    (tmp_path / "11223344" / "state.json").write_text(
        json.dumps(dict(etat_min, run_id="11223344", objective="Audit performance"))
    )

    r = client_runs.get("/api/cascades?q=refactor")
    data = r.json()
    assert data["total"] == 1
    assert "refactor" in data["cascades"][0]["objectif"].lower()


# ── O4 — Hot-reload prompts mid-run (Tâche 5) ────────────────────


def test_prompt_resolver_charge_override_pour_run_specifique(
    tmp_path: Path,
) -> None:
    """L'override d'un run spécifique est utilisé en priorité."""
    from goal_cascade.orchestrator.prompt_resolver import PromptResolver

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "aabbccdd" / "prompts").mkdir(parents=True)
    (runs_dir / "aabbccdd" / "prompts" / "iteration_1.j2").write_text(
        "OVERRIDE-AABBCCDD"
    )

    resolver = PromptResolver(runs_dir=runs_dir)
    contenu = resolver.charger("iteration_1.j2", id_cascade="aabbccdd")
    assert "OVERRIDE-AABBCCDD" in contenu


def test_prompt_resolver_fallback_si_pas_d_override(
    tmp_path: Path,
) -> None:
    """Sans override, le template par défaut est utilisé."""
    from goal_cascade.orchestrator.prompt_resolver import PromptResolver

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    # Pas d'override pour ce run
    resolver = PromptResolver(runs_dir=runs_dir)
    contenu = resolver.charger("iteration_1.j2", id_cascade="aabbccdd")
    # Le template par défaut contient du texte Jinja2 (objectif)
    assert "OBJECTIF" in contenu or "objectif" in contenu.lower()


def test_prompt_resolver_securite_anti_path_traversal(
    tmp_path: Path,
) -> None:
    """Un override hors du runs_dir est rejeté (anti-../)."""
    from goal_cascade.orchestrator.prompt_resolver import PromptResolver

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    # Crée un fichier HORS du runs_dir qui tente de se faire passer
    # pour un override via un nom avec traversal
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "iteration_1.j2").write_text("INJECTED")
    (runs_dir / "aabbccdd").mkdir()

    resolver = PromptResolver(runs_dir=runs_dir)
    # Doit utiliser le défaut, pas charger "other"
    contenu = resolver.charger("iteration_1.j2", id_cascade="aabbccdd")
    assert "INJECTED" not in contenu


# ── T5.5 — Câblage end-to-end du hot-reload (E2E via CascadeExecutor) ─


def test_cascade_executor_applique_override_prompt_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le builder de prompt utilise l'override si présent.

    Test E2E : on crée un run avec un override .j2, on appelle
    ``CascadeExecutor._build_prompt``, on vérifie que l'override
    est bien rendu (pas le template par défaut).
    """
    from goal_cascade.orchestrator import state_manager
    from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
    from goal_cascade.providers.mock import MockProvider
    from goal_cascade.schemas.models import IterationRole, Variant

    # Crée un run avec un override pour iteration_1
    run_id = "aabbccdd"
    (tmp_path / run_id / "prompts").mkdir(parents=True)
    (tmp_path / run_id / "prompts" / "iteration_1.j2").write_text(
        "OVERRIDE-CONTENTU-{{ objective }}"
    )

    # Mock state_manager.RUNS_DIR + crée un état avec objective
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)
    state = type("S", (), {
        "run_id": run_id,
        "objective": "MonObjectif",
        "variant": Variant.A,
        "history": [],
        "last_synthesis": None,
        "artifacts": [],
    })()

    executor = CascadeExecutor(
        provider=MockProvider(),
        synthesizer_provider=MockProvider(),
    )
    prompt = executor._build_prompt(state, IterationRole.PRODUCER)
    assert "OVERRIDE-CONTENTU-MonObjectif" in prompt
    # Le template par défaut (qui contient OBJECTIF) ne doit PAS être utilisé
    assert "OBJECTIF" not in prompt or "MonObjectif" in prompt


# ── O5 UI — Tests frontend (champ recherche + dropdown statut) ─────


def test_ui_index_a_champ_recherche_et_dropdown_statut() -> None:
    """Le HTML expose un champ de recherche et un dropdown de statut.

    Couvre O5 : filtrage sidebar doit avoir une UI, pas juste l'API.
    """
    from pathlib import Path as _P

    index_path = _P("/tmp/goal-cascade-review/src/goal_cascade/dashboard/templates/index.html")
    html = index_path.read_text(encoding="utf-8")
    # Champ de recherche
    assert 'id="champ-recherche"' in html, "Champ de recherche manquant"
    assert 'placeholder="Rechercher…"' in html or "Rechercher" in html
    # Dropdown statut
    assert 'id="filtre-statut"' in html, "Dropdown statut manquant"
    # Options de statut (au moins 'tous' + un spécifique)
    assert "<option" in html
    assert "stopped" in html or "Stopped" in html


def test_ui_appjs_appelle_api_avec_query_params() -> None:
    """Le JS envoie les query params statut + q à l'API via URLSearchParams."""
    from pathlib import Path as _P

    js_path = _P("/tmp/goal-cascade-review/src/goal_cascade/dashboard/static/app.js")
    js = js_path.read_text(encoding="utf-8")
    # Le code JS utilise URLSearchParams pour construire les query params
    assert "URLSearchParams" in js
    assert "params.set" in js
    # Les deux filtres (statut + q) sont configurés
    assert "'statut'" in js or '"statut"' in js
    assert "'q'" in js or '"q"' in js
    # L'event listener est branché sur les changements
    assert "addEventListener" in js
    assert ("'input'" in js or '"input"' in js) and ("'change'" in js or '"change"' in js)


# ── D3 — Auth Bearer (E2E) ───────────────────────────────────────


def test_dashboard_sans_token_env_accepte_toutes_requetes(
    client_runs: TestClient,
) -> None:
    """Mode dev : sans GOAL_DASHBOARD_TOKEN, auth désactivée (rétrocompat).

    Vérifie que le mode dev par défaut reste ouvert (pas de 401 surprise).
    """
    # Le TestClient par défaut n'a pas GOAL_DASHBOARD_TOKEN
    r = client_runs.get("/api/cascades")
    assert r.status_code == 200


def test_dashboard_avec_token_env_exige_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mode prod : avec GOAL_DASHBOARD_TOKEN, TOUTES les routes exigent Bearer."""
    from goal_cascade.orchestrator import state_manager
    from fastapi.testclient import TestClient
    from goal_cascade.dashboard import app

    # Configure l'env (mode prod)
    monkeypatch.setenv("GOAL_DASHBOARD_TOKEN", "secret-test-12345")
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)

    client = TestClient(app)

    # Sans header → 401
    r = client.get("/api/cascades")
    assert r.status_code == 401

    # Avec mauvais token → 403
    r = client.get("/api/cascades", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403

    # Avec bon token → 200
    r = client.get(
        "/api/cascades", headers={"Authorization": "Bearer secret-test-12345"}
    )
    assert r.status_code == 200

    # Pareil pour le PUT (route sensible originelle)
    r = client.put(
        "/api/cascades/aabbccdd/prompts/iteration_1",
        json={"contenu": "x"},
    )
    assert r.status_code == 401  # sans auth
    r = client.put(
        "/api/cascades/aabbccdd/prompts/iteration_1",
        json={"contenu": "x"},
        headers={"Authorization": "Bearer secret-test-12345"},
    )
    # PUT a quand même 400/404 (run absent) mais PAS 401/403
    assert r.status_code in (200, 400, 404, 413, 500)
    assert r.status_code != 401
    assert r.status_code != 403


# ── Éditeur de fichiers (run files) ──────────────────────────────


@pytest.fixture
def run_avec_fichiers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Crée un run avec plusieurs fichiers persistés (events, prompts, iterations)."""
    from goal_cascade.orchestrator import state_manager
    from goal_cascade.audit_journal import AuditJournal

    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)
    run_id = "abcdef12"
    rep = tmp_path / run_id
    rep.mkdir()
    journal = AuditJournal(run_id)
    journal.finalize({"status": "stopped"})
    # Créer des fichiers typiques
    (rep / "events.jsonl").write_text(
        '{"sequence":1,"event":"run_started","timestamp_utc":"2026-07-15T10:00:00","run_id":"abcdef12"}\n'
        '{"sequence":2,"event":"run_finished","timestamp_utc":"2026-07-15T10:00:01","run_id":"abcdef12"}\n'
    )
    (rep / "state.json").write_text('{"run_id":"abcdef12","objective":"Test editor","status":"stopped"}')
    (rep / "iteration_1.txt").write_text("Contenu de l'itération 1 du producer.")
    (rep / "synthesis_1.json").write_text('{"objective":"Test","key_decisions":["d1"]}')
    (rep / "prompt_1_producer.txt").write_text("Tu es un redacteur. Fais le draft.")
    return run_id


def test_editeur_lit_fichier_iteration(client_runs, run_avec_fichiers):
    """L'éditeur peut lire le contenu d'un fichier de run (iteration_1.txt)."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/iterations/1")
    assert r.status_code == 200
    data = r.json()
    assert data["contenu"] == "Contenu de l'itération 1 du producer."
    assert data["type_mime"] == "text/plain"


def test_editeur_lit_synthese_json(client_runs, run_avec_fichiers):
    """L'éditeur parse les JSON (synthesis) et retourne le dict."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/syntheses/1")
    assert r.status_code == 200
    data = r.json()
    assert data["contenu"] == {"objective": "Test", "key_decisions": ["d1"]}
    assert data["type_mime"] == "application/json"


def test_editeur_lit_prompt(client_runs, run_avec_fichiers):
    """L'éditeur lit les prompts (prompt_1_producer.txt)."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/prompts/producer/1")
    assert r.status_code == 200
    assert r.json()["contenu"] == "Tu es un redacteur. Fais le draft."


def test_editeur_lit_state_json(client_runs, run_avec_fichiers):
    """L'éditeur lit state.json (état complet de la cascade)."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/state")
    assert r.status_code == 200
    assert r.json()["contenu"] == {
        "run_id": "abcdef12",
        "objective": "Test editor",
        "status": "stopped",
    }


def test_editeur_lit_events_jsonl(client_runs, run_avec_fichiers):
    """L'éditeur lit events.jsonl (le journal temps réel)."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/evenements")
    assert r.status_code == 200
    data = r.json()
    assert data["type_mime"] == "application/x-ndjson"
    assert "run_started" in data["contenu"]


def test_editeur_type_inconnu_renvoie_400(client_runs, run_avec_fichiers):
    """Un type de fichier non supporté → 400."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/inconnu/1")
    assert r.status_code == 400


def test_editeur_iteration_hors_range_renvoie_404(client_runs, run_avec_fichiers):
    """Un numéro d'itération hors range (0 ou > 5) → 404."""
    r = client_runs.get(f"/api/cascades/{run_avec_fichiers}/fichier/iterations/99")
    assert r.status_code == 404


def test_editeur_path_traversal_bloque(client_runs):
    """L'éditeur refuse les chemins avec .. (path traversal)."""
    # Test : role avec .. ne doit pas passer la regex de role
    r = client_runs.get("/api/cascades/abcdef12/fichier/prompts/..%2F..%2Fetc%2Fpasswd/1")
    assert r.status_code in (400, 404)


def test_editeur_run_inconnu_renvoie_404(client_runs):
    """Un run_id inexistant → 404."""
    r = client_runs.get("/api/cascades/abcdef12/fichier/iterations/1")
    # Le run n'existe pas → 404 (le regex de run_id passe mais pas le fichier)
    assert r.status_code == 404
