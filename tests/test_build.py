"""构建规则：上游转换、人工优先、模型别名与内置供应商清单。全部用离线 fixture。"""

from __future__ import annotations

import pytest

from catalog_build.build import build_catalog, convert_price

OPENAI = {"provider": "openai", "maker": "openai", "currency": "USD", "canonical": "openai"}
ZHIPU = {"provider": "zhipuai", "maker": "zhipu", "currency": "CNY", "canonical": "zhipuai"}


def model(name: str, *, cost: dict | None = None, **extra) -> dict:
    return {
        "name": name,
        "modalities": {"input": ["text", "image"], "output": ["text"]},
        "limit": {"context": 400000, "output": 128000},
        "structured_output": True,
        "release_date": "2026-03-01",
        "cost": {"input": 1, "output": 4} if cost is None else cost,
        **extra,
    }


def rules(*makers: dict, **extra) -> dict:
    return {"makers": list(makers), "listing_min_release_date": "2026-01-01", "listing_exclude": [], **extra}


def by_name(result) -> dict:
    return {entry["name"]: entry for entry in result.catalog["entries"]}


def meters(price: dict) -> dict:
    return {meter["meter"]: [(row["when"], row["price"]) for row in meter["rows"]] for meter in price["meters"]}


def test_context_tiers_become_rows_and_missing_cache_read_is_priced_as_input() -> None:
    price, problem = convert_price(
        {"input": 2, "output": 12, "tiers": [{"input": 4, "output": 18, "tier": {"type": "context", "size": 200000}}]},
        OPENAI,
    )

    assert problem is None
    assert meters(price) == {
        "uncached_input_tokens": [({"context_tier": 0}, 2.0), ({"context_tier": 200000}, 4.0)],
        "cache_read_tokens": [({"context_tier": 0}, 2.0), ({"context_tier": 200000}, 4.0)],
        "output_tokens": [({"context_tier": 0}, 12.0), ({"context_tier": 200000}, 18.0)],
    }


def test_free_item_stays_free_in_higher_tiers_and_1h_cache_write_derives_from_input() -> None:
    source = {**OPENAI, "cache_write_1h_input_multiple": 2}
    price, _ = convert_price(
        {"input": 1, "output": 5, "cache_write": 0, "tiers": [{"input": 3, "output": 9, "tier": {"size": 32000}}]},
        source,
    )

    table = meters(price)
    assert table["cache_write_5m_tokens"] == [({"context_tier": 0}, 0.0), ({"context_tier": 32000}, 0.0)]
    assert table["cache_write_1h_tokens"] == [({"context_tier": 0}, 2.0), ({"context_tier": 32000}, 6.0)]
    assert [meter["meter"] for meter in price["meters"]][-2:] == ["cache_write_1h_tokens", "output_tokens"]


@pytest.mark.parametrize(
    "cost",
    [
        {"input": 1, "output": 4, "currency": "CNY"},  # 不是厂商主站币种，不做汇率换算
        {"input": 1, "output": 4, "reasoning": 8},  # 推理 token 另价
        {"input": 1, "output": 4, "schedule": {}},  # 峰谷价
        {"input": 1, "output": 4, "cache_write": 2, "tiers": [{"input": 2, "output": 8, "tier": {"size": 1000}}]},
    ],
)
def test_inexpressible_cost_publishes_entry_without_price(cost: dict) -> None:
    upstream = {"openai": {"models": {"gpt-x": model("GPT X", cost=cost)}}}

    result = build_catalog([upstream], rules(OPENAI), [], {})

    assert "price" not in by_name(result)["gpt-x"]
    assert result.warnings


def test_basellm_wins_and_models_dev_fills_gaps() -> None:
    basellm = {"openai": {"models": {"gpt-a": model("A from basellm")}}}
    models_dev = {"openai": {"models": {"gpt-a": model("A from models.dev"), "gpt-b": model("B")}}}

    entries = by_name(build_catalog([basellm, models_dev], rules(OPENAI), [], {}))

    assert entries["gpt-a"]["display_name"] == "A from basellm"
    assert entries["gpt-a"]["facts"] == {"image_input": True, "structured_output": True, "max_output_tokens": 128000}
    assert entries["gpt-a"]["context_length"] == 400000
    assert set(entries) == {"gpt-a", "gpt-b"}


def test_only_native_text_models_become_entries() -> None:
    upstream = {
        "zhipuai": {
            "models": {
                "glm-5": model("GLM 5"),
                "glm-5-embed": model("Embed", type="embedding"),
                "glm-image": model("Image", modalities={"input": ["text"], "output": ["image"]}),
                "kimi-k3": model("Kimi", canonical_model_id="moonshotai/kimi-k3"),  # 代售的其他厂商模型
                "kimi-k2.5": model("Moonshot Kimi K2.5"),  # 代售但上游没标 canonical_model_id
                "glm-old": model("Old", status="deprecated"),
                "glm-alias": model("GLM Alias (latest)"),
            }
        }
    }

    entries = by_name(build_catalog([upstream], rules({**ZHIPU, "exclude": ["^kimi-"]}), [], {}))

    assert set(entries) == {"glm-5", "glm-old", "glm-alias"}
    assert entries["glm-old"]["discontinued"] is True
    assert entries["glm-alias"]["display_name"] == "GLM Alias"


