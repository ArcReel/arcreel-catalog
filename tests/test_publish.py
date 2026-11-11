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
        "openai": {
            "models": [{"api_model_name": "gpt-a", "entry": "openai/gpt-a", "endpoint": "openai-responses"}],
            "defaults": {"text": "gpt-a"},
        }
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


def cli_args(tmp_path: Path, *, listing: list[dict] = (), release: str | None = "v0.35.0") -> list[str]:
    """离线构建的命令行参数：本地上游与人工数据，ArcReel 最新发布版本取自本地 release 文件。"""
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
        json.dumps({"openai": {"upstream": ["openai"], "models": list(listing), "defaults": {"text": "gpt-b"}}})
    )
    text_model = {
        "modalities": {"input": ["text"], "output": ["text"]},
        "release_date": "2026-02-01",
        "cost": {"input": 1, "output": 2},
    }
    upstream = tmp_path / "upstream.json"
    upstream.write_text(
        json.dumps(
            {"openai": {"models": {"gpt-b": {"name": "GPT B", **text_model}, "gpt-c": {"name": "GPT C", **text_model}}}}
        )
    )
    app_release = tmp_path / "release.json"
    if release is not None:
        app_release.write_text(json.dumps({"tag_name": release}))
    out = tmp_path / "out"
    out.mkdir()
    return [
        "build",
        *("--basellm", str(upstream), "--models-dev", str(upstream)),
        *("--data", str(data), "--out", str(out), "--app-release", str(app_release)),
    ]


def listed(directory: Path) -> list[str]:
    return [model["api_model_name"] for model in published(directory)["builtin_providers"]["openai"]["models"]]


def test_cli_builds_from_local_files(tmp_path: Path) -> None:
    args = cli_args(tmp_path)
    out = tmp_path / "out"

    assert main([*args, "--check-only"]) == 0
    assert not (out / "catalog.json").exists()
    assert main(args) == 0
    catalog = published(out)
    assert [entry["name"] for entry in catalog["entries"]] == ["agnes-1", "gpt-b", "gpt-c"]
    assert catalog["builtin_providers"]["openai"]["models"] == [
        {"api_model_name": "gpt-b", "entry": "openai/gpt-b", "endpoint": "openai-responses"},
        {"api_model_name": "gpt-c", "entry": "openai/gpt-c", "endpoint": "openai-responses"},
    ]


def test_cli_withholds_models_until_arcreel_releases_their_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gated = [
        {"api_model_name": "gpt-b", "entry": "openai/gpt-b", "min_app_version": "0.35.0"},
        {"api_model_name": "gpt-c", "entry": "openai/gpt-c", "min_app_version": "0.35.1"},
    ]
    args = cli_args(tmp_path, listing=gated)
    out = tmp_path / "out"

    assert main(args) == 0
    assert listed(out) == ["gpt-b"]
    assert "withheld: openai/gpt-c (text, min_app_version 0.35.1)" in capsys.readouterr().out

    (tmp_path / "release.json").write_text(json.dumps({"tag_name": "v0.35.1"}))
    assert main(args) == 0
    assert listed(out) == ["gpt-b", "gpt-c"]
    report = capsys.readouterr().out
    assert "withheld" not in report
    assert "newly listed: openai/gpt-c" in report


