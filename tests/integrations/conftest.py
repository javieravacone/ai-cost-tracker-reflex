from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
EU_FIXTURE = FIXTURES / "copilot-0.69-langsmith-eu.json"
CONTENT_FIXTURE = FIXTURES / "copilot-0.69-content-turn.json"


def load_fixture(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def eu_runs() -> list[dict[str, Any]]:
    return load_fixture(EU_FIXTURE)


@pytest.fixture
def content_runs() -> list[dict[str, Any]]:
    return load_fixture(CONTENT_FIXTURE)
