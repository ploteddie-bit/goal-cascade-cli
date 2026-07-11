"""Synthèse orientée objectif et préservation des artefacts techniques."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import ValidationError

from ..prompts import PromptLoader
from ..providers.base import BaseProvider, LLMResponse
from ..schemas.models import GoalOrientedSynthesis, ImmutableArtifact

CODE_BLOCK_RE = re.compile(
    r"```(?P<language>[\w.+-]*)\s*\n(?P<content>.*?)```",
    re.DOTALL,
)
JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class SynthesisError(ValueError):
    """La réponse du synthétiseur ne respecte pas le contrat JSON."""

    response: LLMResponse | None = None


@dataclass(frozen=True)
class SynthesisResult:
    synthesis: GoalOrientedSynthesis
    artifacts: list[ImmutableArtifact]
    response: LLMResponse
    prompt: str


class Synthesizer:
    """Produit les quatre blocs de synthèse et conserve le code intact."""

    def __init__(self, provider: BaseProvider, prompt_loader: PromptLoader):
        self.provider = provider
        self.prompt_loader = prompt_loader

    def process(
        self,
        raw_output: str,
        objective: str,
        iteration_from: int,
        iteration_to: int,
        previous_synthesis: GoalOrientedSynthesis | None = None,
        previous_artifacts: list[ImmutableArtifact] | None = None,
        prompt: str | None = None,
    ) -> SynthesisResult:
        prompt = prompt or self.build_prompt(
            raw_output=raw_output,
            objective=objective,
            iteration_from=iteration_from,
            iteration_to=iteration_to,
            previous_synthesis=previous_synthesis,
        )
        response = self.provider.call(prompt, role="synthesizer", tier="small")
        try:
            synthesis = self._parse_response(
                response.text,
                iteration_from=iteration_from,
                iteration_to=iteration_to,
            )
        except SynthesisError as error:
            error.response = response
            raise
        artifacts = self._merge_artifacts(
            previous_artifacts or [],
            self._extract_artifacts(raw_output, iteration_from),
        )
        return SynthesisResult(
            synthesis=synthesis,
            artifacts=artifacts,
            response=response,
            prompt=prompt,
        )

    def build_prompt(
        self,
        raw_output: str,
        objective: str,
        iteration_from: int,
        iteration_to: int,
        previous_synthesis: GoalOrientedSynthesis | None = None,
    ) -> str:
        """Construit le prompt avant l'appel pour pouvoir l'auditer."""
        return self.prompt_loader.render(
            "synthesis.j2",
            objective=objective,
            previous_output=raw_output,
            previous_synthesis=(
                previous_synthesis.model_dump_json(indent=2) if previous_synthesis else ""
            ),
            iteration_from=iteration_from,
            iteration_to=iteration_to,
        )

    @staticmethod
    def _parse_response(
        text: str,
        iteration_from: int,
        iteration_to: int,
    ) -> GoalOrientedSynthesis:
        # Premier essai : le texte brut est déjà du JSON valide.
        candidate: str | None = None
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            candidate = stripped

        # Sinon, extraire d'un bloc ```json ... ``` ou du premier objet JSON.
        if candidate is None:
            fenced = JSON_FENCE_RE.search(text)
            if fenced:
                candidate = fenced.group(1)
            else:
                start = text.find("{")
                end = text.rfind("}")
                if start == -1 or end <= start:
                    raise SynthesisError("Le synthétiseur n'a retourné aucun objet JSON")
                candidate = text[start : end + 1]

        try:
            data = json.loads(candidate)
            data["iteration_from"] = iteration_from
            data["iteration_to"] = iteration_to
            return GoalOrientedSynthesis.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise SynthesisError(f"Synthèse JSON invalide : {exc}") from exc

    @staticmethod
    def _extract_artifacts(text: str, iteration: int) -> list[ImmutableArtifact]:
        artifacts: list[ImmutableArtifact] = []
        for match in CODE_BLOCK_RE.finditer(text):
            language = match.group("language").strip().lower() or None
            content = match.group("content").rstrip()
            if not content:
                continue
            artifact_type = cast(
                Literal["code", "json_schema", "formula", "test", "config", "sql"],
                {
                    "json": "json_schema",
                    "jsonschema": "json_schema",
                    "sql": "sql",
                    "toml": "config",
                    "yaml": "config",
                    "yml": "config",
                }.get(language or "", "code"),
            )
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            artifacts.append(
                ImmutableArtifact(
                    artifact_type=artifact_type,
                    language=language,
                    content=content,
                    checksum=checksum,
                    source_iteration=iteration,
                )
            )
        return artifacts

    @staticmethod
    def _merge_artifacts(
        previous: list[ImmutableArtifact],
        current: list[ImmutableArtifact],
    ) -> list[ImmutableArtifact]:
        merged: dict[str, ImmutableArtifact] = {}
        for artifact in [*previous, *current]:
            key = artifact.checksum or hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()
            merged[key] = artifact
        return list(merged.values())
