"""Package RAG versionné pour G.O.A.L. Cascade."""

from __future__ import annotations

import os
from pathlib import Path


def default_ollama_host() -> str:
    """URL de base Ollama par défaut, configurable via OLLAMA_HOST."""
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def default_ollama_embed_url() -> str:
    """URL de l'endpoint embeddings Ollama par défaut."""
    return os.environ.get("OLLAMA_EMBED_URL", f"{default_ollama_host()}/api/embed").rstrip("/")


def default_ollama_embed_model() -> str:
    """Modèle d'embeddings par défaut, configurable via OLLAMA_EMBED_MODEL."""
    return os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3:latest")


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def resolve_worker_path() -> Path:
    """Chemin du worker RAG versionné dans le package."""
    return _package_dir() / "worker.py"


def resolve_embed_module_path() -> Path:
    """Chemin du module d'embeddings versionné dans le package."""
    return _package_dir() / "embed.py"
