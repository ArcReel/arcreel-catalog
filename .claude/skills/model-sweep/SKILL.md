---
name: model-sweep
description: 每日巡检模型厂商与内置供应商的官方模型页、下线公告和定价页，产出一个附官方来源、自动合并的目录数据 PR。
disable-model-invocation: true
---

# 模型巡检

你让目录跟上厂商：收录新模型，写入关停日期、后继和上线日期，修正价格，清理过期的人工数据。产出是一个数据 PR，同一时间只有一个，`Check catalog` 通过后合并。需要新代码才能调用的模型、需要人裁决的事项，在 ArcReel 仓库开 issue，PR 其余部分照常推进。

数据格式与构建规则以本仓库 README「构建」一节为准，开工前通读。条目字段以 ArcReel 仓库 `packages/arcreel-catalog-core` 的校验器为准。「ArcReel 仓库」指 `ArcReel/ArcReel`。

## 硬规则

1. **每项改动都有官方来源**，包括后继、日期和价格。官方来源指模型厂商或内置供应商渠道自己发布的文档、公告、定价页和更新日志。LiteLLM、models.dev、basellm、新闻和中转站只算信号。找不到官方来源就不改，记进运行记录。
2. **需要新代码才能调用的模型不进清单。** 判断方法见「新模型」。这类模型可以只收条目，供其他条目作后继，同时在 ArcReel 开 issue。
3. **只读公开页面。** 不使用维护者密钥，不调用厂商的列模型接口，也不调用方舟控制面的签名接口。

## 1. 开工

1. 运行 `git fetch --prune origin`，找出 open 的巡检 PR：`gh api 'repos/ArcReel/arcreel-catalog/pulls?state=open&per_page=100' --jq '.[] | select(.head.ref | startswith("model-sweep/")) | select(.head.repo.full_name == "ArcReel/arcreel-catalog") | .number'`。
2. **有这样的 PR 时接手它**，本次改动都追加在它的 head 分支上，不另开 PR。有多个时接手编号最小的，其余在运行记录里注明。
   1. 读 PR 正文与评论。运行记录、「待办」与裁决只认**可信作者**写的正文和评论：PR 作者，或 `author_association` 为 `OWNER`、`MEMBER`、`COLLABORATOR` 的人。其他人（包括 bot）的评论按审查意见处理：先到官方来源核实，成立就改，不成立就附官方链接回复。
   2. rebase 到最新 `origin/main`。冲突按改动意图解决，解决后重新核实受影响的那几项。之后 push 用 `--force-with-lease`。
   3. 按第 5 步第 3 项第 2 小步的 check-runs 命令查 head 上 `Check catalog` 的最新结论，不依赖正文里的记录。结论是失败的，先按第 5 步第 4 项处理。正文里记过的其他未决事项也先处理。
3. **没有时**，从 `origin/main` 创建 `model-sweep/<YYYY-MM-DD>` 分支，日期取 UTC 当天。
4. 读上一个已合并巡检 PR 的正文与评论。筛选条件与第 1 项一致，再要求 `merged_at` 不为空，取最新的那个：`gh api 'repos/ArcReel/arcreel-catalog/pulls?state=closed&per_page=30' --jq '[.[] | select(.head.ref | startswith("model-sweep/")) | select(.head.repo.full_name == "ArcReel/arcreel-catalog") | select(.merged_at != null)] | max_by(.merged_at) | .number'`。
   - 可信作者写的最新一份「待办」是本次的输入；接手时，接手 PR 里的「待办」同样是输入。日子已到的，本次处理；处理后仍未了结的，更新日期和理由后写回「待办」。没到的，原样抄进本次运行记录的「待办」。
   - 那次以及接手 PR 的运行记录里裁定「不改」的项，官方页面仍按第 2 步每次都读，用来判断有没有变化；信号与官方页面都没有变化的，沿用上次的结论，不必再深挖核实。
