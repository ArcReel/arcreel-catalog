"""构建规则：上游转换、人工优先、模型别名与内置供应商清单。全部用离线 fixture。"""

from __future__ import annotations

from datetime import date

import pytest

from catalog_build.build import build_catalog, convert_price

OPENAI = {"provider": "openai", "maker": "openai", "currency": "USD", "canonical": "openai"}
ZHIPU = {"provider": "zhipuai", "maker": "zhipu", "currency": "CNY", "canonical": "zhipuai"}
TODAY = date(2026, 11, 3)  # 构建当天（UTC）


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


def human(name: str, **extra) -> dict:
    """人工维护的文本条目。"""
    return {
        "maker": "openai",
        "name": name,
        "media_type": "text",
        "display_name": name,
        "facts": {"image_input": False, "structured_output": False},
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

    result = build_catalog([upstream], rules(OPENAI), [], {}, today=TODAY)

    assert "price" not in by_name(result)["gpt-x"]
    assert result.warnings


def test_basellm_wins_and_models_dev_fills_gaps() -> None:
    basellm = {"openai": {"models": {"gpt-a": model("A from basellm")}}}
    models_dev = {"openai": {"models": {"gpt-a": model("A from models.dev"), "gpt-b": model("B")}}}

    entries = by_name(build_catalog([basellm, models_dev], rules(OPENAI), [], {}, today=TODAY))

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
                "glm-old": model("Old", status="deprecated"),  # 上游弃用标记只是巡检信号，不置真 discontinued
                "glm-alias": model("GLM Alias (latest)"),
            }
        }
    }

    entries = by_name(build_catalog([upstream], rules({**ZHIPU, "exclude": ["^kimi-"]}), [], {}, today=TODAY))

    assert set(entries) == {"glm-5", "glm-old", "glm-alias"}
    assert "discontinued" not in entries["glm-old"]
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

    entries = by_name(build_catalog([upstream], rules(OPENAI), [], {}, today=TODAY))

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

    entries = by_name(build_catalog([upstream], rules(OPENAI), [human], {}, today=TODAY))

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

    entries = by_name(build_catalog([upstream], rules(OPENAI), [], {}, today=TODAY))

    assert entries["gpt-a"]["aliases"] == ["openai-gpt-a"]
    assert "aliases" not in entries["pro-gpt-a"]


