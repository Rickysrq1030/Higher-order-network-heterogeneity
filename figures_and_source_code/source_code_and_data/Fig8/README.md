# Figure 8

ORH 网络上的 MPD 结果。 目录名与论文图号一致。

`data/fig1_global.csv`、`data/fig1_a1_points.csv` 和 `data/fig1_a1_boxes.csv` 分别提供全群体折线、玩家类型散点和箱体统计，均原样取自 `ORH_publication_figures_revised.rar` 的 MPD 分组。同包参考图保存在 `data/source_reference.pdf`，来源与 SHA-256 见 `data/box_source.json`。

`draw.py` 读取本组全群体 CSV 并绘制子图，`render.py` 组织为论文整图。

整图为 160 × 102.5 mm、两行五列：上排保留五种阶数分布的 MPD 折线，下排添加对应玩家类型合作率箱线图。每个绘图区为 24.4 × 30 mm；曲线的原有数值、颜色、标记和坐标范围保持不变。

横轴刻度数字全部保留，每排仅在中央保留一处横轴说明；各排仅最左幅保留纵轴说明和数值。上排使用 Dilemma intensity, δ，下排使用 Hyperedge order distribution。上排图号为 (a)–(e)，下排为 (f)–(j)；每个子图均标注所在列的 P_l。字号均为 8 pt Times New Roman，PNG 为 600 dpi。

上方完整分布名称图例按原顺序标注 D1–D5，下排分类刻度使用相同编号：D1 = Strongly convex，D2 = Convex，D3 = Flat，D4 = Concave，D5 = Strongly concave。编号只用于清楚映射分类，不改变原始类别顺序。

箱体的 1640 个散点与 40 组统计均与先前数据逐项相同。全群体表覆盖原 Excel 的全部 1025 个条件，数值最大绝对差约为 5×10⁻⁹。公共 `paper_mpd_boxplots.py` 核对每个条件的模拟文件、玩家人数及加权合作率。每个箱体汇总 41 个不同 δ 条件。Node、Link 散点及图例均使用蓝色、橙色圆点。Mean 用黑色菱形，放在居中的 Player 标题上方。检查报告为 `交付/Fig8共享轴数据检查.json` 和 `交付/Fig8共享轴布局检查.json`。

箱体填充的不透明度为 22%，边框使用不透明的同色 0.6 pt 线条；上下排可见主刻度线统一为 2 pt。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "正文图/Fig8/plot.py"
```
