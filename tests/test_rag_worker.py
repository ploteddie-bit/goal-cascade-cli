from pathlib import Path

from goal_cascade.rag.worker import verify_endpoint


def test_verify_endpoint_uses_env_host(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.1:11434")
    monkeypatch.delenv("OLLAMA_EMBED_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    # On mock la vérification HTTP pour ne pas dépendre d'Ollama en test
    import urllib.request

    def fake_urlopen(req, **kwargs):
        class FakeResponse:
            def read(self):
                return b'{"models":[{"name":"bge-m3:latest"}]}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    embed_url, model = verify_endpoint()
    assert embed_url == "http://10.0.0.1:11434/api/embed"
    assert model == "bge-m3:latest"
