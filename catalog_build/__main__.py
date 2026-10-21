"""``python -m catalog_build``：构建并发布目录数据，或与 LiteLLM 比对海外媒体价格。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arcreel_catalog_core import (
    CATALOG_FILENAME,
    MANIFEST_FILENAME,
    check_catalog_files,
    make_manifest,
    parse_dataset_version,
)

from .build import build_catalog
from .litellm import compare_litellm

ROOT = Path(__file__).resolve().parent.parent
BASELLM_URL = "https://basellm.github.io/llm-metadata/api/all.json"
MODELS_DEV_URL = "https://models.dev/api.json"
LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
USER_AGENT = "arcreel-catalog-build (+https://github.com/ArcReel/arcreel-catalog)"
_VERSION_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class PublishError(Exception):
    pass


def read_json(source: str) -> object:
    """``source`` 是 https 地址或本地路径。"""
    if source.startswith("https://"):
        # 部分数据源拒绝 urllib 默认的 User-Agent
        request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    return json.loads(Path(source).read_bytes())


def load_human_data(data_dir: Path) -> tuple[dict, list[dict], dict]:
    """人工维护的数据：上游规则、按模型厂商分文件的条目、内置供应商配置。"""
    rules = json.loads((data_dir / "upstream.json").read_bytes())
    entries = [
        entry for path in sorted((data_dir / "entries").glob("*.json")) for entry in json.loads(path.read_bytes())
    ]
    providers = json.loads((data_dir / "builtin_providers.json").read_bytes())
    return rules, entries, providers


def render(data: Mapping) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()


def next_version(previous: str | None, now: datetime) -> str:
    """当前 UTC 时间；不晚于上一个数据集版本时取上一个加一秒，保证版本递增。"""
    version = now.astimezone(UTC).replace(microsecond=0)
    if previous is not None:
        version = max(version, parse_dataset_version(previous) + timedelta(seconds=1))
    return version.strftime(_VERSION_FORMAT)


def publish(directory: Path, body: Mapping, now: datetime, *, write: bool = True) -> bool:
    """校验并写出数据文件与清单文件，返回内容是否有变化。

    内容（除数据集版本外）与已发布的相同时沿用原数据集版本，不产生新版本。校验不通过时抛
    ``PublishError``，不写任何文件。
    """
    catalog_path, manifest_path = directory / CATALOG_FILENAME, directory / MANIFEST_FILENAME
    previous = json.loads(catalog_path.read_bytes()) if catalog_path.exists() else None
    previous_version = previous.get("dataset_version") if isinstance(previous, dict) else None
    unchanged = isinstance(previous, dict) and {k: v for k, v in previous.items() if k != "dataset_version"} == body
    version = previous_version if unchanged else next_version(previous_version, now)
    content = render({"dataset_version": version, **body})
    manifest = render(make_manifest(content))
    issues = check_catalog_files(manifest, content)
    if issues:
        raise PublishError("\n".join(str(issue) for issue in issues))
    changed = not unchanged
    if write:
        for path, data in ((catalog_path, content), (manifest_path, manifest)):
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
    return changed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m catalog_build")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="构建目录数据，校验通过且有变化时写出 catalog.json 与 manifest.json")
    build.add_argument("--basellm", default=BASELLM_URL, help="basellm all.json 的地址或本地路径")
    build.add_argument("--models-dev", default=MODELS_DEV_URL, help="models.dev api.json 的地址或本地路径")
    build.add_argument("--data", type=Path, default=ROOT / "data", help="人工维护的数据目录")
    build.add_argument("--out", type=Path, default=ROOT, help="写出目录")
    build.add_argument("--check-only", action="store_true", help="只构建与校验，不写文件")
    compare = commands.add_parser("compare-litellm", help="比对人工条目与 LiteLLM 的海外媒体价格，输出差异")
    compare.add_argument("--litellm", default=LITELLM_URL, help="LiteLLM 价格文件的地址或本地路径")
    compare.add_argument("--data", type=Path, default=ROOT / "data", help="人工维护的数据目录")
    args = parser.parse_args(argv)

    if args.command == "compare-litellm":
        _, entries, _ = load_human_data(args.data)
        for line in compare_litellm(entries, read_json(args.litellm)):
            print(line)
        return 0

    rules, entries, providers = load_human_data(args.data)
    result = build_catalog([read_json(args.basellm), read_json(args.models_dev)], rules, entries, providers)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    try:
        changed = publish(args.out, result.catalog, datetime.now(UTC), write=not args.check_only)
    except PublishError as exc:
        print(exc, file=sys.stderr)
        return 1
    entries_count = len(result.catalog["entries"])
    print(f"{'changed' if changed else 'unchanged'}: {entries_count} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
