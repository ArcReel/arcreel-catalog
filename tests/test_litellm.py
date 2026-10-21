"""LiteLLM 比对只报告原厂渠道上与人工数据不一致的单价。"""

from __future__ import annotations

from catalog_build.litellm import compare_litellm

VEO = {
    "maker": "google",
    "name": "veo-x",
    "media_type": "video",
    "display_name": "Veo X",
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


def test_reports_native_channel_price_missing_from_catalog() -> None:
    litellm = {
        "gemini/veo-x": {"litellm_provider": "gemini", "output_cost_per_second": 0.4, "output_cost_per_second_4k": 0.6},
        "vertex_ai/veo-x": {"litellm_provider": "vertex_ai-video-models", "output_cost_per_second_1080p": 0.5},
        "fal_ai/veo-x": {"litellm_provider": "fal_ai", "output_cost_per_second": 9.9},  # 中转渠道不比
        "sample_spec": {"max_tokens": "set to max"},
    }

    report = list(compare_litellm([VEO], litellm))

    assert len(report) == 1
    assert "vertex_ai/veo-x" in report[0]
    assert "0.5" in report[0]


def test_skips_text_discontinued_and_domestic_entries() -> None:
    litellm = {"gemini/veo-x": {"litellm_provider": "gemini", "output_cost_per_second": 1.0}}
    entries = [{**VEO, "discontinued": True}, {**VEO, "maker": "bytedance"}, {**VEO, "media_type": "text"}]

    assert list(compare_litellm(entries, litellm)) == []
