"""Tests des schemas de versionnement (RunVersion, RunVersionsList, VersionDiff)."""

from __future__ import annotations

from goal_cascade.schemas.versioning import RunVersion, RunVersionsList, VersionDiff

# ── Helpers ─────────────────────────────────────────────────────


def _make_version(
    version_id: str = "v1",
    run_id: str = "run-001",
    cost: float = 0.01,
    iterations: int = 3,
    verdict: str = "STOP",
    created_at: str = "2026-07-11T10:00:00+00:00",
) -> RunVersion:
    return RunVersion(
        version_id=version_id,
        run_id=run_id,
        total_cost_usd=cost,
        iteration_count=iterations,
        final_verdict=verdict,
        created_at=created_at,
        status="stopped",
        objective="Test objective",
    )


# ── TestRunVersion ──────────────────────────────────────────────


class TestRunVersion:
    def test_version_creation(self) -> None:
        v = _make_version(
            version_id="v1",
            run_id="run-001",
            cost=0.05,
            iterations=3,
            verdict="STOP",
            created_at="2026-07-11T10:00:00+00:00",
        )

        assert v.version_id == "v1"
        assert v.run_id == "run-001"
        assert v.total_cost_usd == 0.05
        assert v.iteration_count == 3
        assert v.final_verdict == "STOP"
        assert v.created_at == "2026-07-11T10:00:00+00:00"
        assert v.parent_version is None
        assert v.status == "stopped"
        assert v.variant == "A"
        assert v.tags == []

    def test_version_with_parent(self) -> None:
        v = _make_version(version_id="v2", run_id="run-001")
        v.parent_version = "v1"

        assert v.parent_version == "v1"
        assert v.version_id == "v2"


# ── TestRunVersionsList ─────────────────────────────────────────


class TestRunVersionsList:
    def test_from_versions_sorted_by_date(self) -> None:
        v_oldest = _make_version(version_id="v1", created_at="2026-07-11T08:00:00+00:00")
        v_newest = _make_version(version_id="v3", created_at="2026-07-11T12:00:00+00:00")
        v_middle = _make_version(version_id="v2", created_at="2026-07-11T10:00:00+00:00")

        # Deliberement dans le desordre
        versions_list = RunVersionsList.from_versions(
            run_id="run-001", versions=[v_newest, v_oldest, v_middle]
        )

        assert versions_list.total_versions == 3
        assert versions_list.latest_version == "v3"
        assert [v.version_id for v in versions_list.versions] == ["v1", "v2", "v3"]

    def test_empty_versions_list(self) -> None:
        versions_list = RunVersionsList.from_versions(run_id="run-001", versions=[])

        assert versions_list.total_versions == 0
        assert versions_list.latest_version is None
        assert versions_list.versions == []


# ── TestVersionDiff ─────────────────────────────────────────────


class TestVersionDiff:
    def test_diff_computation(self) -> None:
        diff = VersionDiff(
            run_id="run-001",
            version_a="v1",
            version_b="v2",
            cost_delta_usd=0.02,
            iteration_delta=1,
            verdict_changed=False,
            verdict_a="STOP",
            verdict_b="STOP",
            new_artifacts=1,
            removed_artifacts=0,
            summary="Cout +0.02 USD, 1 iteration supplementaire",
        )

        assert diff.run_id == "run-001"
        assert diff.version_a == "v1"
        assert diff.version_b == "v2"
        assert diff.cost_delta_usd == 0.02
        assert diff.iteration_delta == 1
        assert diff.verdict_changed is False
        assert diff.new_artifacts == 1
        assert diff.removed_artifacts == 0
        assert "0.02" in diff.summary
