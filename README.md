# arcreel-catalog

[ArcReel](https://github.com/ArcReel/ArcReel) 的官方模型目录数据：模型条目、价格与能力。ArcReel 实例从这里自动同步，随版本打包的出厂快照也取自这里。

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 清单：数据集版本与数据文件哈希 |
| `catalog.json` | 目录数据 |

数据由定时构建生成：文本模型取自公开的第三方数据源，再叠加人工维护的数据，人工数据优先。构建结果通过 ArcReel 的目录数据校验器（`arcreel-catalog-core`）后，由 bot 直接提交到 `main`。

---

Official model catalog data for [ArcReel](https://github.com/ArcReel/ArcReel). ArcReel instances sync from this repository, and the factory snapshot bundled with each release is taken from it.
