from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_ledger() -> Path:
    return Path(__file__).resolve().parents[1] / "samples" / "ledger"


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
