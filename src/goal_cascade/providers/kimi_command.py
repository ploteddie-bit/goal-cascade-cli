"""Providers locaux basés sur les modes non interactifs des deux CLI Kimi."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from enum import Enum
from pathlib import Path

from .base import BaseProvider, LLMResponse


class KimiBackend(str, Enum):
    CLI = "kimi-cli"
    CODE = "kimi-code"


class ProviderCommandError(RuntimeError):
    """L'exécutable Kimi a échoué ou n'a pas produit de réponse exploitable."""


class KimiCommandProvider(BaseProvider):
    """Lance une nouvelle session Kimi non interactive à chaque appel."""

    SAFETY_PREFIX = """CONTRAINTE D'EXÉCUTION ABSOLUE :
- N'utilise aucun outil, aucune commande shell et aucun sous-agent.
- Ne lis, ne crées, ne modifies et ne supprimes aucun fichier.
- Réponds uniquement avec le texte demandé dans ce prompt.

"""

    def __init__(
        self,
        backend: KimiBackend,
        work_dir: Path | None = None,
        timeout_s: int = 300,
        executable: str | None = None,
        isolate_work_dir: bool = True,
    ):
        self.backend = backend
        self.work_dir = work_dir or Path.cwd()
        self.timeout_s = timeout_s
        self.executable = executable or self._default_executable(backend)
        self.isolate_work_dir = isolate_work_dir

    @property
    def name(self) -> str:
        return self.backend.value

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        isolated_prompt = f"{self.SAFETY_PREFIX}{prompt}"
        command = self._command(isolated_prompt)
        started = time.monotonic()
        try:
            if self.isolate_work_dir:
                with tempfile.TemporaryDirectory(prefix="goal-kimi-") as temp_dir:
                    result = self._run(command, Path(temp_dir))
            else:
                result = self._run(command, self.work_dir)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderCommandError(
                f"Échec d'exécution de {self.backend.value} : {exc}"
            ) from exc

        if result.returncode != 0:
            details = (result.stderr or result.stdout or "erreur inconnue").strip()
            raise ProviderCommandError(
                f"{self.backend.value} a quitté avec le code {result.returncode}: "
                f"{details}"
            )

        text = self.extract_assistant_text(result.stdout)
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResponse(
            text=text,
            provider=self.backend.value,
            model=self.backend.value,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            cost_usd=0.0,
            latency_ms=latency_ms,
            token_count_estimated=True,
        )

    def _run(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            check=False,
        )

    def _command(self, prompt: str) -> list[str]:
        if self.backend == KimiBackend.CLI:
            return [
                self.executable,
                "--print",
                "--output-format",
                "stream-json",
                "-p",
                prompt,
            ]
        return [
            self.executable,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
        ]

    @staticmethod
    def extract_assistant_text(output: str) -> str:
        messages: list[str] = []
        for line in output.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("role") != "assistant":
                continue
            content = payload.get("content")
            if isinstance(content, str) and content.strip():
                messages.append(content.strip())
            elif isinstance(content, list):
                text_parts = [
                    part.get("text", "").strip()
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                text = "\n".join(part for part in text_parts if part)
                if text:
                    messages.append(text)
        if not messages:
            raise ProviderCommandError("Aucun message assistant dans le flux stream-json")
        return messages[-1]

    @staticmethod
    def _default_executable(backend: KimiBackend) -> str:
        if backend == KimiBackend.CLI:
            configured = os.environ.get("GOAL_KIMI_CLI_BIN")
            return configured or shutil.which("kimi") or str(
                Path.home() / ".local" / "bin" / "kimi"
            )
        return os.environ.get("GOAL_KIMI_CODE_BIN") or str(
            Path.home() / ".kimi-code" / "bin" / "kimi"
        )
