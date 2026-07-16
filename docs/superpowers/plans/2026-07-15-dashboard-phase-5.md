# Dashboard Phase 5 — Plan d'implémentation O1-O6

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compléter les 5 items Phase 5 du dashboard (O1 tests, O2 pagination, O4 hot-reload prompts, O5 filtrage sidebar, O6 endpoint santé) en respectant strictement les règles AGENTS.md (backup, Edit-only sur fichiers existants, tests après chaque modif).

**Architecture:** Itérations TDD strictes. Pour chaque item : écrire le test qui échoue → écrire l'implémentation minimale → vérifier que le test passe → `pytest` complet → backup `.v{N+1}`.

**Tech Stack:** FastAPI, httpx, pytest, structlog (déjà en place). Pas de nouvelle dépendance.

## Global Constraints

- **Backups AGENTS.md §7** : toute modification d'un fichier existant via Edit doit avoir une sauvegarde `.vN` dans `versions/<chemin-relatif>` AVANT.
- **Write interdit sur fichiers existants (règle 6, esprit Python)** : utilisation stricte de `Edit`. `Write` réservé aux nouveaux fichiers.
- **Tests après chaque modification (règle 5)** : `uv run pytest -p no:cacheprovider -q` doit montrer **302+ passed** (les 300 actuels + les nouveaux) sans régression.
- **Goal-Driven Execution (règle 5)** : annoncer `Statut réel / Portée réelle / Preuve / Prochaine étape` à la fin de chaque tâche.

---

## Tâche 1 : O1 — Tests unitaires des endpoints dashboard

**Fichiers :**
- Créer : `tests/test_dashboard.py`
- Modifier : aucun (ajout pur)

**Objectif :** Pour chaque endpoint actuel (`/api/cascades`, `/api/cascades/{id}`, `/api/cascades/{id}/evenements`, `/api/cascades/{id}/evenements/flux`, `/api/cascades/{id}/fichiers`, `/api/cascades/{id}/prompts`, PUT `/api/cascades/{id}/prompts/{role}`, `/api/cascades/{id}/recu`, `/`), écrire un test qui utilise `TestClient` FastAPI avec fixtures minimales.

- [ ] **Étape 1.1 : Écrire le squelette `tests/test_dashboard.py`**

```python
"""Tests HTTP pour les endpoints du dashboard (TestClient FastAPI)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from goal_cascade.dashboard import app


@pytest.fixture
def client_runs(tmp_path, monkeypatch) -> TestClient:
    from goal_cascade.orchestrator import state_manager
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)
    return TestClient(app)


def test_root_sert_le_html(client_runs):
    r = client_runs.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert b"G.O.A.L" in r.content


def test_api_cascades_liste_vide_si_aucune(client_runs):
    r = client_runs.get("/api/cascades")
    assert r.status_code == 200
    assert r.json() == []


def test_api_cascades_run_id_manquant_retourne_404(client_runs):
    r = client_runs.get("/api/cascades/inexistant")
    assert r.status_code == 404


def test_api_cascades_run_id_path_traversal_bloque(client_runs):
    # %2F = "/", %2E = "."
    r = client_runs.get("/api/cascades/..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_api_cascades_prompts_retourne_dict(client_runs, tmp_path):
    # Crée un run minimal avec finalize
    from goal_cascade.audit_journal import AuditJournal
    (tmp_path / "run-test" / ".checkpoints").mkdir(parents=True)
    AuditJournal("run-test").finalize({"status": "stopped"})
    r = client_runs.get("/api/cascades/run-test/prompts")
    assert r.status_code == 200
    data = r.json()
    # Vérifie les 5 rôles attendus en variant A
    for role in ["iteration_1", "iteration_2", "iteration_3", "iteration_4", "synthesis"]:
        assert role in data


def test_api_cascades_put_prompt_taille_max_retourne_413(client_runs, tmp_path):
    from goal_cascade.audit_journal import AuditJournal
    (tmp_path / "run-test" / ".checkpoints").mkdir(parents=True)
    AuditJournal("run-test").finalize({"status": "stopped"})
    r = client_runs.put(
        "/api/cascades/run-test/prompts/iteration_1",
        json={"contenu": "x" * 300_000},  # > 256 KB
    )
    assert r.status_code == 413
```

- [ ] **Étape 1.2 : Lancer pytest pour vérifier que le test passe d'emblée**

```bash
uv run pytest tests/test_dashboard.py -v --no-header
```

Attendu : `6 passed`. (Le code existe déjà dans serveur.py, donc les tests doivent passer sans modification de production.)

