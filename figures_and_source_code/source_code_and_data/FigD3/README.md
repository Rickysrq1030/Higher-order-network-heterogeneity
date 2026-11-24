# Figure D3

SRH 网络中改变随机连接概率 η 的 MPD 结果。 目录名与论文图号一致。

`data/MPD_SRH_global_results.xlsx` 是新版 4305 点源数据；`data/processed_coop_data.txt` 是本图曲线和相图的直接输入。

`prepare_data.py` 将源表的 `final_avg_fc` 原值导入处理表，不与其他数据混合；`draw.py` 绘制曲线，`phase.py` 绘制相图。`render.py` 将整图组织为 160 × 137 mm 的三排五列：上排为 δ 折线图，中排为 (δ,η) 相图，下排为新增的 η 箱线图。每个绘图区保持 24.4 × 30 mm，原有 615 个曲线值和 4305 个相图值逐项与本图完整处理表及缓存核验，不从箱体统计重建曲线。

新增 `data/box_plot_data.csv`、`box_statistics.csv` 原样取自 `SRH_new_figure.rar` 中的 `SRH_MPD/alpha/A1`，来源和字节哈希记录在 `box_source.json`。源字段 alpha 对应正文 η，b 对应 δ；箱线类别顺序为 η=0.5、0.25、0。每箱汇总 41 个不同 δ 条件，不是同一条件的独立重复。公共 `paper_mpd_boxplots.py` 校验全部 984 个观察值、24 个箱体统计及其与本图工作簿中 615 个切片条件的加权合作率一致性。

各排编号为 (a)–(e)、(f)–(j)、(k)–(o)，每个子图均标注所在列的 $P_l$。三排横轴说明各保留中央一处，所有横轴刻度数字保留；上、中两排使用 Dilemma intensity, δ，下排使用完整的 Random attachment probability, η（无连字符）。各排仅首列显示纵轴说明和数值；箱线图纵轴与上排相同。曲线配色、标记、相图色标和真实数据范围均保留。Node/Link 散点和图例均为蓝橙圆点，Mean 为黑菱形；Mean 独立在上，Player 标题居中。全图使用 8 pt Times New Roman、0.6 pt 线宽及 600 dpi 输出。

箱体填充的不透明度为 22%，边框使用不透明的同色 0.6 pt 线条；三排可见主刻度线统一为 2 pt。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "附录图/FigD3/plot.py"
```
