Livrable final.

```python
# src/goal_cascade/is_non_empty.py
def is_non_empty(value: object) -> bool:
    """Retourne True si ``value`` est une str contenant au moins un caractère non blanc."""
    return isinstance(value, str) and any(not c.isspace() for c in value)
```

```python
# tests/test_is_non_empty.py
"""Tests pytest pour is_non_empty."""

from __future__ import annotations

import pytest

from goal_cascade.is_non_empty import is_non_empty


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Cas positifs
        ("a", True),
        (" hello ", True),
        ("  \t\n  x  \t\n  ", True),
        ("é", True),
        ("\u00A0\u2000Z\u2003", True),
        ("x", True),
        (" \t\nvisible\t\n ", True),
        ("\x00", True),  # caractère de contrôle non blanc
        # Cas négatifs
        ("", False),
        ("   ", False),
        ("\t\n\r", False),
        ("\u00A0\u2000\u2003", False),
        (None, False),
        (0, False),
        ([], False),
        ({}, False),
        (b"bytes", False),
        (3.14, False),
        (object(), False),
    ],
)
def test_is_non_empty(value, expected):
    assert is_non_empty(value) is expected


def test_is_non_empty_long_whitespace_only():
    assert is_non_empty(" " * 10_000_000) is False
```

```text
$ .venv/bin/python -m pytest -v
============================== 31 passed in 4.22s ==============================
```

VERDICT : STOP
JUSTIFICATION : La fonction retourne correctement True uniquement pour les instances str contenant au moins un caractère non blanc, avec une complexité mémoire O(1) via any(not c.isspace() for c in value) ; la suite pytest passe intégralement (31/31), incluant les cas limites unicode, non-str, caractère de contrôle \x00 et chaîne blanche longue, et le fichier a été déplacé dans src/goal_cascade/.