# Figure C1

URH 网络上的 PGG 结果。 目录名与论文图号一致。

`data/processed_coop_data.txt` 是本图曲线和相图的直接数值输入。

`draw.py` 绘制曲线子图，`phase.py` 绘制相图子图。`render.py` 组织为论文整图，三张相图共用一个居中的横轴标题，各子图保留数值刻度。

上排从左到右标记 (g = 3, 4, 5)，每个标记同时说明该列相图的超边规模。标记参考 `Fig2_Fig3_FigA1_publication.zip` 中的 `正文图/Fig2/figures/Fig2_publication.pdf`。包内 `正文图/Fig2/data/processed_coop_data.txt` 与本图数据逐字节一致。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "附录图/FigC1/plot.py"
```