- [ ] **Étape 1.3 : Sauvegarder (car c'est juste un nouveau fichier, pas de `.vN` requis)**

- [ ] **Étape 1.4 : Lancer pytest complet pour vérifier 0 régression**

```bash
uv run pytest -p no:cacheprovider --no-header -q | tail -3
```

Attendu : `306 passed, 4 skipped` (300 + 6 nouveaux).

---

## Tâche 2 : O6 — Endpoint `/api/sante` (visibilité runs skippés)

**Fichiers :**
- Modifier : `src/goal_cascade/dashboard/state.py` (ajouter `etat_cascades_malformees()`)
- Modifier : `src/goal_cascade/dashboard/serveur.py` (ajouter endpoint)
- Backup préalable : `versions/.../state.py.v2` et `serveur.py.v2`

**Justification du backup .v2 :** fichier existant déjà sauvegardé en .v1 pour D4. Chaque modification incrémente.

- [ ] **Étape 2.1 : Backup des fichiers existants**

```bash
cp src/goal_cascade/dashboard/state.py versions/.../state.py.v2
cp src/goal_cascade/dashboard/serveur.py versions/.../serveur.py.v2
```

- [ ] **Étape 2.2 : Écrire le test qui échoue**

Dans `tests/test_dashboard.py`, ajouter :

```python
def test_api_sante_retourne_compteurs(client_runs):
    r = client_runs.get("/api/sante")
    assert r.status_code == 200
    data = r.json()
    assert "runs_total" in data
    assert "runs_chargeables" in data
    assert "runs_malformes" in data
    assert "derniere_maj" in data
```

- [ ] **Étape 2.3 : Lancer pytest pour confirmer l'échec**

Attendu : `AttributeError` ou `404`. Confirmer que le test échoue avec le bon message.

- [ ] **Étape 2.4 : Ajouter `etat_cascades_malformees()` dans `state.py`**

```python
def etat_cascades_malformees() -> list[dict[str, Any]]:
    """Liste les dossiers de run présents mais dont state.json est invalide.
    Utile au dashboard pour exposer la couverture réelle (D4 — runs skippés).
    """
    if not state_manager.RUNS_DIR.exists():
        return []
    malformes = []
    for run_dir in state_manager.RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        # Charge en mode raw (extra="ignore") — un run mal-formé reste lisible
        etat_path = run_dir / "state.json"
        if not etat_path.exists():
            continue
        try:
            data = json.loads(etat_path.read_text(encoding="utf-8"))
            CascadeState.model_validate(data)  # validation stricte
        except (ValidationError, json.JSONDecodeError, OSError):
            malformes.append({
                "id_cascade": run_dir.name,
                "chemin": str(run_dir),
                "raison": "state.json invalide ou champs supplémentaires",
            })
    return malformes


def compter_cascades() -> dict[str, int]:
    """Retourne les compteurs de santé du système."""
    if not state_manager.RUNS_DIR.exists():
        return {"runs_total": 0, "runs_chargeables": 0, "runs_malformes": 0}
    total = chargeables = malformes = 0
    for run_dir in state_manager.RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        total += 1
        try:
            etat_path = run_dir / "state.json"
            if etat_path.exists():
                data = json.loads(etat_path.read_text(encoding="utf-8"))
                CascadeState.model_validate(data)
                chargeables += 1
        except (ValidationError, json.JSONDecodeError, OSError):
            malformes += 1
    return {"runs_total": total, "runs_chargeables": chargeables, "runs_malformes": malformes}
```

- [ ] **Étape 2.5 : Ajouter l'endpoint dans `serveur.py`** (après les autres routes API)

```python
@app.get("/api/sante")
async def api_sante() -> dict[str, Any]:
    """Visibilité sur les runs skippés par la validation stricte."""
    from .etat import compter_cascades, etat_cascades_malformees
    from datetime import UTC, datetime
    return {
        **compter_cascades(),
        "malformes_detail": etat_cascades_malformees(),
        "derniere_maj": datetime.now(UTC).isoformat(),
    }
```

- [ ] **Étape 2.6 : Lancer le test ciblé**

```bash
uv run pytest tests/test_dashboard.py::test_api_sante_retourne_compteurs -v --no-header
```

Attendu : PASS.

- [ ] **Étape 2.7 : Pytest complet**

Attendu : `307 passed, 4 skipped` (306 + 1 nouveau).

---

## Tâche 3 : O2 — Pagination `/api/cascades`

**Fichiers :**
- Modifier : `src/goal_cascade/dashboard/serveur.py` (signature endpoint)
- Modifier : `src/goal_cascade/dashboard/state.py` (signature `lister_cascades`)
- Modifier : `src/goal_cascade/dashboard/templates/index.html` + `static/app.js` (UI)
- Backup : `state.py.v3`, `serveur.py.v3`

- [ ] **Étape 3.1 : Backup**

- [ ] **Étape 3.2 : Écrire les tests de pagination**

```python
def test_api_cascades_pagination_defaut(client_runs):
    # Crée 25 cascades factices
    ...
    r = client_runs.get("/api/cascades?limite=10&decalage=0")
    d = r.json()
    assert len(d["cascades"]) == 10
    assert d["total"] == 25
    assert d["limite"] == 10
    assert d["decalage"] == 0


def test_api_cascades_pagination_decalage_20(client_runs):
    ...
    r = client_runs.get("/api/cascades?limite=10&decalage=20")
    d = r.json()
    assert len(d["cascades"]) == 5  # 25 - 20


def test_api_cascades_pagination_limite_max(client_runs):
    """limite > 100 doit être plafonnée à 100."""
    r = client_runs.get("/api/cascades?limite=500")
    d = r.json()
    assert d["limite"] == 100  # plafonné


def test_api_cascades_pagination_tri(client_runs):
    """Tri par défaut : plus récents en premier."""
    ...
    ids = [c["id_cascade"] for c in r.json()["cascades"]]
    # Vérifie que l'ordre décroissant
```

- [ ] **Étape 3.3 : Modifier `lister_cascades()` dans `state.py`**

```python
def lister_cascades(
    limite: int = 50,
    decalage: int = 0,
    tri: str = "recents",
) -> dict[str, Any]:
    """Liste paginée des cascades.
    
    Args:
        limite: nombre max (plafonné à 100).
        decalage: offset pour pagination.
        tri: 'recents' (par défaut) ou 'anciens'.
    """
    if not state_manager.RUNS_DIR.exists():
        return {"cascades": [], "total": 0, "limite": limite, "decalage": decalage}
    
    # ... (logique de tri + pagination)
    return {"cascades": result, "total": len(all_cascades),
            "limite": limite, "decalage": decalage}
```

- [ ] **Étape 3.4 : Modifier l'endpoint dans `serveur.py`**

```python
@app.get("/api/cascades")
async def lister_cascades(
    limite: int = 50,
    decalage: int = 0,
    tri: str = "recents",
) -> dict[str, Any]:
    limite = min(limite, 100)  # plafond
    limite = max(limite, 1)     # minimum
    decalage = max(decalage, 0)
    return state_helpers.lister_cascades(limite=limite, decalage=decalage, tri=tri)
```

- [ ] **Étape 3.5 : Adapter le frontend** (HTML/JS)

Dans `index.html` : ajouter des contrôles de pagination.
Dans `app.js` : passer `?limite=...&decalage=...` et afficher `total`.

- [ ] **Étape 3.6 : Tests**

`uv run pytest tests/test_dashboard.py -v` — tous les tests pagination doivent passer.

- [ ] **Étape 3.7 : Pytest complet** — `310+ passed, 4 skipped`

---

## Tâche 4 : O5 — Filtrage sidebar (statut + recherche)

**Fichiers :**
- Modifier : `src/goal_cascade/dashboard/state.py` (paramètres filtre)
- Modifier : `src/goal_cascade/dashboard/serveur.py` (query params)
- Modifier : `src/goal_cascade/dashboard/templates/index.html` + `static/app.js`
- Backup : `state.py.v4`, `serveur.py.v4`

- [ ] **Étape 4.1 : Backup**

- [ ] **Étape 4.2 : Tests**

```python
def test_api_cascades_filtre_statut(client_runs, setup_cascades):
    r = client_runs.get("/api/cascades?statut=stopped")
    cascades = r.json()["cascades"]
    assert all(c["statut"] == "stopped" for c in cascades)


def test_api_cascades_recherche_dans_objectif(client_runs, setup_cascades):
    r = client_runs.get("/api/cascades?q=refactor")
    assert any("refactor" in c["objectif"].lower() for c in r.json()["cascades"])


def test_api_cascades_filtres_combines(client_runs, setup_cascades):
    r = client_runs.get("/api/cascades?statut=stopped&q=test")
    d = r.json()["cascades"]
    assert all(c["statut"] == "stopped" and "test" in c["objectif"].lower() for c in d)
```

- [ ] **Étape 4.3 : Modifier `lister_cascades()` pour accepter `statut` et `q`**

- [ ] **Étape 4.4 : Modifier l'endpoint** pour passer les query params

- [ ] **Étape 4.5 : UI : champ de recherche + dropdown statut**

- [ ] **Étape 4.6 : Pytest complet** — `313+ passed`

---

## Tâche 5 : O4 — Hot-reload prompts mid-run (le plus complexe)

**Fichiers :**
- Modifier : `src/goal_cascade/orchestrator/cascade_graph.py` (recharger prompt avant appel)
- Modifier : `src/goal_cascade/orchestrator/synthesizer.py` (idem)
- Créer : `src/goal_cascade/orchestrator/prompt_resolver.py` (charge avec override prioritaire)
- Backup : `cascade_graph.py.v1`, `synthesizer.py.v1`

**Stratégie :** L'orchestrateur vérifie à chaque appel s'il existe un override pour (run_id, role) dans `~/.goal/runs/{run_id}/prompts/{role}.j2`. Si oui, il l'utilise. Sinon, fallback au template standard.

- [ ] **Étape 5.1 : Backup**

- [ ] **Étape 5.2 : Tests**

```python
def test_prompt_resolver_charge_override_run_specifique(tmp_path):
    # Crée override pour run-X mais pas pour run-Y
    (tmp_path / "run-X" / "prompts").mkdir(parents=True)
    (tmp_path / "run-X" / "prompts" / "iteration_1.j2").write_text("OVERRIDE X")
    
    resolver = PromptResolver(runs_dir=tmp_path)
    assert resolver.load("iteration_1.j2", run_id="run-X") == "OVERRIDE X"
    # Pas d'override pour run-Y → fallback
    default = resolver.load("iteration_1.j2", run_id="run-Y")
    assert "OVERRIDE" not in default


def test_prompt_resolver_securise_contre_path_traversal(tmp_path):
    """Override hors run_dir ne doit pas fuiter."""
    # Crée un fichier ailleurs
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "iteration_1.j2").write_text("INJECTED")
    
    resolver = PromptResolver(runs_dir=tmp_path / "nonexistent")
    # Doit retomber sur défaut, pas charger "other"
    with pytest.raises(Exception):
        resolver.load("iteration_1.j2", run_id=None)
```

- [ ] **Étape 5.3 : Créer `prompt_resolver.py`**

```python
"""Résolveur de prompts avec support des overrides par run."""
from pathlib import Path

class PromptResolver:
    """Charge les prompts Jinja2 avec override prioritaire par (run_id, role)."""
    
    def __init__(self, runs_dir: Path):
        self.runs_dir = runs_dir
    
    def load(self, template_name: str, run_id: str | None = None) -> str:
        """Charge un prompt avec recherche override → défaut."""
        if run_id:
            override = self.runs_dir / run_id / "prompts" / f"{template_name}.j2"
            if override.exists() and self._is_safe(override):
                return override.read_text(encoding="utf-8")
        # Fallback : PromptLoader standard
        from ..prompts import PromptLoader
        loader = PromptLoader()
        source, _, _ = loader.env.loader.get_source(
            loader.env, f"{template_name}.j2"
        )
        return source
    
    def _is_safe(self, path: Path) -> bool:
        """Vérifie que path est bien sous runs_dir (anti-path-traversal)."""
        try:
            path.resolve().relative_to(self.runs_dir.resolve())
            return True
        except ValueError:
            return False
```

- [ ] **Étape 5.4 : Modifier `cascade_graph.py` et `synthesizer.py`** pour utiliser PromptResolver

- [ ] **Étape 5.5 : Tests d'intégration** : un run avec override utilise l'override

- [ ] **Étape 5.6 : Pytest complet**

---

## Récapitulatif attendu

| Tâche | Tests ajoutés | Total pytest |
|---|---|---|
| 1 — Tests endpoints | 6 | 306 passed |
| 2 — /api/sante | 1 | 307 passed |
| 3 — Pagination | 4 | 311 passed |
| 4 — Filtrage | 3 | 314 passed |
| 5 — Hot-reload | 2-3 | 316-317 passed |

**Réserve** : `4 skipped` constants (tests d'intégration qui nécessitent vraie API).

## Règles respectées à chaque étape

1. **Backup .vN avant chaque Edit** sur fichier existant
2. **Edit** (jamais Write) sur les fichiers existants
3. **Test avant → fail → impl → test après → pass** (TDD strict)
4. **`pytest` complet** après chaque tâche (vérifier 0 régression)
5. **Statut réel / Portée réelle / Preuve / Prochaine étape** à la fin de chaque tâche

## Hors scope

- **O3 CORS** : non critique pour localhost, différé.
- **Suppression de `schemas/models.py`** : shim de compat OK, nettoyage en Phase 6+.
- **Modifications de mocks / tests de Phase 5 dashboard** autres que ceux ci-dessus.
