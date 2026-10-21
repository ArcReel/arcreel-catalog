# arcreel-catalog

[ArcReel](https://github.com/ArcReel/ArcReel) 的官方模型目录数据：模型条目、价格与能力。ArcReel 实例从这里自动同步，随版本打包的出厂快照也取自这里。

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 清单：数据集版本与数据文件哈希 |
| `catalog.json` | 目录数据 |

数据由定时构建生成：文本模型取自公开的第三方数据源，再叠加人工维护的数据，人工数据优先。构建结果通过 ArcReel 的目录数据校验器（`arcreel-catalog-core`）后，由 bot 直接提交到 `main`。两个发布文件不要手改，修改 `data/` 即可。

格式定义与校验规则见 ArcReel 仓库的 [`packages/arcreel-catalog-core`](https://github.com/ArcReel/ArcReel/tree/main/packages/arcreel-catalog-core)。

## 构建

| 来源 | 用途 |
| --- | --- |
| [basellm](https://github.com/basellm/llm-metadata) | 文本模型的主要来源 |
| [models.dev](https://models.dev) | basellm 没有的文本模型；各中转站的模型命名 |
| `data/entries/<模型厂商>.json` | 人工维护的模型条目：第三方没有的图片、视频、TTS 模型，以及第三方数据不准确的文本模型 |
| `data/builtin_providers.json` | 内置供应商：对应的上游供应商（`upstream`）、排除规则（`exclude`）、人工清单（`models`）与默认模型（`defaults`） |
| `data/upstream.json` | 生成文本条目的上游供应商与模型厂商、主站币种的对应（`makers`，靠前的优先），清单的过滤规则 |

构建规则：

- `makers` 中每个上游供应商的纯文本模型生成一个条目。币种不是厂商主站币种、或计价方式无法表达（如推理 token 另价、峰谷价）时，条目照常发布，但不带价格。代售的其他厂商模型（`canonical_model_id` 属于别家）不在这里建条目；上游没有标出 `canonical_model_id` 的，用该来源的 `exclude` 按名字排除。
- 人工条目优先：自动条目的名字归一化后与人工条目的官方模型名或模型别名相同时，只保留人工条目，自动条目的名字并入它的模型别名。
- 模型别名：与主名价格、能力都相同的日期快照名（如 `claude-opus-4-5-20251101`），以及各中转站以 `canonical_model_id` 指向该模型、形如「前缀 + 原名」的命名（如 `databricks-gpt-5-4`）。与其他条目冲突的生成别名丢弃。
- 内置供应商清单 = 人工清单 + `upstream` 中满足条件的文本模型：未弃用、发布日期不早于 `listing_min_release_date`、不匹配 `listing_exclude` 与 `exclude`、名字能对应到未下架的条目。同一 API 模型名以人工清单为准；供应商模型倍率与最低应用版本写在人工清单里。默认模型请留在人工清单里，免得上游变化把它移出清单。
- 发布内容（除数据集版本外）与 `main` 上的相同时不产生新版本；校验不通过时不发布。

每周还会用 [LiteLLM](https://github.com/BerriAI/litellm) 的价格文件比对 Google、OpenAI、xAI 的人工媒体条目，有差异时开 issue 提醒，不直接修改数据。

## 本地运行

需要 [uv](https://docs.astral.sh/uv/)。

```bash
uv run python -m pytest                            # 构建脚本的测试，离线
uv run python -m catalog_build build --check-only  # 抓取上游并完整构建、校验，不写文件
uv run python -m catalog_build build               # 同上，有变化时写出 catalog.json 与 manifest.json
uv run python -m catalog_build compare-litellm     # 输出与 LiteLLM 的价格差异
```

`build` 可以用 `--basellm`、`--models-dev` 指向本地文件离线构建。校验器依赖取 ArcReel `main` 上的 `arcreel-catalog-core`；仓库不提交 `uv.lock`，本地需要更新校验器时运行 `uv lock --upgrade-package arcreel-catalog-core`。

---

Official model catalog data for [ArcReel](https://github.com/ArcReel/ArcReel). ArcReel instances sync from this repository, and the factory snapshot bundled with each release is taken from it.
