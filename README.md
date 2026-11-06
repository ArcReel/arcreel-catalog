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
| `data/entries/<模型厂商>.json` | 人工维护的模型条目：第三方没有的图片、视频、TTS 模型，第三方数据不准确的文本模型，以及要记录关停日期或后继的退役模型 |
| `data/builtin_providers.json` | 内置供应商：对应的上游供应商（`upstream`）、排除规则（`exclude`）、人工清单（`models`）与默认模型（`defaults`） |
| `data/upstream.json` | 生成文本条目的上游供应商与模型厂商、主站币种的对应（`makers`，靠前的优先），清单的过滤规则 |

构建规则：

- `makers` 中每个上游供应商的纯文本模型生成一个条目。币种不是厂商主站币种、或计价方式无法表达（如推理 token 另价、峰谷价）时，条目照常发布，但不带价格。代售的其他厂商模型（`canonical_model_id` 属于别家）不在这里建条目；上游没有标出 `canonical_model_id` 的，用该来源的 `exclude` 按名字排除。
- 人工条目优先：自动条目的名字归一化后与人工条目的官方模型名或模型别名相同时，只保留人工条目，自动条目的名字并入它的模型别名。
- 模型别名：与主名价格、能力都相同的日期快照名（如 `claude-opus-4-5-20251101`），以及各中转站以 `canonical_model_id` 指向该模型、形如「前缀 + 原名」的命名（如 `databricks-gpt-5-4`）。与其他条目冲突的生成别名丢弃。下线时间不同的型号不能互为模型别名：把旧型号写成独立的人工条目，构建不会再把它并入现役条目。
- 上线日期：文本条目取上游的 `release_date`（只收完整的 `YYYY-MM-DD`）。人工条目写了上线日期时以人工的为准，没写时取同名上游模型的。
- 内置供应商清单 = 人工清单 + `upstream` 中满足条件的文本模型：发布日期不早于 `listing_min_release_date`、不匹配 `listing_exclude` 与 `exclude`、名字能对应到条目；对应的条目已下线、但没有关停日期时不列入。同一 API 模型名以人工清单为准；供应商模型倍率与最低应用版本写在人工清单里。默认模型请留在人工清单里，免得上游变化把它移出清单。
- 供应商模型省略 `endpoint` 时补成格式包里该供应商、媒体类型的默认端点；偏离默认的端点写在 `data/builtin_providers.json`。发布入口拒绝缺失端点的数据，端点名、媒体类型和可选范围由格式包严格校验。
- 最低应用版本取手写值、端点起始版本、多端点供应商的声明读取版本中的最高值（按数字版本比较）。`data/upstream.json` 的 `endpoint_version_exemptions` 固定记录首次过渡时已逐条核对的供应商、API 模型名、条目、媒体类型和端点，只豁免声明读取版本；改绑条目或端点后不再豁免。不要把新模型加入这份历史清单。声明读取版本尚为 `None` 时，新加入的多端点模型拒绝构建，待 ArcReel 确定该版本后自动按版本门槛发布，避免旧实例按名字误路由。
- 生命周期按构建当天（UTC）落实：
  - 关停日期不晚于构建当天的条目，发布时 `discontinued` 为真。
  - 关停未满 90 天的条目与清单项照常发布；满 90 天后，条目和引用它的清单项都不再发布，人工数据也一样。过了保留期的人工条目请继续留在 `data/` 里：上游仍有这个模型时，构建靠它认出模型已过保留期，不会重新生成条目和清单项。
  - 上游的 `deprecated` 标记不影响条目和清单。模型的关停日期要写进人工条目。
  - 条目上的关停日期指模型厂商层面的退役，取仍在提供它的渠道里最晚的那天。渠道指模型厂商自营的 API 与本目录的内置供应商，不含转售方。只有某个供应商提前下架时，不改条目，在该供应商的清单里处理（`exclude` 或移出人工清单）。
- 发布内容（除数据集版本外）与 `main` 上的相同时不产生新版本；校验不通过时不发布。

## 模型巡检

厂商的上新、下线与价格变化，由每日一次的模型巡检跟进：新模型、关停日期、后继、上线日期、价格，以及过期人工数据的清理。巡检是 Claude 按 [`.claude/skills/model-sweep/SKILL.md`](.claude/skills/model-sweep/SKILL.md) 执行的无人值守任务。它读 [LiteLLM](https://github.com/BerriAI/litellm)、models.dev、basellm 的信号与各厂商的官方页面，只做有官方来源的改动。产出一个数据 PR，`Check catalog` 通过后合并；需要新调用端点的模型和需要人裁决的事项，在 ArcReel 仓库开 `needs-triage` issue。

定时任务：

- 位置：维护者 claude.ai 账号下的 Claude Code 云端定时任务「arcreel-catalog 每日模型巡检」，每天运行一次，prompt 首行为 `/model-sweep`。
- 源仓库：`ArcReel/arcreel-catalog`，以及用于读取调用通道代码、开 issue 的 `ArcReel/ArcReel`。
- 权限：经云端 GitHub 代理，以维护者身份推送 `model-sweep/` 分支、创建与合并 PR，并在两个仓库开 issue 与评论。代理只支持 REST，所以 skill 里的 GitHub 操作都用 `gh api`。
- 网络：运行环境需要能访问各厂商官方页面，以及 `models.dev`、`basellm.github.io` 与 `raw.githubusercontent.com`。

## 本地运行

需要 [uv](https://docs.astral.sh/uv/)。

```bash
uv run python -m pytest                            # 构建脚本的测试，离线
uv run python -m catalog_build build --check-only  # 抓取上游并完整构建、校验，不写文件
uv run python -m catalog_build build               # 同上，有变化时写出 catalog.json 与 manifest.json
uv run python -m catalog_build signals             # 列出模型巡检的信号（抓取上游与 LiteLLM）
```

`build` 可以用 `--basellm`、`--models-dev` 指向本地文件离线构建。校验器依赖取 ArcReel `main` 上的 `arcreel-catalog-core`；仓库不提交 `uv.lock`，本地需要更新校验器时运行 `uv lock --upgrade-package arcreel-catalog-core`。

---

Official model catalog data for [ArcReel](https://github.com/ArcReel/ArcReel). ArcReel instances sync from this repository, and the factory snapshot bundled with each release is taken from it.
