from __future__ import annotations

from importlib.resources import files


def test_all_runtime_templates_are_packaged() -> None:
    prompt_dir = files("goal_cascade.prompts")
    expected = {
        "iteration_1.j2",
        "iteration_2.j2",
        "iteration_3.j2",
        "iteration_4.j2",
        "synthesis.j2",
        "technical_iteration_1.j2",
        "technical_iteration_2.j2",
        "technical_iteration_3.j2",
        "technical_iteration_4.j2",
    }

    missing = sorted(name for name in expected if not prompt_dir.joinpath(name).is_file())

    assert missing == []