def test_listing_maps_upstream_models_with_filters_and_human_priority() -> None:
    upstream = {
        "openai": {
            "models": {
                "gpt-new": model("New"),
                "gpt-old": model("Old", release_date="2025-01-01"),
                "gpt-deprecated": model("Deprecated", status="deprecated"),
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

    result = build_catalog([upstream], rules(OPENAI, listing_exclude=["-latest$"]), [], providers, today=TODAY)

    listings = result.catalog["builtin_providers"]
    assert listings["openai"] == {
        "models": [
            {"api_model_name": "gpt-old", "entry": "openai/gpt-old"},
            {"api_model_name": "gpt-new", "entry": "openai/gpt-new", "multiplier": 0.5},
            # 上游标了 deprecated、条目没有关停日期：照常列入
            {"api_model_name": "gpt-deprecated", "entry": "openai/gpt-deprecated"},
        ],
        "defaults": {"text": "gpt-old"},
    }
    # 渠道上的模型名按归一化对应到条目；对应不上的不列入
    assert listings["plan"]["models"] == [{"api_model_name": "GPT.New", "entry": "openai/gpt-new"}]
    assert any("unknown-model" in warning for warning in result.warnings)


def test_missing_upstream_provider_fails_the_build() -> None:
    with pytest.raises(ValueError, match="openai"):
        build_catalog([{}], rules(OPENAI), [], {}, today=TODAY)


@pytest.mark.parametrize(
    ("shutdown_date", "discontinued"),
    [("2026-11-02", True), ("2026-11-03", True), ("2026-11-04", None)],
)
def test_entry_is_discontinued_from_its_shutdown_date(shutdown_date: str, discontinued: bool | None) -> None:
    entries = by_name(build_catalog([], rules(), [human("gpt-a", shutdown_date=shutdown_date)], {}, today=TODAY))

    assert entries["gpt-a"].get("discontinued") is discontinued
    assert entries["gpt-a"]["shutdown_date"] == shutdown_date


def test_text_entries_carry_the_upstream_release_date_and_human_dates_win() -> None:
    upstream = {
        "openai": {
            "models": {
                "gpt-a": model("A"),
                "gpt-b": model("B", release_date="2026-02"),  # 不是完整日期，不带入
                "gpt-c": model("C", release_date="2026-04-01"),
                "gpt-d": model("D", release_date="2026-05-01"),
            }
        }
    }
    humans = [human("gpt-c"), human("gpt-d", release_date="2026-05-20")]

    entries = by_name(build_catalog([upstream], rules(OPENAI), humans, {}, today=TODAY))

    assert entries["gpt-a"]["release_date"] == "2026-03-01"
    assert "release_date" not in entries["gpt-b"]
    assert entries["gpt-c"]["release_date"] == "2026-04-01"  # 人工条目没写时取上游
    assert entries["gpt-d"]["release_date"] == "2026-05-20"


def test_retired_models_stay_published_for_90_days_and_upstream_cannot_bring_them_back() -> None:
    upstream = {
        "openai": {
            "models": {name: model(name) for name in ("gpt-retiring", "gpt-recent", "gpt-expired", "gpt-legacy")},
        }
    }
    humans = [
        human("gpt-retiring", shutdown_date="2026-12-01"),
        human("gpt-recent", shutdown_date="2026-08-06"),  # 关停第 89 天
        human("gpt-expired", aliases=["gpt-expired-latest"], shutdown_date="2026-08-05"),  # 关停满 90 天
        human("gpt-legacy", discontinued=True),  # 没有关停日期的历史下线条目
    ]
    providers = {
        "openai": {
            "upstream": ["openai"],
            "models": [
                {"api_model_name": "gpt-expired", "entry": "openai/gpt-expired"},
                {"api_model_name": "gpt-recent-human", "entry": "openai/gpt-recent"},
            ],
        }
    }

    result = build_catalog([upstream], rules(OPENAI), humans, providers, today=TODAY)

    entries = by_name(result)
    assert set(entries) == {"gpt-retiring", "gpt-recent", "gpt-legacy"}
    assert entries["gpt-recent"]["discontinued"] is True
    assert [model["api_model_name"] for model in result.catalog["builtin_providers"]["openai"]["models"]] == [
        "gpt-recent-human",
        "gpt-retiring",
        "gpt-recent",
    ]
    assert not any("gpt-expired" in warning for warning in result.warnings)


def test_split_off_snapshot_is_not_folded_back_into_the_live_entry() -> None:
    # 旧快照与现役条目下线时间不同，人工拆成独立条目；上游的日期快照折叠不能把它并回现役条目
    # 现役型号有人工条目（排在拆出的条目之后）或只有自动条目（gpt-c、gpt-d），拆出的条目以快照为名
    # 或以快照为模型别名（gpt-d-legacy），都要成立
    names = (
        *("gpt-a", "gpt-a-20260101", "gpt-a-20260601", "gpt-b", "gpt-b-20260101"),
        *("gpt-c", "gpt-c-20260101", "gpt-d", "gpt-d-20260101"),
    )
    upstream = {"openai": {"models": {name: model(name) for name in names}}}
    for name in ("gpt-a-20260101", "gpt-c-20260101"):
        upstream["openai"]["models"][name]["release_date"] = "2026-01-01"
    humans = [
        human("gpt-a-20260101", shutdown_date="2026-10-01"),
        human("gpt-a", aliases=["gpt-a-20260601"]),
        human("gpt-b"),
        human("gpt-b-20260101", shutdown_date="2026-08-01"),  # 关停满 90 天
        human("gpt-c-20260101", shutdown_date="2026-10-01"),
        human("gpt-d-legacy", aliases=["gpt-d-20260101"], shutdown_date="2026-10-01"),
    ]
    providers = {"openai": {"upstream": ["openai"]}}

    result = build_catalog([upstream], rules(OPENAI), humans, providers, today=TODAY)

    entries = by_name(result)
    assert set(entries) == {"gpt-a", "gpt-a-20260101", "gpt-b", "gpt-c", "gpt-c-20260101", "gpt-d", "gpt-d-legacy"}
    assert entries["gpt-a"]["aliases"] == ["gpt-a-20260601"]
    for name in ("gpt-b", "gpt-c", "gpt-c-20260101", "gpt-d"):
        assert "aliases" not in entries[name]
    assert entries["gpt-d-legacy"]["aliases"] == ["gpt-d-20260101"]
    assert "discontinued" not in entries["gpt-c"]
    assert "discontinued" not in entries["gpt-d"]
    assert entries["gpt-a-20260101"]["discontinued"] is True
    # 上线日期各取同名上游模型的
    assert entries["gpt-a"]["release_date"] == entries["gpt-c"]["release_date"] == "2026-03-01"
    assert entries["gpt-a-20260101"]["release_date"] == entries["gpt-c-20260101"]["release_date"] == "2026-01-01"
    # 拆出的旧型号与其他退役模型一样，保留期内照常列入，并引用它自己的条目
    listed = {
        model["api_model_name"]: model["entry"] for model in result.catalog["builtin_providers"]["openai"]["models"]
    }
    assert listed == {
        **{name: f"openai/{name}" for name in ("gpt-a", "gpt-a-20260101", "gpt-b", "gpt-c", "gpt-c-20260101", "gpt-d")},
        "gpt-d-20260101": "openai/gpt-d-legacy",
    }