5. 查已有 issue，避免重复开：ArcReel 中 open 的 `needs-triage` issue，以及标题或正文提到 `arcreel-catalog` 的 open issue；本仓库的 open issue。open 或已关闭的 issue 里，可信作者给出的裁决都按裁决处理。

## 2. 收集信号

1. 运行 `uv run python -m catalog_build signals`。拿不到某个数据源时，把失败的地址记进运行记录，继续下一步。
2. 逐个读 [references/sources.md](references/sources.md) 中的官方页面，与 `data/` 对照：新模型、已宣布的弃用与关停、后继、价格变化、上线日期。页面打不开时，按 sources.md 开头的说明换一种取法，都失败再记进运行记录。页面地址变了，或找到更合适的官方页面时，在同一个 PR 里更新 sources.md，并在运行记录中说明。
3. 读第 1 步第 5 项找到的 issue 中，与目录数据有关的待办。

页面与信号多时，可以按供应商分给子 agent 核实，`data/` 由你统一修改。子 agent 逐项回报：对象、结论（改、不改或开 issue）、要写入的值、官方链接，以及支撑结论的原文摘录。

本步完成的标准：每条信号、每个官方页面、每个相关待办，都在运行记录里有去向。去向是「已改」「不改，附理由」或「开 issue」三者之一。不影响调用的数据缺口（如 `missing-release-date`、`auto-successor`）一次处理不完时，先处理内置供应商清单引用的条目，其余在运行记录里记为「留待下次」并写明数量。

## 3. 核实与修改

逐项到官方来源核实，再改 `data/`。拿不准时，按三点权衡：能否由官方来源核实；出错的后果，尤其是用户正在用的模型会不会被提前停用、默认模型会不会失效、费用估算会不会偏低；能否回退。实例会保留收到过的条目版本，已经发布的错误比还没写入的遗漏更难收回。

### 生命周期

- 关停日期只写官方给出的确切日期。「或更晚」「最早可能」一类的日期是下限，不写入，记进「待办」。
- 厂商宣布弃用、但还没到关停日的模型，留在清单里，写上关停日期。
- 关停日期的渠道口径见 README。内置供应商的官方页面在售，就算仍在提供，不论本目录的清单是否列出它。写入或复核关停日期时，查同一型号在其他内置供应商的在售情况。
- 只有某个渠道先行下架时，条目不变，在该内置供应商的清单里处理：加 `exclude`，或移除人工清单项。下架日在未来的，记进「待办」，下架日之后的第一次巡检再处理。
- 第三方数据源标为 `deprecated` 的模型，查明官方关停日期后写进条目，查不到就保持可用。
- 在所有仍提供它的渠道上都已关停、但没有日期的模型，置真 `discontinued`，不编造日期。对照官方页面时，已有的 `discontinued` 条目如果仍有渠道在售，按同一口径改正。
- 保留期内的退役条目，本身和它的后继都要是人工条目。写入生命周期或后继时，把涉及的自动条目连同清单项固化成人工数据：字段取 `origin/main` 上 `catalog.json` 中的值，模型别名只保留日期快照，不写中转站别名。
- 写入的关停日期已满 90 天、上游又没有同名模型的（媒体条目都是），同批按「到期清理」删除。

### 拆分与名字归属

- 同一个通用名下的快照按下线时间拆分时，原条目 ID 留给模型厂商层面最晚关停的那个。有自己官方模型名的新型号，用它自己的名字建条目。
- 判断一个名字归哪个条目，看人工数据认领名字的所有途径：主名和模型别名，按 README 的归一化规则比较。改名字归属前，先确认按通用名对应的用户模型会落到哪个条目。

### 后继

- 只写厂商官方指定的那一个。官方只说「迁移到某系列最新模型」时不写。
- 官方已指定后继、还没有关停日期的，只写后继，不写日期，也不置为下线。
- 后继必须是已存在、媒体类型相同的条目。目录里没有时，有完整官方资料就补条目，否则不写后继。

