import pytest

from goal_cascade.rag.embed import OllamaEmbedding


def test_ollama_embedding_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_EMBED_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    emb = OllamaEmbedding()
    assert emb.url == "http://127.0.0.1:11434/api/embed"
    assert emb.model_name == "bge-m3:latest"


def test_ollama_embedding_uses_env_variables(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_EMBED_URL", "http://10.0.0.1:11434/api/embed")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "custom-model")
    emb = OllamaEmbedding()
    assert emb.url == "http://10.0.0.1:11434/api/embed"
    assert emb.model_name == "custom-model"


def test_ollama_embedding_derives_url_from_host(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.1:11434")
    monkeypatch.delenv("OLLAMA_EMBED_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    emb = OllamaEmbedding()
    assert emb.url == "http://10.0.0.1:11434/api/embed"
    assert emb.model_name == "bge-m3:latest"


def test_ollama_embedding_rejects_non_http_url(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_EMBED_URL", "file:///etc/passwd")
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    emb = OllamaEmbedding()
    with pytest.raises(ValueError, match="URL Ollama invalide"):
        list(emb.embed(["test"]))
