# Figure 4

SRH 网络中改变 m 的 MPD 结果。 目录名与论文图号一致。

`data/MPD_SRH_global_results.xlsx` 是本图 m=1、2、3 的数值输入；与 Figure 7 的同名表属于不同参数扫描。

`draw.py` 读取本组 Excel 并绘制子图，`render.py` 组织为 160 × 92.5 mm 的两排五列整图：上排保留合作率随困境强度 δ 变化的三条曲线，下排新增类型内部合作率箱线图；每个绘图区仍为 24.4 × 30 mm。

新增 `data/box_plot_data.csv`、`box_statistics.csv` 原样来自 `SRH_new_figure.rar` 的 `SRH_MPD/m/A1`，来源及字节哈希记录在 `box_source.json`。每箱汇总 41 个不同 δ 条件，不代表同一条件的独立重复；类别按源数据依次为 m=3、2、1。`paper_mpd_boxplots.py` 会逐项核对 984 个散点、24 个箱体统计及其与本目录工作簿中 615 个条件的加权合作率一致性。原有工作簿和曲线数值保持原精度。

上排为 (a)–(e)，下排为 (f)–(j)，每个子图均标注所在列的 $P_l$。每排只在中央显示一次横轴说明，全部横轴刻度数字保留；各排左侧显示相同的 Cooperation rate 纵轴说明。曲线保留既有蓝橙绿配色；箱线图中 Node、Link 均用蓝橙圆点，散点与图例一致，均值用独立黑菱形，同类均值连线。右侧先列 Mean，再在居中的 Player 标题下列 Node 和 Link。全图使用 8 pt Times New Roman、0.6 pt 线宽及 600 dpi 输出。

箱体填充的不透明度为 22%，边框使用不透明的同色 0.6 pt 线条；上下排可见主刻度线统一为 2 pt。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "正文图/Fig4/plot.py"
```