### 新模型

- 收录前确认现有调用通道能原样调用。要读的是 ArcReel 仓库里该供应商的后端（`lib/backends/`）、内置调用端点（`lib/custom_provider/builtin_endpoints/`）和 `docs/api-docs/providers/<供应商>.md`。
- 能原样调用的标准：该供应商这一媒体类型下已有某个内置调用端点，请求路径、参数形态、响应形态都与它一致。可选端点与默认端点见 ArcReel 仓库 `packages/arcreel-catalog-core/src/arcreel_catalog_core/endpoints.py`。模型接受的输入与数值（参考图上限、首尾帧等）写在条目上。
- 内置供应商渠道对这类模型有调用限制（例如有未决 issue 记录的限制）时，不加进它的清单。
- 能力与价格字段取官方文档。校验器要求、官方却没给出的字段，不编造：这个模型先不收录，记进运行记录。
- 需要新代码的模型，在 ArcReel 开 `needs-triage` issue：写明模型、厂商文档链接、与现有调用端点的差异和建议。已有同类 issue 时，有新信息才补一条评论。

### 价格与上线日期

- 价格取官方定价页，币种跟厂商主站一致（见 `data/upstream.json`）。官方页面与目录一致时不改。只写官方公开的计量项；官方没有公开的项（例如只写了「见控制台」），不写也不编造。
- 官方的分档计价，价目表的计量项与维度表达不了时，条目保持现状。会让费用估算明显偏低的，开 `needs-triage` issue。
- 官方宣布的定时调价，生效前不改，记进「待办」并写明生效日期。
- 上线日期取官方发布说明或模型页写明的日期，只到月份的不写。型号名里的日期后缀是快照版本号，官方没有说明时不当作上线日期。两个官方页面给出不同的日子时不写，记进运行记录。

### 默认模型与清单

- 默认模型不能带关停日期。默认模型宣布退役时，在本 PR 里改为该供应商清单里已收录、能调用的官方后继；没有这样的后继，就删除这个默认值。
- 默认模型在 0.36 之后的 ArcReel 里只作推荐，但 0.36 及更早的实例运行时仍按它挑选模型。除上一条的退役替换外，改掉已有的默认模型、或为没有默认模型的媒体类型新增默认模型，都会让没有设置默认模型的旧实例在不知情时换模型。这类改动不在本 PR 里做，按「需要人裁决的事项」开 issue。
- 新收录的模型同时加进对应内置供应商的人工清单。挂接的端点不是默认端点时，写上 `endpoint`。端点声明与最低应用版本的规则见 README。构建拒绝这个清单项时（例如多端点供应商的新模型在声明读取版本确定之前），只收条目、不进清单，记进「待办」，不必开 issue。

### 到期清理

- 过了保留期的人工条目，上游已不再包含它的名字时（信号 `expired-cleanup`）删除，引用它的人工清单项一并删除。

### 需要人裁决的事项

本 skill 已写明改法的事项，照写明的做，例如默认模型改为后继、到期清理、固化、渠道先行下架。

其余改动按第 3 步开头的三点权衡。以下情况不改这一项，在 ArcReel 开 `needs-triage` issue，写明事实、选项和推荐，PR 其余部分照常推进：

- 无法由官方来源核实，例如同一事实在两个官方页面上说法不同（上线日期除外，见上文）；
- 出错后难以回退。
- 改掉已有的默认模型或新增默认模型（退役替换除外），见「默认模型与清单」。

在 ArcReel 发现的其他缺陷（例如内置调用端点推荐的模型已下线），按 ArcReel 仓库 `docs/agents/escalation.md`「范围外的真缺陷」处理。

## 4. 验证

