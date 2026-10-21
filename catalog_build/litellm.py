"""用 LiteLLM 的价格文件比对人工维护的海外媒体条目，只报告差异，不修改数据。

LiteLLM 按渠道建键（如 ``gemini/veo-3.1-generate-preview``），这里只看原厂渠道、键名去掉命名空间后与条目的
官方模型名或模型别名相同的键。LiteLLM 的某个单价不在条目同一计量项的各档单价之中，就报告一行。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping

OVERSEAS_MAKERS = ("google", "openai", "xai")
_NATIVE_PROVIDER = re.compile(r"^(openai|gemini|xai|vertex_ai(-.+)?)$")
# LiteLLM 字段 → (计量项, 换算到目录单价的倍数)
_FIELDS = {
    "output_cost_per_video_per_second": ("output_seconds", 1),
    "output_cost_per_image": ("output_images", 1),
    "input_cost_per_image": ("input_images", 1),
    "input_cost_per_token": ("uncached_input_tokens", 1_000_000),
    "output_cost_per_image_token": ("image_output_tokens", 1_000_000),
    "output_cost_per_audio_token": ("audio_output_tokens", 1_000_000),
}


def _meter_of(field: str) -> tuple[str, int] | None:
    # output_cost_per_second 及按分辨率的变体（output_cost_per_second_720p 等）
    if field == "output_cost_per_second" or field.startswith("output_cost_per_second_"):
        return "output_seconds", 1
    return _FIELDS.get(field)


def compare_litellm(entries: list[Mapping], litellm: Mapping[str, Mapping]) -> Iterator[str]:
    by_name: dict[str, list[tuple[str, Mapping]]] = {}
    for key, item in litellm.items():
        if isinstance(item, Mapping) and _NATIVE_PROVIDER.match(str(item.get("litellm_provider", ""))):
            by_name.setdefault(key.rpartition("/")[2], []).append((key, item))
    for entry in entries:
        if (
            entry["maker"] not in OVERSEAS_MAKERS
            or entry["media_type"] == "text"
            or entry.get("discontinued")
            or "price" not in entry
        ):
            continue
        prices = {meter["meter"]: [row["price"] for row in meter["rows"]] for meter in entry["price"]["meters"]}
        for name in [entry["name"], *entry.get("aliases", [])]:
            for key, item in by_name.get(name, []):
                for field, value in item.items():
                    spec = _meter_of(field)
                    if spec is None or spec[0] not in prices or not isinstance(value, int | float):
                        continue
                    expected = value * spec[1]
                    ours = prices[spec[0]]
                    if not any(math.isclose(expected, price, rel_tol=1e-6, abs_tol=1e-12) for price in ours):
                        listed = ", ".join(f"{price:g}" for price in ours)
                        yield (
                            f"- `{entry['maker']}/{entry['name']}`（{entry['media_type']}）：LiteLLM `{key}` 的 "
                            f"`{field}` 折合 {expected:g}，目录 `{spec[0]}` 的单价为 {listed}"
                        )
