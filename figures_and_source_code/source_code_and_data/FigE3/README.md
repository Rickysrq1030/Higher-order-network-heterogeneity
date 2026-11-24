# FigE3 · ORH PGG，θ=0 超边规模与合作率

上排为每类玩家的平均参与超边规模组成。下排比较各区间的平均超边规模和合作率。下排沿用源表展示规则，仅绘制 41 个条件中每次均至少有 20 名同类玩家的区间。五列对应相同的 $P_l$。

`data/plot_data.csv` 原样保存 `ORH_publication_figures_revised.rar` 内的 `fig2_a2_bins.csv`，`data/source_reference.pdf` 保存同包的参考图。新旧绘图表按区间键逐行核对，320 行数值一致。来源及校验和见 `data/source.json`。

使用仓库现有环境，运行以下命令重新绘制并同步交付。

```powershell
uv run python 附录图/FigE3/plot.py
```