def test_dated_snapshot_with_same_price_becomes_alias_otherwise_its_own_entry() -> None:
    upstream = {
        "openai": {
            "models": {
                "gpt-a": model("A"),
                "gpt-a-20260301": model("A snapshot"),
                "gpt-b": model("B"),
                "gpt-b-2026-02-01": model("B snapshot", cost={"input": 2, "output": 8}),
            }
        }
    }

    entries = by_name(build_catalog([upstream], rules(OPENAI), [], {}))

    assert set(entries) == {"gpt-a", "gpt-b", "gpt-b-2026-02-01"}
    assert entries["gpt-a"]["aliases"] == ["gpt-a-20260301"]


def test_human_entry_wins_and_absorbs_the_upstream_names() -> None:
    human = {
        "maker": "openai",
        "name": "gpt-a",
        "media_type": "text",
        "display_name": "GPT A (verified)",
        "aliases": ["gpt-a-latest"],
        "facts": {"image_input": True, "structured_output": True},
        "price": {
            "currency": "USD",
            "meters": [{"meter": "uncached_input_tokens", "dims": [], "rows": [{"when": {}, "price": 9.0}]}],
        },
    }
    upstream = {
        "openai": {"models": {"gpt-a-20260301": model("A snapshot"), "gpt-a": model("A")}},
        "relay": {"models": {"openai/GPT.A": model("relay", canonical_model_id="openai/gpt-a")}},
    }

    entries = by_name(build_catalog([upstream], rules(OPENAI), [human], {}))

    assert entries["gpt-a"]["display_name"] == "GPT A (verified)"
    assert entries["gpt-a"]["price"] == human["price"]
    assert entries["gpt-a"]["aliases"] == ["gpt-a-latest", "gpt-a-20260301"]


def test_relay_names_become_aliases_only_when_unambiguous_prefix_forms() -> None:
    upstream = {
        "openai": {"models": {"gpt-a": model("A"), "pro-gpt-a": model("Pro A")}},
        "relay1": {
            "models": {
                "openai-gpt-a": model("ok", canonical_model_id="openai/gpt-a"),
                "gpt-a-fast": model("variant", canonical_model_id="openai/gpt-a"),
                "large": model("generic", canonical_model_id="openai/gpt-a"),
                "gpt-a:free": model("free", canonical_model_id="openai/gpt-a"),
                "acme-pro-gpt-a": model("mislabelled", canonical_model_id="openai/gpt-a"),
            }
        },
        # 同一个名字被两个条目认领，哪边都不给
        "relay2": {"models": {"acme-pro-gpt-a": model("ok", canonical_model_id="openai/pro-gpt-a")}},
    }

    entries = by_name(build_catalog([upstream], rules(OPENAI), [], {}))

    assert entries["gpt-a"]["aliases"] == ["openai-gpt-a"]
    assert "aliases" not in entries["pro-gpt-a"]


def test_listing_maps_upstream_models_with_filters_and_human_priority() -> None:
    upstream = {
        "openai": {
            "models": {
                "gpt-new": model("New"),
                "gpt-old": model("Old", release_date="2025-01-01"),
                "gpt-gone": model("Gone", status="deprecated"),
                "gpt-mini-latest": model("Latest"),
                "gpt-x": model("X"),
                "gpt-image": model("Image", type="image"),
            }
        },
        "openai-plan": {"models": {"GPT.New": model("plan name"), "unknown-model": model("?")}},
    }
    providers = {
        "openai": {
            "upstream": ["openai"],
            "exclude": ["^gpt-x$"],
            "models": [
                {"api_model_name": "gpt-old", "entry": "openai/gpt-old"},
                {"api_model_name": "gpt-new", "entry": "openai/gpt-new", "multiplier": 0.5},
            ],
            "defaults": {"text": "gpt-old"},
        },
        "plan": {"upstream": ["openai-plan"]},
    }

    result = build_catalog([upstream], rules(OPENAI, listing_exclude=["-latest$"]), [], providers)

    listings = result.catalog["builtin_providers"]
    assert listings["openai"] == {
        "models": [
            {"api_model_name": "gpt-old", "entry": "openai/gpt-old"},
            {"api_model_name": "gpt-new", "entry": "openai/gpt-new", "multiplier": 0.5},
        ],
        "defaults": {"text": "gpt-old"},
    }
    # 渠道上的模型名按归一化对应到条目；对应不上的不列入
    assert listings["plan"]["models"] == [{"api_model_name": "GPT.New", "entry": "openai/gpt-new"}]
    assert any("unknown-model" in warning for warning in result.warnings)


def test_missing_upstream_provider_fails_the_build() -> None:
    with pytest.raises(ValueError, match="openai"):
        build_catalog([{}], rules(OPENAI), [], {})
