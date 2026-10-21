"""由第三方数据源与人工维护的数据合成目录数据（不含数据集版本）。

本模块是纯函数，不联网、不读写文件：输入是已经读入的上游数据与 ``data/`` 下的人工数据，
输出是 ``{"entries": [...], "builtin_providers": {...}}``。

- 文本模型条目由「模型厂商来源」配置的上游供应商生成：basellm 为主，models.dev 按模型 ID 补缺。
- 人工条目优先：自动条目的官方模型名（或其日期快照名）归一化后与某个人工条目的名字相同，就并入那个人工
  条目，只贡献模型别名。
- 模型别名在构建时生成：价格与能力都与主名相同的日期快照名，以及上游各中转站以
  ``canonical_model_id`` 指向该模型、形如「前缀 + 原名」的命名。生成的别名与其他条目冲突时丢弃。
- 内置供应商清单 = 人工清单 + 按「上游供应商 → 内置供应商」映射、过滤后自动生成的文本模型；
  同一 API 模型名以人工清单为准。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from arcreel_catalog_core import normalize_model_name

# 上游 cost 字段 → 计量项。各项单价都按每百万 token 标价，与 ArcReel 的 token 类计量项一致。
COST_METERS = {
    "input": "uncached_input_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_5m_tokens",
    "output": "output_tokens",
    "input_audio": "audio_input_tokens",
}
# context_over_200k 是上游由 tiers 派生的旧式副本；reasoning 只在与 output 同价时可以表达。
_KNOWN_COST_KEYS = {*COST_METERS, "currency", "tiers", "context_over_200k", "reasoning"}

DATE_SUFFIX = re.compile(r"^(?P<base>.+)-(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{6}|\d{4})$")


@dataclass
class _Candidate:
    """一个自动条目，及它要贡献的模型别名与中转站对应键。"""

    entry: dict
    dated: list[str] = field(default_factory=list)
    canonical: set[str] = field(default_factory=set)


@dataclass
class BuildResult:
    catalog: dict
    warnings: list[str]


def merged_models(upstreams: Iterable[Mapping], provider: str) -> dict[str, dict]:
    """同一上游供应商的模型，先出现的数据源优先，后面的只补缺。"""
    models: dict[str, dict] = {}
    for source in upstreams:
        for model_id, model in source.get(provider, {}).get("models", {}).items():
            models.setdefault(model_id, model)
    return models


def is_text_model(model_id: str, model: Mapping) -> bool:
    """只收原厂直供的纯文本输出模型：带命名空间或变体后缀的 ID、嵌入与实时等类型都不收。"""
    return (
        "/" not in model_id
        and ":" not in model_id
        and model.get("type") is None
        and model.get("modalities", {}).get("output") == ["text"]
    )


def convert_price(cost: Mapping, source: Mapping) -> tuple[dict | None, str | None]:
    """上游 cost → 价目表。无法如实表达时返回 ``(None, 原因)``，条目按未定价发布。

    ``source`` 是模型厂商来源配置：``currency`` 是厂商主站币种；``cache_write_1h_input_multiple`` 给出时，
    按「1 小时缓存写入单价 = 未缓存输入单价 × 倍数」补出上游没有的 1 小时缓存写入价。
    """
    currency = source["currency"]
    actual = cost.get("currency") or "USD"
    if actual != currency:
        return None, f"上游币种 {actual} 不是模型厂商主站币种 {currency}"
    unknown = sorted(set(cost) - _KNOWN_COST_KEYS)
    if unknown:
        return None, f"无法表达的计价字段 {unknown}"
    levels: list[tuple[int, Mapping]] = [(0, cost)]
    for tier in cost.get("tiers", []):
        spec = tier.get("tier", {})
        if spec.get("type", "context") != "context":
            return None, f"无法表达的分档 {spec}"
        levels.append((spec["size"], tier))  # 输入 token 总量超过 size 时落入这一档
    levels.sort(key=lambda level: level[0])
    keys = [key for key in COST_METERS if key == "cache_read" or any(key in level for _, level in levels)]
    meters = []
    for key in keys:
        rows = []
        for bound, level in levels:
            if level.get("reasoning", level["output"]) != level["output"]:
                return None, "推理 token 单价与输出单价不同"
            value = level.get(key)
            if value is None and key == "cache_read":
                # 没有缓存读价时按无折扣计：调用方上报了缓存读 token 也不会整笔未定价
                value = level["input"]
            elif value is None and cost.get(key) == 0:
                value = 0  # 首档免费的项，上游在高档不再重复写 0
            if value is None:
                return None, f"上下文档 {bound} 缺少 {key} 单价"
            rows.append({"when": {"context_tier": bound} if len(levels) > 1 else {}, "price": float(value)})
        meters.append({"meter": COST_METERS[key], "dims": ["context_tier"] if len(levels) > 1 else [], "rows": rows})
    if multiple := source.get("cache_write_1h_input_multiple"):
        rows = [{**row, "price": row["price"] * multiple} for row in meters[0]["rows"]]
        output = [meter["meter"] for meter in meters].index("output_tokens")
        meters.insert(output, {**meters[0], "meter": "cache_write_1h_tokens", "rows": rows})
    return {"currency": currency, "meters": meters}, None


def convert_model(source: Mapping, model_id: str, model: Mapping) -> tuple[dict, str | None]:
    """上游文本模型 → 模型条目。第二项是价格无法表达的原因。"""
    limit = model.get("limit", {})
    facts: dict = {
        "image_input": "image" in model.get("modalities", {}).get("input", []),
        "structured_output": bool(model.get("structured_output")),
    }
    if isinstance(limit.get("output"), int) and limit["output"] > 0:
        facts["max_output_tokens"] = limit["output"]
    entry: dict = {
        "maker": source["maker"],
        "name": model_id,
        "media_type": "text",
        "display_name": model.get("name") or model_id,
    }
    if model.get("status") == "deprecated":
        entry["discontinued"] = True
    if isinstance(limit.get("context"), int) and limit["context"] > 0:
        entry["context_length"] = limit["context"]
    entry["facts"] = facts
    problem = None
    if model.get("cost"):
        price, problem = convert_price(model["cost"], source)
        if price is not None:
            entry["price"] = price
    return entry, problem


def _same_model(a: Mapping, b: Mapping) -> bool:
    return all(a.get(key) == b.get(key) for key in ("facts", "price", "context_length"))


def text_candidates(upstreams: list[Mapping], source: Mapping, warnings: list[str]) -> list[_Candidate]:
    """一个模型厂商来源的自动条目；与主名同价同能力的日期快照并入主名。"""
    provider = source["provider"]
    models = merged_models(upstreams, provider)
    if not models:
        raise ValueError(f"上游数据里没有供应商 {provider}")
    candidates: dict[str, _Candidate] = {}
    unpriced: dict[str, list[str]] = defaultdict(list)
    for model_id, model in models.items():
        canonical = model.get("canonical_model_id")
        # 厂商平台上代售的其他厂商模型（如百炼上的 glm-5）归那家厂商，不在这里建条目
        if not is_text_model(model_id, model) or (canonical and not canonical.startswith(f"{source['canonical']}/")):
            continue
        entry, problem = convert_model(source, model_id, model)
        if problem:
            unpriced[problem].append(model_id)
        keys = {f"{source['canonical']}/{model_id}"}
        if canonical:
            keys.add(canonical)
        candidates[model_id] = _Candidate(entry, canonical=keys)
    for problem, model_ids in unpriced.items():
        warnings.append(f"{provider}: {problem}，按未定价发布：{', '.join(model_ids)}")
    for model_id in list(candidates):
        match = DATE_SUFFIX.match(model_id)
        base = candidates.get(match["base"]) if match else None
        if base is not None and _same_model(base.entry, candidates[model_id].entry):
            folded = candidates.pop(model_id)
            base.dated.append(model_id)
            base.canonical |= folded.canonical
    return list(candidates.values())


def relay_names(upstreams: Iterable[Mapping]) -> dict[str, list[str]]:
    """``canonical_model_id`` → 各上游供应商（含中转站）对这个模型的命名，去掉命名空间。"""
    index: dict[str, list[str]] = defaultdict(list)
    for source in upstreams:
        for provider in source.values():
            for model_id, model in provider.get("models", {}).items():
                canonical = model.get("canonical_model_id")
                # 带 :free 一类后缀的是另一个计价变体，不是同一模型的别名（docs/adr/0105）
                if canonical and ":" not in model_id:
                    index[canonical].append(model_id.rpartition("/")[2])
    return index


def _compact(name: str) -> str:
    return re.sub(r"[^0-9a-z]", "", name.lower())


def _slot(entry: Mapping, name: str) -> tuple[str, str]:
    return entry["media_type"], normalize_model_name(name)


def compose_entries(
    human: list[dict], candidates: list[_Candidate], relays: Mapping[str, list[str]], warnings: list[str]
) -> list[dict]:
    """人工条目优先合成条目，并加上不与其他条目冲突的生成别名。"""
    entries = [dict(entry) for entry in human]
    strong: dict[tuple[str, str], int] = {}  # 官方模型名与人工别名的归一化名 → 条目下标
    for index, entry in enumerate(entries):
        for name in [entry["name"], *entry.get("aliases", [])]:
            strong.setdefault(_slot(entry, name), index)
    generated: dict[int, list[str]] = defaultdict(list)
    human_count = len(entries)
    for candidate in candidates:
        entry = candidate.entry
        names = [entry["name"], *candidate.dated]
        owners = {strong[slot] for name in names if (slot := _slot(entry, name)) in strong}
        covering = [owner for owner in owners if owner < human_count]
        if covering:
            owner = min(covering)
        elif owners:
            warnings.append(f"{entry['maker']}/{entry['name']}: 与已有条目同名，跳过")
            continue
        else:
            owner = len(entries)
            entries.append(entry)
            strong[_slot(entry, entry["name"])] = owner
        own = (_compact(entry["name"]), _compact(entries[owner]["name"]))
        relayed = [
            name
            for key in sorted(candidate.canonical)
            for name in relays.get(key, [])
            # 只收「前缀 + 原名」的命名：带 -fast、-free 等后缀的多是另一个计价变体，泛称（如 large）不可靠
            if _compact(name).endswith(own)
        ]
        generated[owner] += [*names, *relayed]

    claims: dict[tuple[str, str], set[int]] = defaultdict(set)
    for owner, names in generated.items():
        for name in names:
            claims[_slot(entries[owner], name)].add(owner)
    for owner, names in generated.items():
        entry = entries[owner]
        aliases = list(entry.get("aliases", []))
        seen: set[tuple[str, str]] = set()
        for name in names:
            slot = _slot(entry, name)
            # 已是某个条目的名字（含自己），或被多个条目认领：不生成别名
            if slot in strong or slot in seen or len(claims[slot]) > 1:
                continue
            seen.add(slot)
            aliases.append(name)
        if aliases:
            entries[owner] = _ordered({**entry, "aliases": aliases})
    return sorted(entries, key=lambda entry: (entry["maker"], entry["name"], entry["media_type"]))


_FIELD_ORDER = ("maker", "name", "media_type", "display_name", "aliases", "discontinued", "context_length", "facts")


def _ordered(entry: Mapping) -> dict:
    """字段按 ``arcreel_catalog_core.dump_entry`` 的顺序排列。"""
    head = {key: entry[key] for key in _FIELD_ORDER if key in entry}
    return {**head, **{key: value for key, value in entry.items() if key not in head}}


def _text_lookup(entries: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for entry in entries:
        if entry["media_type"] == "text":
            for name in [entry["name"], *entry.get("aliases", [])]:
                lookup.setdefault(normalize_model_name(name), entry)
    return lookup


def compose_listings(
    providers: Mapping[str, Mapping],
    upstreams: list[Mapping],
    entries: list[dict],
    rules: Mapping,
    folded: set[tuple[str, str]],
    warnings: list[str],
) -> dict[str, dict]:
    lookup = _text_lookup(entries)
    patterns = [re.compile(pattern) for pattern in rules.get("listing_exclude", [])]
    min_release = rules["listing_min_release_date"]
    listings: dict[str, dict] = {}
    for provider_id, config in providers.items():
        models = [dict(model) for model in config.get("models", [])]
        taken = {model["api_model_name"] for model in models}
        excludes = patterns + [re.compile(pattern) for pattern in config.get("exclude", [])]
        for upstream in config.get("upstream", []):
            for model_id, model in merged_models(upstreams, upstream).items():
                if (
                    model_id in taken
                    or (upstream, model_id) in folded
                    or not is_text_model(model_id, model)
                    or model.get("status") == "deprecated"
                    or (model.get("release_date") or "") < min_release
                    or any(pattern.search(model_id) for pattern in excludes)
                ):
                    continue
                entry = lookup.get(normalize_model_name(model_id))
                if entry is None:
                    warnings.append(f"{provider_id}: {upstream}/{model_id} 没有对应的条目，不列入清单")
                    continue
                if entry.get("discontinued"):
                    continue
                taken.add(model_id)
                models.append({"api_model_name": model_id, "entry": f"{entry['maker']}/{entry['name']}"})
        listings[provider_id] = {"models": models, "defaults": dict(config.get("defaults", {}))}
    return listings


def build_catalog(
    upstreams: list[Mapping],
    rules: Mapping,
    human_entries: list[dict],
    providers: Mapping[str, Mapping],
) -> BuildResult:
    """``upstreams`` 按优先级排列（basellm 在前、models.dev 在后）。"""
    warnings: list[str] = []
    candidates: list[_Candidate] = []
    folded: set[tuple[str, str]] = set()
    for source in rules["makers"]:
        found = text_candidates(upstreams, source, warnings)
        candidates += found
        folded |= {(source["provider"], dated) for candidate in found for dated in candidate.dated}
    entries = compose_entries(human_entries, candidates, relay_names(upstreams), warnings)
    listings = compose_listings(providers, upstreams, entries, rules, folded, warnings)
    return BuildResult({"entries": entries, "builtin_providers": listings}, warnings)
