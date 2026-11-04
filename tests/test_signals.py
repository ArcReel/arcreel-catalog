"""巡检信号：从第三方数据里找出需要巡检到官方来源核实的条目。全部用离线 fixture。"""

from __future__ import annotations

from datetime import date

from catalog_build.signals import collect_signals

TODAY = date(2026, 11, 4)
OPENAI = {"provider": "openai", "maker": "openai", "currency": "USD", "canonical": "openai"}
RULES = {"makers": [OPENAI], "listing_min_release_date": "2026-01-01", "listing_exclude": []}

VEO = {
    "maker": "google",
    "name": "veo-x",
    "media_type": "video",
    "display_name": "Veo X",
    "release_date": "2026-01-01",
    "facts": {"durations": [8]},
    "price": {
        "currency": "USD",
        "meters": [
            {
                "meter": "output_seconds",
                "dims": ["resolution"],
                "rows": [{"when": {"resolution": "720p"}, "price": 0.4}, {"when": {"resolution": "4k"}, "price": 0.6}],
            }
        ],
    },
}


def text_model(name: str, **extra) -> dict:
    return {
        "name": name,
        "modalities": {"input": ["text"], "output": ["text"]},
        "release_date": "2026-03-01",
        "cost": {"input": 1, "output": 4},
        **extra,
    }


def text_entry(name: str, **extra) -> dict:
    return {
        "maker": "openai",
        "name": name,
        "media_type": "text",
        "display_name": name,
        "release_date": "2026-03-01",
        "facts": {"image_input": False, "structured_output": False},
        **extra,
    }


def signals(*, upstream: dict | None = None, human: list | None = None, litellm: dict | None = None) -> dict:
    """按类别归组的信号对象（``maker/name``）。"""
    models = {"openai": {"models": {"gpt-a": text_model("gpt-a")} if upstream is None else upstream}}
    grouped: dict[str, list[str]] = {}
    for signal in collect_signals([models], RULES, human or [], {}, litellm or {}, today=TODAY):
        grouped.setdefault(signal.kind, []).append(signal.subject)
    return grouped


def test_litellm_price_on_native_channel_missing_from_catalog_is_reported() -> None:
    litellm = {
        "gemini/veo-x": {"litellm_provider": "gemini", "output_cost_per_second": 0.4, "output_cost_per_second_4k": 0.6},
        "vertex_ai/veo-x": {"litellm_provider": "vertex_ai-video-models", "output_cost_per_second_1080p": 0.5},
        "fal_ai/veo-x": {"litellm_provider": "fal_ai", "output_cost_per_second": 9.9},  # 中转渠道不比
        "sample_spec": {"max_tokens": "set to max"},
    }

    upstream = {"openai": {"models": {"gpt-a": text_model("gpt-a")}}}
    found = collect_signals([upstream], RULES, [VEO], {}, litellm, today=TODAY)

    prices = [signal for signal in found if signal.kind == "litellm-price"]
    assert [signal.subject for signal in prices] == ["google/veo-x"]
    assert "vertex_ai/veo-x" in prices[0].detail
    assert "0.5" in prices[0].detail


def test_litellm_price_skips_retired_and_domestic_entries() -> None:
    litellm = {"gemini/veo-x": {"litellm_provider": "gemini", "output_cost_per_second": 1.0}}
    human = [
        {**VEO, "discontinued": True},
        {**VEO, "name": "veo-y", "shutdown_date": "2026-10-01"},
        {**VEO, "maker": "bytedance"},
    ]
    litellm["gemini/veo-y"] = {"litellm_provider": "gemini", "output_cost_per_second": 1.0}

    assert "litellm-price" not in signals(human=human, litellm=litellm)


def test_upstream_deprecated_text_model_without_shutdown_date_is_reported() -> None:
    upstream = {
        "gpt-a": text_model("gpt-a", status="deprecated"),
        "gpt-b": text_model("gpt-b", status="deprecated"),
        "gpt-c": text_model("gpt-c"),
    }
    human = [text_entry("gpt-b", shutdown_date="2026-12-01")]

    assert signals(upstream=upstream, human=human)["upstream-deprecated"] == ["openai/gpt-a"]


def test_litellm_deprecation_date_differing_from_entry_is_reported() -> None:
    litellm = {
        "gpt-a": {"litellm_provider": "openai", "deprecation_date": "2027-01-14"},
        "gpt-b": {"litellm_provider": "openai", "deprecation_date": "2026-12-01"},
        "azure/gpt-c": {"litellm_provider": "azure", "deprecation_date": "2026-12-01"},  # 中转渠道不看
    }
    upstream = {name: text_model(name) for name in ("gpt-a", "gpt-b", "gpt-c")}
    human = [text_entry("gpt-b", shutdown_date="2026-12-01")]

    assert signals(upstream=upstream, human=human, litellm=litellm)["litellm-deprecation"] == ["openai/gpt-a"]


def test_media_model_on_native_channel_without_entry_is_reported() -> None:
    litellm = {
        "gemini/veo-y": {"litellm_provider": "gemini", "mode": "video_generation"},
        "gemini/veo-x": {"litellm_provider": "gemini", "mode": "video_generation"},  # 已收录
        "gemini/veo-x-20260101": {"litellm_provider": "gemini", "mode": "video_generation"},  # 已收录型号的日期快照
        "gemini/veo-old": {"litellm_provider": "gemini", "mode": "video_generation", "deprecation_date": "2026-06-30"},
        "fal_ai/veo-z": {"litellm_provider": "fal_ai", "mode": "video_generation"},
    }

    assert signals(human=[VEO], litellm=litellm)["unlisted-media"] == ["google/veo-y"]


def test_expired_human_entry_is_a_cleanup_candidate_only_when_upstream_dropped_the_name() -> None:
    upstream = {"gpt-kept": text_model("gpt-kept")}
    human = [
        text_entry("gpt-kept", shutdown_date="2026-01-01"),
        text_entry("gpt-gone", shutdown_date="2026-01-01"),
        text_entry("gpt-recent", shutdown_date="2026-10-01"),
    ]

    assert signals(upstream=upstream, human=human)["expired-cleanup"] == ["openai/gpt-gone"]


def test_upcoming_shutdown_auto_successor_and_missing_release_date_are_reported() -> None:
    upstream = {"gpt-auto": text_model("gpt-auto")}
    undated = {key: value for key, value in VEO.items() if key != "release_date"}
    human = [text_entry("gpt-old", shutdown_date="2026-11-20", successor="openai/gpt-auto"), undated]

    found = signals(upstream=upstream, human=human)

    assert found["shutdown-soon"] == ["openai/gpt-old"]
    assert found["auto-successor"] == ["openai/gpt-old"]
    assert found["missing-release-date"] == ["google/veo-x"]
