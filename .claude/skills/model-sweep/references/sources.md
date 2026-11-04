# 官方页面清单

巡检每次逐个读这里的页面。按内置供应商分组，后面是只经自动构建收录文本模型的模型厂商。接口参数与调用方式另见 ArcReel 仓库 `docs/api-docs/providers/<供应商>.md`。

页面是单页应用、抓不到正文时，先试同一站点的 Markdown 版（地址加 `.md`）或 `llms.txt`、`llms-full` 文本。方舟和百炼的公告会按批次增加，从下线公告页进入最新一批。百炼逐批公告的正文由脚本渲染，需要用浏览器渲染才能读到。

## gemini-aistudio

`ai.google.dev/gemini-api/docs/<页面>` 已 301 到 `aistudio.google.com/docs/<页面>`。

- 弃用与关停：https://aistudio.google.com/docs/deprecations
- 模型：https://aistudio.google.com/docs/models
- 定价：https://aistudio.google.com/docs/pricing
- 更新日志：https://aistudio.google.com/docs/changelog

## gemini-vertex

- 模型版本与退役日期：https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions
- 发布说明：https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes
- 定价：https://cloud.google.com/vertex-ai/generative-ai/pricing

## ark

方舟文档的正文可在 `https://ark.volcengine.com/region:cn-beijing/docs/<slug>.md` 取到。

- 模型下线公告：https://ark.volcengine.com/region:cn-beijing/docs/model-deprecation-notice.md
- 模型列表：https://ark.volcengine.com/region:cn-beijing/docs/model-list.md
- 定价：https://ark.volcengine.com/region:cn-beijing/docs/model-pricing.md
- 模型发布公告：https://ark.volcengine.com/region:cn-beijing/docs/model-release-announcement.md

## ark-agent-plan

- 支持的模型：https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-plan-overview.md
- 模型下线公告：https://ark.volcengine.com/region:cn-beijing/docs/agent-plan-personal-model-deprecation-announcement.md
- 全文文本（含下线公告与价格表）：https://ark.volcengine.com/llms-full/agent-coding-plan-subscriptions.txt

## grok

- 模型与价格：https://docs.x.ai/developers/models
- 发布说明：https://docs.x.ai/developers/release-notes
- 退役迁移说明在 `https://docs.x.ai/developers/migration/<批次>` 下，每批一页（例如 https://docs.x.ai/developers/migration/may-15-retirement ），索引页本身是 404，从发布说明里的链接进入
- 新闻页 https://x.ai/news 有 Cloudflare 拦截，抓不到时以模型页与发布说明为准

## openai

- 弃用与关停：https://developers.openai.com/api/docs/deprecations
- 模型：https://developers.openai.com/api/docs/models
- 定价：https://developers.openai.com/api/docs/pricing
- 更新日志：https://developers.openai.com/api/docs/changelog

## dashscope

- 模型下线：https://help.aliyun.com/zh/model-studio/model-depreciation （逐批公告在 https://www.aliyun.com/notice/ 下）
- 模型列表：https://help.aliyun.com/zh/model-studio/getting-started/models
- 定价：https://help.aliyun.com/zh/model-studio/model-pricing

## minimax

- 模型下线说明与历史模型：https://platform.minimax.cn/docs/faq/models
- 模型发布记录：https://platform.minimax.cn/docs/release-notes/models.md
- 接口总览（国际站）：https://platform.minimax.io/docs/api-reference/api-overview
- 定价：https://platform.minimax.cn/docs/pricing/overview.md

## kling

- 文档索引：https://klingai.com/document-api/llms.txt ，各页加 `.md` 取正文
- 接口更新：https://klingai.com/document-api/updates/api.md
- 定价：https://klingai.com/document-api/pricing/base/video.md 、https://klingai.com/document-api/pricing/base/image.md

## vidu

- 文档索引：https://platform.vidu.cn/docs/llms.txt
- 模型对照：https://platform.vidu.cn/docs/overview/model-map.md
- 定价：https://platform.vidu.cn/docs/overview/pricing

## agnes

- 文档索引：https://wiki.agnes-ai.com/llms.txt （GitHub 上的 MODEL_CATALOG.md 已不再更新）
- 定价：https://wiki.agnes-ai.com/en/docs/pricing.md

## 其他模型厂商（文本，自动构建）

这些厂商的模型由上游数据源自动收录，巡检只核实生命周期信号涉及的型号。

- Anthropic：https://platform.claude.com/docs/en/about-claude/model-deprecations
- DeepSeek：https://api-docs.deepseek.com/updates 、https://api-docs.deepseek.com/quick_start/pricing
- Moonshot（Kimi）：https://platform.kimi.com/docs/models.md
- 智谱：https://docs.bigmodel.cn/cn/guide/start/model-overview （没有独立的下线公告页，弃用信息写在各模型页）