@pytest.mark.parametrize("pr_check", [False, True])
@pytest.mark.parametrize("release", [None, "nightly"])
def test_cli_fails_without_a_readable_latest_release(
    tmp_path: Path, release: str | None, pr_check: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    args = cli_args(tmp_path, release="v0.35.0")
    out = tmp_path / "out"
    assert main(args) == 0
    if pr_check:
        args = [*args, "--check-only"]
    before = (out / "catalog.json").read_bytes(), (out / "manifest.json").read_bytes()
    release_file = tmp_path / "release.json"
    if release is None:
        release_file.unlink()
    else:
        release_file.write_text(json.dumps({"tag_name": release}))

    assert main(args) == 1

    assert ((out / "catalog.json").read_bytes(), (out / "manifest.json").read_bytes()) == before
    assert "ArcReel 最新发布版本" in capsys.readouterr().err


def test_cli_publishes_the_rest_when_a_default_model_is_withheld(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = cli_args(tmp_path)
    out = tmp_path / "out"
    assert main(args) == 0
    capsys.readouterr()
    # 新的默认模型要等 ArcReel 发版：其余数据照常发布，默认模型沿用上一次发布的
    data = tmp_path / "data" / "builtin_providers.json"
    providers = json.loads(data.read_text())
    providers["openai"]["models"] = [{"api_model_name": "gpt-c", "entry": "openai/gpt-c", "min_app_version": "0.36"}]
    providers["openai"]["defaults"] = {"text": "gpt-c"}
    data.write_text(json.dumps(providers))

    assert main(args) == 0

    assert listed(out) == ["gpt-b"]
    assert published(out)["builtin_providers"]["openai"]["defaults"] == {"text": "gpt-b"}
    report = capsys.readouterr().out
    assert "withheld: openai/gpt-c (text, min_app_version 0.36)" in report
    assert "withheld default: openai text keeps gpt-b until ArcReel releases 0.36" in report

    (tmp_path / "release.json").write_text(json.dumps({"tag_name": "v0.36.0"}))
    assert main(args) == 0
    assert published(out)["builtin_providers"]["openai"]["defaults"] == {"text": "gpt-c"}


def test_withheld_default_model_without_a_previous_default_is_left_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gated = [{"api_model_name": "gpt-b", "entry": "openai/gpt-b", "min_app_version": "0.36"}]
    args = cli_args(tmp_path, listing=gated)

    assert main(args) == 0

    catalog = published(tmp_path / "out")
    assert listed(tmp_path / "out") == ["gpt-c"]
    assert catalog["builtin_providers"]["openai"]["defaults"] == {}
    report = capsys.readouterr().out
    assert "withheld default: openai text has no default until ArcReel releases 0.36" in report
    assert "newly listed: openai/gpt-b" not in report


def test_newly_listed_tells_media_types_of_the_same_api_model_apart(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gated = [
        {"api_model_name": "gpt-c", "entry": "openai/gpt-c", "media_type": "text"},
        {
            "api_model_name": "gpt-c",
            "entry": "openai/gpt-c",
            "media_type": "image",
            "endpoint": "openai-images",
            "min_app_version": "0.35.1",
        },
    ]
    args = cli_args(tmp_path, listing=gated)
    image = {
        "maker": "openai",
        "name": "gpt-c",
        "media_type": "image",
        "display_name": "GPT C Image",
        "facts": {"text_to_image": True, "output_token_bases": {"medium": 48}},
        "price": {
            "currency": "USD",
            "meters": [{"meter": "image_output_tokens", "dims": [], "rows": [{"when": {}, "price": 30.0}]}],
        },
    }
    (tmp_path / "data" / "entries" / "openai.json").write_text(json.dumps([image]))
    assert main(args) == 0
    assert "withheld: openai/gpt-c (image, min_app_version 0.35.1)" in capsys.readouterr().out

    (tmp_path / "release.json").write_text(json.dumps({"tag_name": "v0.35.1"}))
    assert main(args) == 0
    assert "newly listed: openai/gpt-c (image)" in capsys.readouterr().out


@pytest.mark.parametrize("default_version", ["0.35.0", "0.36"])
@pytest.mark.parametrize("invalid_version", ["0.35.0", "0.36"])
def test_withheld_default_does_not_hide_other_validation_errors(
    tmp_path: Path, default_version: str, invalid_version: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gated = [
        {"api_model_name": "gpt-b", "entry": "openai/gpt-b", "min_app_version": default_version},
        {
            "api_model_name": "gpt-c",
            "entry": "openai/gpt-c",
            "endpoint": "does-not-exist",
            "min_app_version": invalid_version,
        },
    ]
    args = cli_args(tmp_path, listing=gated)

    assert main([*args, "--check-only"]) == 1

    assert "unknown_endpoint" in capsys.readouterr().err


def test_missing_endpoint_is_not_published(tmp_path: Path) -> None:
    model = {"api_model_name": "gpt-a", "entry": "openai/gpt-a"}
    broken = {**BODY, "builtin_providers": {"openai": {"models": [model], "defaults": {}}}}
    with pytest.raises(PublishError, match="missing_endpoint"):
        publish(tmp_path, broken, NOW)
    assert not (tmp_path / "catalog.json").exists()


@pytest.mark.parametrize(
    ("endpoint", "code"),
    [
        ("does-not-exist", "unknown_endpoint"),
        ("openai-images", "endpoint_media_type_mismatch"),
        ("ark-chat", "endpoint_not_selectable"),
    ],
)
def test_invalid_endpoint_is_not_published(tmp_path: Path, endpoint: str, code: str) -> None:
    model = {"api_model_name": "gpt-a", "entry": "openai/gpt-a", "endpoint": endpoint}
    broken = {**BODY, "builtin_providers": {"openai": {"models": [model], "defaults": {}}}}
    with pytest.raises(PublishError, match=code):
        publish(tmp_path, broken, NOW)
    assert not (tmp_path / "catalog.json").exists()
