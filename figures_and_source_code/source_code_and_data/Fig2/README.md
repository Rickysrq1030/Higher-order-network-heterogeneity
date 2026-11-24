# Figure 2

SRH 网络中比较 $m=1,2,3$ 的 PGG 结果。目录名与论文图号一致。

原始输入为 `data/PGG_SRH_global_results.xlsx`，来自 `New_PGG.rar` 中的 `m/old_generator_results/`。本组固定 $g=4$、$N=2000$、$m_h=3$、$\eta=0$；源表中的 `alpha` 对应 $\eta$，`p` 对应 $P_l$。

`prepare_data.py` 校验完整的 $3\times5\times41=615$ 点网格：$m\in\{1,2,3\}$，$P_l\in\{0,0.25,0.5,0.75,1\}$，$r=0,0.05,\ldots,2$，并核对每行 $R/g=r$。缺点、重复坐标、非法参数或合作率会使导入失败。

通过校验后，脚本将 `final_avg_fc` 原值直接写为 `data/processed_coop_data.txt` 的 `Coop_Rate` 列，输出列为 `m,alpha,p,r,Coop_Rate`。浮点数以 `repr` 保留往返精度，不平均、不插值，也不改动原始 Excel。`交付/Fig2数据导入检查.json` 记录来源哈希、完整网格和 615 行五列逐项核对结果。

`draw.py` 读取处理表并绘制五组 $P_l$ 的曲线子图，`render.py` 组织为 160 × 92.5 mm、两行五列的论文整图：上行为原有全群体合作率折线，下行为新增的类型内部合作率箱线图。原折线配色、标度和数据保持不变。

两排各子图均在上方居中标注所在列的 $P_l$（0、0.25、0.5、0.75、1），符号与正文变量表一致，字号为 8 pt；上行为 (a)–(e)，下行为 (f)–(j)。两排横轴说明仅在各排中央保留一处，所有横轴刻度数字保留；说明均用一行文字，分别为 Reduced synergy, r 与 Growth parameter, m；左侧纵轴统一标为 Cooperation rate。箱线图中 Node 和 Link 使用蓝色、橙色圆点，散点与图例一致；Mean 保留黑色菱形。

箱体填充的不透明度为 22%，边框使用不透明的同色 0.6 pt 线条；上下排可见主刻度线统一为 2 pt。

新增输入 `data/box_plot_data.csv` 和 `data/box_statistics.csv` 原样取自 `SRH_new_figure.rar` 的 `SRH_PGG/m/A1/`；`data/box_source.json` 记录压缩包、成员路径和 SHA-256。每个箱体汇总 41 个不同 $r$ 条件下的同一类型合作率，而非重复实验或置信区间；蓝色为 Node，橙色为 Link，黑色菱形为均值。同类均值连线，散点使用原 CSV 的抖动坐标。横轴依源数据为 $m=3,2,1$。公共模块 `paper_boxplots.py` 逐项核对箱体统计、散点及其与本目录 Excel 的来源对应关系；纯 Node/Link 条件只绘制实际存在的类型。

`plot.py` 是统一入口，`figure.json` 记录本组绘图步骤。字号、配色和交付流程使用项目公共模块；本组数据与原图保存在本目录中。

在项目根目录运行：

```powershell
uv run python "正文图/Fig2/plot.py"
```

统一入口先执行 `prepare_data.py`，再绘图。仅重新导入数据可运行：

```powershell
uv run python "正文图/Fig2/prepare_data.py"
```

右侧图例先单独列出 Mean，再在 Player 标题下列 Node 和 Link，Mean 不属于玩家类型分组。
