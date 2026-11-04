"""模型巡检的信号：第三方数据与目录不一致、或目录数据有缺口的地方。

信号只是线索，不是来源：巡检逐条到官方页面核实后才改数据。本模块是纯函数，不联网、不读写文件。

LiteLLM 按渠道建键（如 ``gemini/veo-3.1-generate-preview``），这里只看原厂渠道，键名去掉命名空间后按归一化名
对应到同一模型厂商的条目。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from arcreel_catalog_core import normalize_model_name

from .build import DATE_SUFFIX, RETENTION, build_catalog, is_text_model, merged_models, parse_date

# 信号类别 → 说明，按输出顺序排列
KINDS = {
    "upstream-deprecated": "第三方数据源标为 deprecated、条目没有关停日期的文本模型",
    "litellm-deprecation": "LiteLLM 的 deprecation_date 与条目的关停日期不同",
    "shutdown-soon": "30 天内关停：复核日期与后继，以及默认模型是否受影响",
    "unlisted-media": "LiteLLM 原厂渠道有、目录没有条目的媒体模型",
    "litellm-price": "LiteLLM 原厂渠道的单价不在条目同一计量项的各档单价之中",
    "missing-release-date": "人工条目没有上线日期",
    "auto-successor": "后继指向自动条目：上游删掉它时，整份数据会被校验器拒收",
    "expired-cleanup": "过了保留期、上游也不再有同名模型的人工条目，可以从 data/ 删除",
}
SHUTDOWN_SOON = timedelta(days=30)
# 只比价格的模型厂商：LiteLLM 原厂渠道与目录同为美元计价
PRICE_MAKERS = ("google", "openai", "xai")
# LiteLLM 原厂渠道 → 模型厂商；带后缀的 vertex_ai 渠道（vertex_ai-video-models 等）也归 google
_NATIVE = {
    "openai": "openai",
    "gemini": "google",
    "vertex_ai": "google",
    "xai": "xai",
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "dashscope": "alibaba",
    "volcengine": "bytedance",
    "minimax": "minimax",
    "moonshot": "moonshot",
}
_MEDIA_MODES = {
    "image_generation": "image",
    "image_edit": "image",
    "video_generation": "video",
    "audio_speech": "audio",
}
# LiteLLM 字段 → (计量项, 换算到目录单价的倍数)
_PRICE_FIELDS = {
    "output_cost_per_video_per_second": ("output_seconds", 1),
    "output_cost_per_image": ("output_images", 1),
    "input_cost_per_image": ("input_images", 1),
    "input_cost_per_token": ("uncached_input_tokens", 1_000_000),
    "output_cost_per_image_token": ("image_output_tokens", 1_000_000),
    "output_cost_per_audio_token": ("audio_output_tokens", 1_000_000),
}


@dataclass(frozen=True)
class Signal:
    kind: str
    subject: str  # 条目引用 maker/name；目录没有条目时是模型厂商加 LiteLLM 的模型名
    detail: str


def _ref(entry: Mapping) -> str:
    return f"{entry['maker']}/{entry['name']}"


def _names(entry: Mapping) -> list[str]:
    return [entry["name"], *entry.get("aliases", [])]


def _native_maker(item: object) -> str | None:
    if not isinstance(item, Mapping):
        return None
    provider = str(item.get("litellm_provider", ""))
    return _NATIVE.get("vertex_ai" if provider.startswith("vertex_ai") else provider)


def _price_meter(field: str) -> tuple[str, int] | None:
    # output_cost_per_second 及按分辨率的变体（output_cost_per_second_720p 等）
    if field == "output_cost_per_second" or field.startswith("output_cost_per_second_"):
        return "output_seconds", 1
    return _PRICE_FIELDS.get(field)


def _litellm_prices(human: Iterable[Mapping], litellm: Mapping) -> Iterable[Signal]:
    by_name: dict[str, list[tuple[str, Mapping]]] = {}
    for key, item in litellm.items():
        if _native_maker(item) is not None:
            by_name.setdefault(key.rpartition("/")[2], []).append((key, item))
    for entry in human:
        if (
            entry["maker"] not in PRICE_MAKERS
            or entry["media_type"] == "text"
            or entry.get("discontinued")
            or "price" not in entry
        ):
            continue
        prices = {meter["meter"]: [row["price"] for row in meter["rows"]] for meter in entry["price"]["meters"]}
        for name in _names(entry):
            for key, item in by_name.get(name, []):
                for field, value in item.items():
                    spec = _price_meter(field)
                    if spec is None or spec[0] not in prices or not isinstance(value, int | float):
                        continue
                    expected = value * spec[1]
                    ours = prices[spec[0]]
                    if not any(math.isclose(expected, price, rel_tol=1e-6, abs_tol=1e-12) for price in ours):
                        listed = ", ".join(f"{price:g}" for price in ours)
                        yield Signal(
                            "litellm-price",
                            _ref(entry),
                            f"LiteLLM `{key}` 的 `{field}` 折合 {expected:g}，`{spec[0]}` 的单价为 {listed}",
                        )


def collect_signals(
    upstreams: list[Mapping],
    rules: Mapping,
    human_entries: list[dict],
    providers: Mapping[str, Mapping],
    litellm: Mapping,
    *,
    today: date,
) -> list[Signal]:
    """前四个参数与 ``build_catalog`` 的相同；``litellm`` 是 LiteLLM 的价格文件，``today`` 是 UTC 当天。"""
    entries = build_catalog(upstreams, rules, human_entries, providers, today=today).catalog["entries"]
    by_name: dict[tuple[str, str], dict] = {}
    for entry in entries:
        for name in _names(entry):
            by_name.setdefault((entry["maker"], normalize_model_name(name)), entry)
    human_refs = {_ref(entry) for entry in human_entries}
    found: dict[tuple[str, str], list[str]] = {}

    def add(kind: str, subject: str, detail: str) -> None:
        details = found.setdefault((kind, subject), [])
        if detail not in details:
            details.append(detail)

    # 第三方数据源的 deprecated 标记：看模型厂商来源，以及内置供应商清单的上游里没被该供应商排除的模型
    maker_sources = {source["provider"] for source in rules["makers"]}
    listing_excludes: dict[str, list[list[str]]] = {}
    for config in providers.values():
        for upstream in config.get("upstream", []):
            listing_excludes.setdefault(upstream, []).append(config.get("exclude", []))
    upstream_providers = sorted(maker_sources | set(listing_excludes))
    for provider in upstream_providers:
        for model_id, model in merged_models(upstreams, provider).items():
            if model.get("status") != "deprecated" or not is_text_model(model_id, model):
                continue
            if provider not in maker_sources and all(
                any(re.search(pattern, model_id) for pattern in excludes) for excludes in listing_excludes[provider]
            ):
                continue
            normalized = normalize_model_name(model_id)
            for entry in entries:
                if (
                    entry["media_type"] == "text"
                    and not entry.get("shutdown_date")
                    and not entry.get("discontinued")
                    and normalized in {normalize_model_name(name) for name in _names(entry)}
                ):
                    add("upstream-deprecated", _ref(entry), f"`{provider}/{model_id}`")

    for key, item in litellm.items():
        maker = _native_maker(item)
        if maker is None:
            continue
        name = key.rpartition("/")[2]
        deprecation = item.get("deprecation_date")
        entry = by_name.get((maker, normalize_model_name(name)))
        if entry is not None:
            if isinstance(deprecation, str) and entry.get("shutdown_date") != deprecation:
                detail = f"`{key}`：{deprecation}（条目：{entry.get('shutdown_date', '无')}）"
                add("litellm-deprecation", _ref(entry), detail)
            continue
        media = _MEDIA_MODES.get(str(item.get("mode")))
        retired = parse_date(deprecation)
        snapshot = DATE_SUFFIX.match(name)
        if (
            media is None
            or (retired is not None and retired <= today)
            # 已收录型号的日期快照
            or (snapshot is not None and (maker, normalize_model_name(snapshot["base"])) in by_name)
        ):
            continue
        add("unlisted-media", f"{maker}/{name}", f"`{key}`（{media}）")

    # 按发布的条目比价：已下线和过了保留期的不比
    for signal in _litellm_prices([entry for entry in entries if _ref(entry) in human_refs], litellm):
        add(signal.kind, signal.subject, signal.detail)

    for entry in entries:
        shutdown = parse_date(entry.get("shutdown_date"))
        if shutdown is not None and today < shutdown <= today + SHUTDOWN_SOON:
            add("shutdown-soon", _ref(entry), entry["shutdown_date"])
        if _ref(entry) in human_refs and not entry.get("release_date") and not entry.get("discontinued"):
            add("missing-release-date", _ref(entry), entry["media_type"])
        if entry.get("successor") and entry["successor"] not in human_refs:
            add("auto-successor", _ref(entry), f"后继 `{entry['successor']}`")

    # 上游仍有同名模型时，人工条目要留在 data/ 里，构建靠它拦住上游、不重新生成条目
    upstream_names = {
        normalize_model_name(model_id)
        for provider in upstream_providers
        for model_id in merged_models(upstreams, provider)
    }
    for entry in human_entries:
        shutdown = parse_date(entry.get("shutdown_date"))
        if shutdown is None or today - shutdown < RETENTION:
            continue
        if not upstream_names & {normalize_model_name(name) for name in _names(entry)}:
            add("expired-cleanup", _ref(entry), f"关停于 {entry['shutdown_date']}")

    order = list(KINDS)
    return [
        Signal(kind, subject, "；".join(details))
        for (kind, subject), details in sorted(found.items(), key=lambda item: (order.index(item[0][0]), item[0][1]))
    ]


def render_signals(signals: list[Signal]) -> str:
    """按类别输出 Markdown，没有信号的类别也列出标题，表示已检查。"""
    lines: list[str] = []
    for kind, description in KINDS.items():
        group = [signal for signal in signals if signal.kind == kind]
        lines += [f"## {kind}（{len(group)}）", "", description, ""]
        lines += [f"- `{signal.subject}`：{signal.detail}" for signal in group]
        if group:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
