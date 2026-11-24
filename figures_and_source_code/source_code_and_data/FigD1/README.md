# Figure D1

SRH 网络中改变随机连接概率 η 的 PGG 结果。 目录名与论文图号一致。

`data/PGG_SRH_global_results.xlsx` 是当前完整原始数据，来自 `New_PGG.rar` 中的 alpha 扫描。`prepare_data.py` 默认只读取这份本图工作簿，校验固定参数 G=4、N=2000、m=1、mh=3，以及 5 个 p × 21 个 alpha × 41 个 r 的 4305 个唯一网格点，并核对 R/G=r。缺点、重复坐标、非法数值或缺失来源路径会中止导入；不会回用旧扫描。

`final_avg_fc` 直接映射为 `Coop_Rate`，不与旧数据混合，也不再平均或补值。导入会同时替换 `data/p0.txt`、`p0.25.txt`、`p0.5.txt`、`p0.75.txt`、`p1.txt` 和 `data/processed_coop_data.txt`；这些 TXT 是从同一工作簿生成的处理结果。数值使用 Python `repr(float)` 无损表示，逐个浮点值及五份扫描与总表的一致性均在 `交付/FigD1数据聚合检查.json` 中记录。

`phase.py` 绘制相图子图；`render.py` 将论文整图组织为三排：上排保留原曲线，中排保留原相图，下排显示点策略与边策略的合作率箱线图。成品为 160 × 137 mm，每排五个 24.4 × 30 mm 绘图区；原有曲线和相图的数值、颜色及坐标范围保持不变。

三排各子图均在上方居中标注所在列的 $P_l$（0、0.25、0.5、0.75、1），符号与正文变量表一致，字号为 8 pt；各排编号依次为 (a)–(e)、(f)–(j)、(k)–(o)。三排横轴说明均只在各排中央保留一处，所有子图的刻度数字保留；上两排说明为 Reduced synergy, r，箱线图横轴使用单行完整名称 Random attachment probability, η；箱线图左纵轴沿用上排 Cooperation rate。Node 和 Link 的散点及图例分别用蓝色和橙色圆点，Mean 保留黑色菱形。

箱体填充的不透明度为 22%，边框使用不透明的同色 0.6 pt 线条；三排可见主刻度线统一为 2 pt。

下排读取本目录 `data/box_plot_data.csv`、`box_statistics.csv`，来源记录在 `box_source.json`，对应 `SRH_new_figure.rar` 中的 `SRH_PGG/alpha/A1`。三类依次为 η=0.5、0.25、0；每个箱体汇总 41 个不同 r 条件下、该类实际个体的末期平均合作率，并非同一条件下的独立重复。蓝色为 Node，橙色为 Link，黑色菱形为跨 r 均值。纯点或纯边群体只绘制实际存在的类型。公共 `paper_boxplots.py` 会核验全部 984 个观察值、24 个箱体统计及其与本图工作簿中 615 个条件的加权合作率一致性；箱体、散点和均值连线的实际数值检查写入 `交付/FigD1箱线图数据检查.json`。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "附录图/FigD1/plot.py"
```

仅更新处理数据，或显式指定同结构的新工作簿：

```powershell
uv run python "附录图/FigD1/prepare_data.py"
uv run python "附录图/FigD1/prepare_data.py" --input "C:/path/to/PGG_SRH_global_results.xlsx"
```

需要独立导入传统五份 TXT 扫描时，必须显式选择来源目录：

```powershell
uv run python "附录图/FigD1/prepare_data.py" --scan-dir "C:/path/to/scans"
```
