from pathlib import Path

from goal_cascade.rag import (
    default_ollama_embed_model,
    default_ollama_embed_url,
    default_ollama_host,
    resolve_embed_module_path,
    resolve_worker_path,
)


def test_defaults_use_localhost(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    assert default_ollama_host() == "http://127.0.0.1:11434"
    assert default_ollama_embed_url() == "http://127.0.0.1:11434/api/embed"
    assert default_ollama_embed_model() == "bge-m3:latest"


def test_resolve_worker_path_points_to_versioned_worker() -> None:
    path = resolve_worker_path()
    assert path.name == "worker.py"
    assert "src/goal_cascade/rag" in str(path)


def test_resolve_embed_module_path_points_to_versioned_embed() -> None:
    path = resolve_embed_module_path()
    assert path.name == "embed.py"
    assert "src/goal_cascade/rag" in str(path)
