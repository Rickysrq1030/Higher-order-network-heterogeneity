# Figure A1

SRH 网络超度分布。 目录名与论文图号一致。

`data/` 保存五种网络配置的节点超度 CSV、分布 CSV 和 `network_summary.csv`。

`draw.py` 读取本组数据并绘制上下两组分布图；统一入口默认复用已存 CSV，不重新生成网络。

`render.py` 负责把两组分布图组成完整的 Figure A1，保留 5 mm 的子图行间距；组合成品保存在本组 `figures/` 中。

成品在六个子图上方标出对应的 η 和 m。标记参考 `Fig2_Fig3_FigA1_publication.zip` 中的 `附录图/FigA1/figures/FigA1_publication.pdf`。包内 `附录图/FigA1/data/` 的五份分布表和汇总表与本图数据逐字节一致。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "附录图/FigA1/plot.py"
```