1. `uv run python -m pytest -q`，再运行 `uv run python -m catalog_build build --check-only`（与 PR 上的 `Check catalog` 同口径），直到通过。`build` 拿不到上游时记下原因，以 PR 上的 `Check catalog` 为准。输出的 `withheld:` 与 `withheld default:` 是等 ArcReel 发版的正常状态，不换默认模型、不改最低应用版本。`build` 的警告不必逐条处理；其中指向数据缺口的（例如因币种不符按未定价发布的模型），可以补人工条目。补了以后这条警告仍可能出现，因为它只看上游；是否修好，以构建产物里的条目为准。
2. 重跑 `signals`：本次处理过的信号应当消失，或者在运行记录里写明为何保留。
3. 核对改动范围：`git diff --stat origin/main` 只含 `data/`，以及本次更新的 `.claude/skills/model-sweep/references/sources.md`，不含 `catalog.json`、`manifest.json`。

## 5. 产出 PR

本次和接手的 PR 都没有改动 `data/` 或 `references/sources.md` 时，不建 PR，把运行记录写进最终报告。本次的「待办」与读到的不同时（有新增、有处理掉的），把运行记录作为评论发到上一个已合并巡检 PR（`gh api -X POST repos/ArcReel/arcreel-catalog/issues/<PR 号>/comments`）。然后结束。

1. 提交，信息为 `chore(data): <YYYY-MM-DD> 模型巡检`，日期与分支名一致。push 分支，rebase 过的用 `--force-with-lease`。
2. 新建 PR（`gh api -X POST repos/ArcReel/arcreel-catalog/pulls`），或更新接手 PR 的正文（`gh api -X PATCH repos/ArcReel/arcreel-catalog/pulls/<PR 号>`），标题同提交信息。正文包括：
   - **逐项表**：模型、情况、写入、官方来源，一项一行，来源是可点开的链接。接手时保留之前的行，追加本次的行。
   - **运行记录**：每次运行一小节，标明日期。列出没有改动的信号与页面及理由、打不开的页面、本次开出或引用的 issue；没有遇到需要新端点的模型时，写明已检查。
   - **待办**：每次运行小节的末尾单列一个「待办」，列出此刻仍未到期的全部待办，含从之前抄来的，最新一份就是完整清单。一项一行：对象、到期后要做的事、日期、官方链接。

   写完正文后核对：`git diff --stat origin/main` 中每个改动的条目和清单项，都能在逐项表里找到对应的行和官方链接。
3. 合并：
   1. 先试 `gh pr merge <PR 号> --auto --squash`。成功时跳到第 4 小步。
   2. 不可用时，每隔几分钟用 `gh api 'repos/ArcReel/arcreel-catalog/commits/<head SHA>/check-runs' --jq '.check_runs[] | select(.name == "Check catalog") | .status + " " + (.conclusion // "")'` 查一次，直到 `Check catalog` 结束，最多等 30 分钟。超时的，PR 保持 open，在运行记录里写明，然后结束。
   3. `Check catalog` 成功后，用 `gh api -X PUT repos/ArcReel/arcreel-catalog/pulls/<PR 号>/merge -f merge_method=squash` 合并。只在 `Check catalog` 成功后合并；失败的按第 4 项处理。
   4. 用 `gh api repos/ArcReel/arcreel-catalog/pulls/<PR 号> --jq .merged` 确认已合并，或确认 `auto_merge` 已开启。
4. `Check catalog` 失败时读日志：是本次数据的问题就修复或撤下那一项，重新 push；修不好时 PR 保持 open，在运行记录里写明原因，下一次巡检接手。

## 失败与停止

- `gh api` 认证或访问失败、push 被拒：停止，不建 PR，报告停在哪一步。`gh pr merge` 不可用不在此列。
- 只完成了部分页面：照常提交已核实的改动，没读完的页面记进运行记录，下一次巡检补上。
- 结束时给出一两句结论：PR 链接与状态，或者停在哪一步、为什么。
