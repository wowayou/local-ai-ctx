from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]


def test_project_schema_validates_sample_ledger() -> None:
    schema = _load_json(ROOT / "schemas" / "projects.schema.json")
    data = _load_yaml(ROOT / "samples" / "ledger" / "projects.yml")

    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(data)


def test_provider_schema_validates_sample_ledger() -> None:
    schema = _load_json(ROOT / "schemas" / "providers.schema.json")
    data = _load_yaml(ROOT / "samples" / "ledger" / "providers.yml")

    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(data)


def test_project_schema_rejects_unknown_status() -> None:
    schema = _load_json(ROOT / "schemas" / "projects.schema.json")
    data = {
        "projects": {
            "demo": {
                "name": "demo",
                "status": "mystery",
                "next_action": "Pick the next useful task",
            }
        }
    }

    errors = list(Draft7Validator(schema).iter_errors(data))

    assert any("mystery" in error.message for error in errors)


def test_provider_schema_rejects_unknown_scope_surface() -> None:
    schema = _load_json(ROOT / "schemas" / "providers.schema.json")
    data = {
        "providers": {
            "official": {
                "type": "official",
                "scope": {"surfaces": ["phone"]},
            }
        }
    }

    errors = list(Draft7Validator(schema).iter_errors(data))

    assert any("phone" in error.message for error in errors)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
