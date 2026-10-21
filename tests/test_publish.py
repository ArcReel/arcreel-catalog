"""发布：过同一份校验器才写出，内容不变不产生新数据集版本。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from arcreel_catalog_core import check_catalog_files

from catalog_build.__main__ import PublishError, main, publish

NOW = datetime(2026, 10, 21, 8, 0, 0, tzinfo=UTC)

ENTRY = {
    "maker": "openai",
    "name": "gpt-a",
    "media_type": "text",
    "display_name": "GPT A",
    "facts": {"image_input": True, "structured_output": True},
    "price": {
        "currency": "USD",
        "meters": [{"meter": "output_tokens", "dims": [], "rows": [{"when": {}, "price": 4.0}]}],
    },
}
BODY = {
    "entries": [ENTRY],
    "builtin_providers": {
        "openai": {"models": [{"api_model_name": "gpt-a", "entry": "openai/gpt-a"}], "defaults": {"text": "gpt-a"}}
    },
}


def published(directory: Path) -> dict:
    return json.loads((directory / "catalog.json").read_bytes())


def test_first_publish_writes_files_that_pass_the_validator(tmp_path: Path) -> None:
    assert publish(tmp_path, BODY, NOW) is True

    assert published(tmp_path)["dataset_version"] == "2026-10-21T08:00:00Z"
    assert (
        check_catalog_files((tmp_path / "manifest.json").read_bytes(), (tmp_path / "catalog.json").read_bytes()) == []
    )


def test_unchanged_content_keeps_the_dataset_version(tmp_path: Path) -> None:
    publish(tmp_path, BODY, NOW)
    before = (tmp_path / "catalog.json").read_bytes(), (tmp_path / "manifest.json").read_bytes()

    assert publish(tmp_path, BODY, datetime(2026, 10, 22, tzinfo=UTC)) is False

    assert ((tmp_path / "catalog.json").read_bytes(), (tmp_path / "manifest.json").read_bytes()) == before


def test_changed_content_gets_a_newer_dataset_version(tmp_path: Path) -> None:
    publish(tmp_path, BODY, NOW)
    changed = {**BODY, "entries": [{**ENTRY, "display_name": "GPT A v2"}]}

    # 时钟回拨也要保证新版本晚于旧版本
    assert publish(tmp_path, changed, datetime(2026, 10, 20, tzinfo=UTC)) is True

    assert published(tmp_path)["dataset_version"] == "2026-10-21T08:00:01Z"


def test_invalid_catalog_is_not_published(tmp_path: Path) -> None:
    publish(tmp_path, BODY, NOW)
    before = (tmp_path / "catalog.json").read_bytes()
    broken = {
        **BODY,
        "builtin_providers": {
            "openai": {"models": [{"api_model_name": "x", "entry": "openai/missing"}], "defaults": {}}
        },
    }

    with pytest.raises(PublishError, match="unknown_entry"):
        publish(tmp_path, broken, NOW)

    assert (tmp_path / "catalog.json").read_bytes() == before


def test_cli_builds_from_local_files(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "entries").mkdir(parents=True)
    (data / "entries" / "agnes.json").write_text(json.dumps([{**ENTRY, "maker": "agnes", "name": "agnes-1"}]))
    (data / "upstream.json").write_text(
        json.dumps(
            {
                "makers": [{"provider": "openai", "maker": "openai", "currency": "USD", "canonical": "openai"}],
                "listing_min_release_date": "2026-01-01",
            }
        )
    )
    (data / "builtin_providers.json").write_text(
        json.dumps({"openai": {"upstream": ["openai"], "defaults": {"text": "gpt-b"}}})
    )
    upstream = tmp_path / "upstream.json"
    upstream.write_text(
        json.dumps(
            {
                "openai": {
                    "models": {
                        "gpt-b": {
                            "name": "GPT B",
                            "modalities": {"input": ["text"], "output": ["text"]},
                            "release_date": "2026-02-01",
                            "cost": {"input": 1, "output": 2},
                        }
                    }
                }
            }
        )
    )
    out = tmp_path / "out"
    out.mkdir()
    args = ["build", "--basellm", str(upstream), "--models-dev", str(upstream), "--data", str(data), "--out", str(out)]

    assert main([*args, "--check-only"]) == 0
    assert not (out / "catalog.json").exists()
    assert main(args) == 0
    catalog = published(out)
    assert [entry["name"] for entry in catalog["entries"]] == ["agnes-1", "gpt-b"]
    assert catalog["builtin_providers"]["openai"]["models"] == [{"api_model_name": "gpt-b", "entry": "openai/gpt-b"}]
