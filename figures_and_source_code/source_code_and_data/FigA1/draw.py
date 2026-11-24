# -*- coding: utf-8 -*-
"""
SRH 超图生成与节点超度散点图。

依赖：pip install numpy matplotlib
运行：python draw.py；复用本目录 data 中的网络数据：python draw.py --reuse-data

两组实验：
  1. alpha = 0, 0.5, 1.0；m = 1, mh = 3, n = 10000, g = 4。
  2. m = 1, 2, 3；alpha = 0, mh = 3, n = 10000, g = 4。

绘图与参考图片一致：横坐标 log10(k)，纵坐标 log10(P(k))。
P(k) = 超度恰好为 k 的节点数 / n；每个点代表一个出现过的超度值。
超度 k 是节点参与的超边数，不是普通邻居数。

生成规则与 mpdsrhm.py / pgg_srh.py 一致。只生成网络，不运行博弈。
alpha=0 表示纯偏好连接，alpha=1 表示纯均匀随机连接。
特别注意：偏好权重为 k_counts + 未曾被选中时的 3，非直接使用超度。
每个参数组合只生成一张网络，未作多次平均、分箱或幂律拟合。
两组实验共用相同的 alpha=0、m=1 网络，避免基准网络重复随机生成。
"""

from pathlib import Path
from math import comb
import csv
import random
import sys
import argparse
from types import SimpleNamespace

import numpy as np
import matplotlib
from matplotlib.ticker import MaxNLocator


# ===================== 可修改参数 =====================
N = 10000
G = 4
MH = 3

ALPHA_VALUES = [0.0, 0.5, 1.0]
FIXED_M = 1
M_VALUES = [1, 2, 3]
FIXED_ALPHA = 0.0

SEED = 20260930
SAVE_INDIVIDUAL = True          # 同时保存每个参数组合的独立图
SHOW_FIGURES = False            # True：保存后显示对比图窗口
DPI = 600
DATA_DIR = Path(__file__).resolve().parent / "data"
OUTPUT_DIR = Path(__file__).resolve().parent / "figures"
# =====================================================

if not SHOW_FIGURES:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paper_plot_style import configure_style, save_figure, LINE_WIDTH_PT
from paper_plot_palette import BASE_COLORS
from figure_layout import panel_inches

configure_style()


class SRHHypergraph:
    """按原代码规则生成简单、固定规模超图，保留插入顺序。"""

    def __init__(self, n, alpha, g, m, mh, seed=SEED):
        for name, value in (("n", n), ("g", g), ("m", m), ("mh", mh)):
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
                raise ValueError(f"{name} 必须为整数")
        if g < 2 or n < g:
            raise ValueError("需要满足 g >= 2 且 n >= g")
        if not (1 <= m < g):
            raise ValueError("需要满足 1 <= m < g")
        if mh <= 0:
            raise ValueError("mh 必须大于 0")
        if not (0.0 <= alpha <= 1.0):
            raise ValueError("alpha 必须位于 [0, 1]")

        self.n = n
        self.alpha = float(alpha)
        self.g = g
        self.m = m
        self.mh = mh
        self.seed = seed
        self.hypergraph = []
        self.degrees = [0] * n
        self.k_counts = [0] * n
        self.is_selected = [False] * n

        # 独立随机数对象不会污染外部状态；采用与原代码相同的随机数算法。
        self._py_rng = random.Random(seed)
        self._np_rng = np.random.RandomState(seed)
        self.generate_hypergraph()

    def _get_all_weights(self, active_count):
        """一次性计算已有节点 0 ~ active_count-1 的权重，用于偏好链接采样"""
        k_array = np.array(self.k_counts)
        selected_array = np.array(self.is_selected)

        # 逻辑：如果没被选过，权重 = k + 3，否则 = k
        weights = k_array + np.where(selected_array, 0, 3)

        return weights[:active_count]

    def generate_hypergraph(self):
        """
        新的 SRH 超图生成逻辑：

        初始阶段：
        - 初始 g 个节点构成一条超边；
        - 初始超边只加入一次；全程不允许成员集合完全相同的超边。

        演化阶段：
        - 每一步同时加入 m 个新节点；
        - 每一步创建 mh 条不同的超边，重复候选重新抽样；
        - 每条超边先包含本批次所有新节点；
        - 再从已有节点中选取 g-len(new_nodes) 个节点补足；
        - 选取已有节点时，以 alpha 概率随机连接，以 1-alpha 概率偏好连接；
        - 仅成功加入新超边后更新 PA 权重，重复候选不改变计数。
        """

        # ---------- Step 0：初始化 ----------
        initial_edge = tuple(range(self.g))

        self.hypergraph.append(initial_edge)
        edge_set = {initial_edge}
        for node in initial_edge:
            self.degrees[node] += 1

        active_count = self.g

        # ---------- Step 1：批量加入新节点 ----------
        while active_count < self.n:
            new_count = min(self.m, self.n - active_count)
            new_nodes = list(range(active_count, active_count + new_count))

            # 本批新节点加入系统后，下一批才会成为“已有节点”
            existing_count = active_count

            num_targets_needed = self.g - new_count
            max_unique_edges = comb(existing_count, num_targets_needed)
            if self.mh > max_unique_edges:
                raise ValueError(
                    f"本批最多可生成 {max_unique_edges} 条不同超边，"
                    f"但 mh={self.mh}；已有节点数={existing_count}，"
                    f"需选择旧节点数={num_targets_needed}"
                )

            edges_created = 0
            attempts = 0
            max_attempts = max(10000, 1000 * self.mh)
            while edges_created < self.mh:
                attempts += 1
                if attempts > max_attempts:
                    raise RuntimeError(
                        f"本批在 {max_attempts} 次抽样内仅生成 "
                        f"{edges_created}/{self.mh} 条不同超边；"
                        "请检查 mh 或抽样权重设置。"
                    )
                edge_nodes = set(new_nodes)

                num_targets_needed = self.g - len(edge_nodes)

                if num_targets_needed > 0:
                    rand_val = self._py_rng.random()

                    if rand_val < self.alpha:
                        # 随机链接：从已有节点中无放回选择
                        targets = self._py_rng.sample(range(existing_count), num_targets_needed)

                    else:
                        # 偏好链接：每次生成超边前，都基于最新 k_counts / is_selected 重算概率
                        current_weights = self._get_all_weights(existing_count)
                        weight_sum = current_weights.sum()

                        if weight_sum == 0:
                            prob = np.ones(existing_count, dtype=float) / existing_count
                        else:
                            prob = current_weights / weight_sum

                        targets = self._np_rng.choice(
                            existing_count,
                            size=num_targets_needed,
                            replace=False,
                            p=prob
                        )

                    for target in targets:
                        edge_nodes.add(int(target))

                edge = tuple(sorted(edge_nodes))
                if edge in edge_set:
                    continue

                edge_set.add(edge)
                self.hypergraph.append(edge)
                edges_created += 1

                # 仅成功加入不同超边后更新旧节点的 PA 计数。
                for target in targets:
                    target = int(target)
                    self.k_counts[target] += 1
                    self.is_selected[target] = True

                # 更新所有参与该超边节点的度
                for node in edge:
                    self.degrees[node] += 1

            # 本批新节点正式成为已有节点
            active_count += new_count

def degree_distribution(degrees):
    """返回未分箱的离散概率质量 P(k)，不把频数直接当作概率。"""
    degrees = np.asarray(degrees, dtype=np.int64)
    k, counts = np.unique(degrees, return_counts=True)
    probability = counts.astype(float) / degrees.size
    return k, counts, probability


def validate_graph(graph):
    """从超边重新计数，检查画图使用的确为实际超度。"""
    expected_edges = 1 + graph.mh * ((graph.n - graph.g + graph.m - 1) // graph.m)
    if len(graph.hypergraph) != expected_edges:
        raise RuntimeError("超边总数与生长规则不符")
    if len(set(graph.hypergraph)) != len(graph.hypergraph):
        raise RuntimeError("存在重复超边")
    actual = np.zeros(graph.n, dtype=np.int64)
    for edge in graph.hypergraph:
        if len(edge) != graph.g or len(set(edge)) != graph.g:
            raise RuntimeError("超边规模不符或内部有重复节点")
        actual[list(edge)] += 1
    if not np.array_equal(actual, graph.degrees):
        raise RuntimeError("记录的超度与实际超边计数不一致")
    if np.any(actual == 0):
        raise RuntimeError("存在孤立节点")


def graph_tag(graph):
    return (f"alpha_{graph.alpha:.1f}_m_{graph.m}_mh_{graph.mh}"
            f"_n_{graph.n}_g_{graph.g}")


def export_data(graph, output_dir):
    """保存逐节点超度与度分布，便于在其他软件重新画图。"""
    tag = graph_tag(graph)
    degrees = np.asarray(graph.degrees, dtype=np.int64)
    node_data = np.column_stack((np.arange(1, graph.n + 1), degrees))
    np.savetxt(output_dir / f"{tag}_nodes.csv", node_data, delimiter=",",
               fmt="%d", header="node_id_1based,hyperdegree", comments="")
    k, counts, probability = degree_distribution(degrees)
    with (output_dir / f"{tag}_distribution.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["hyperdegree_k", "node_count", "P_k", "log10_k", "log10_P_k"])
        for degree, count, prob in zip(k, counts, probability):
            writer.writerow([int(degree), int(count), float(prob),
                             float(np.log10(degree)), float(np.log10(prob))])


def draw_panel(ax, graph, color, *, comparison=False):
    degrees = np.asarray(graph.degrees)
    k, counts, probability = degree_distribution(degrees)
    positive = k > 0
    ax.scatter(np.log10(k[positive]), np.log10(probability[positive]),
               s=9, color=color, alpha=0.68, linewidths=LINE_WIDTH_PT,
               edgecolors=color, label=r"Observed $P(k)$")
    if comparison:
        # The finished A1 panels use only the mathematical axis labels.
        ax._paper_formula_only_xlabel = True
        ax.set_xlabel(r"$\log_{10}(k)$", labelpad=1.5)
        ax.set_ylabel(r"$\log_{10} P(k)$", labelpad=1.5)
    else:
        ax.set_xlabel(r"Hyperdegree, $\log_{10}(k)$", labelpad=1.5)
        ax.set_ylabel("Hyperdegree probability,\n" + r"$\log_{10} P(k)$", labelpad=1.5)
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.tick_params(length=2, pad=1.5)
    ax.grid(True, color="#dddddd", linewidth=LINE_WIDTH_PT, alpha=0.8)
    ax.set_axisbelow(True)
    # The probability axes identify the observations; an internal legend
    # would cover the high-probability points at the final paper size.
    if not comparison:
        stats = (rf"$L={len(graph.hypergraph)}$" + "\n"
                 + rf"$\langle k\rangle={degrees.mean():.3f}$")
        ax.annotate(stats, xy=(0.5, 0), xycoords="axes fraction",
                    xytext=(0, -23), textcoords="offset points",
                    ha="center", va="top", fontsize=8, linespacing=1.05)


def set_shared_limits(axes, graphs, *, padding=0.0):
    max_degree = max(max(graph.degrees) for graph in graphs)
    x_min, x_max = 0.0, max(1.0, np.log10(max_degree) + 0.15)
    y_min, y_max = -np.log10(graphs[0].n) - 0.2, 0.05
    x_padding = (x_max - x_min) * padding
    y_padding = (y_max - y_min) * padding
    for ax in axes:
        ax.set_xlim(x_min - x_padding, x_max + x_padding)
        ax.set_ylim(y_min - y_padding, y_max + y_padding)


def save_comparison(graphs, group, output_dir):
    """一行三个子图，同组使用相同坐标范围，便于比较。"""
    # The two comparison strips form the two rows of the finished A1.
    # Only its bottom row needs horizontal labels and tick numbers.
    bottom_row = group == "m"
    width_mm, height_mm = 160.0, (52.0 if bottom_row else 42.0)
    fig, axes = plt.subplots(1, len(graphs),
                             figsize=(width_mm / 25.4, height_mm / 25.4),
                             squeeze=False)
    axes = axes.ravel()
    colors = BASE_COLORS
    for i, (ax, graph) in enumerate(zip(axes, graphs)):
        draw_panel(ax, graph, colors[i % len(colors)], comparison=True)
        ax.set_title(f"η = {graph.alpha:g}, m = {graph.m:g}")
    # Add 5% padding around 0-4, retaining its five integer tick labels.
    set_shared_limits(axes, graphs, padding=0.05)
    for i, ax in enumerate(axes):
        ax.set_xlim(-0.2, 4.2)
        ax.set_xticks([0, 1, 2, 3, 4])
        if i:
            ax.set_ylabel("")
            ax.tick_params(axis="y", which="both", labelleft=False)
        if not bottom_row:
            ax.set_xlabel("")
            ax.tick_params(axis="x", which="both", labelbottom=False)
    # Equal 44 x 32 mm plotting areas: a single shared y-label margin
    # frees space for larger data panels while retaining every tick mark.
    left_mm, axes_width_mm, axes_height_mm = 14.0, 44.0, 32.0
    pitch_mm = 50.0
    bottom_mm = 12.0 if bottom_row else 3.0
    for i, ax in enumerate(axes):
        ax.set_position([
            (left_mm + i * pitch_mm) / width_mm,
            bottom_mm / height_mm,
            axes_width_mm / width_mm,
            axes_height_mm / height_mm,
        ])
    stem = output_dir / f"compare_{group}_distribution"
    save_figure(fig, stem, bbox_inches="tight", facecolor="white")
    if not SHOW_FIGURES:
        plt.close(fig)


def save_individual(graph, output_dir):
    fig, ax = plt.subplots(figsize=panel_inches("FigA1"))
    draw_panel(ax, graph, "#148e91")
    set_shared_limits([ax], [graph])
    fig.subplots_adjust(left=15/52, right=1-2/52,
                        top=1-8/44, bottom=15/44)
    save_figure(fig, output_dir / f"{graph_tag(graph)}_distribution", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    configure_style()
    plt.rcParams.update({"axes.spines.top": True, "axes.spines.right": True})

    # 去重后共有五个参数组合；两组比较共享同一张基准网络。
    configurations = list(dict.fromkeys(
        [(float(alpha), FIXED_M) for alpha in ALPHA_VALUES]
        + [(float(FIXED_ALPHA), m) for m in M_VALUES]
    ))
    graphs = {}
    summary_rows = []
    for index, (alpha, m) in enumerate(configurations, start=1):
        print(f"[{index}/{len(configurations)}] Generating alpha={alpha:g}, m={m} ...",
              flush=True)
        # 所有组合用同一可复现种子；不同规则会消耗不同的随机序列。
        graph = SRHHypergraph(N, alpha, G, m, MH, seed=SEED)
        validate_graph(graph)
        graphs[(alpha, m)] = graph
        export_data(graph, DATA_DIR)
        if SAVE_INDIVIDUAL:
            save_individual(graph, OUTPUT_DIR)
        degrees = np.asarray(graph.degrees)
        summary_rows.append([alpha, m, MH, N, G, SEED, len(graph.hypergraph),
                             float(degrees.mean()), int(degrees.min()), int(degrees.max())])
        print(f"  edges={len(graph.hypergraph)}, mean k={degrees.mean():.4f}, "
              f"max k={degrees.max()}", flush=True)

    alpha_graphs = [graphs[(float(alpha), FIXED_M)] for alpha in ALPHA_VALUES]
    m_graphs = [graphs[(float(FIXED_ALPHA), m)] for m in M_VALUES]
    save_comparison(alpha_graphs, "alpha", OUTPUT_DIR)
    save_comparison(m_graphs, "m", OUTPUT_DIR)

    with (DATA_DIR / "network_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["alpha", "m", "mh", "n", "g", "seed", "edge_count",
                         "mean_hyperdegree", "min_hyperdegree", "max_hyperdegree"])
        writer.writerows(summary_rows)

    print(f"Saved figures to {OUTPUT_DIR} and CSV data to {DATA_DIR}", flush=True)
    if SHOW_FIGURES:
        plt.show()


def redraw_existing_data():
    """Redraw the stored node data without generating a new network."""
    graphs = {}
    with (DATA_DIR / "network_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            graph = SimpleNamespace(n=int(row["n"]), g=int(row["g"]), m=int(row["m"]),
                                    mh=int(row["mh"]), alpha=float(row["alpha"]),
                                    hypergraph=range(int(row["edge_count"])))
            with (DATA_DIR / f"{graph_tag(graph)}_nodes.csv").open(encoding="utf-8-sig", newline="") as nodes:
                graph.degrees = [int(item["hyperdegree"]) for item in csv.DictReader(nodes)]
            if len(graph.degrees) != graph.n:
                raise ValueError(f"Stored node count differs from N: {graph_tag(graph)}")
            graphs[(graph.alpha, graph.m)] = graph
            if SAVE_INDIVIDUAL:
                save_individual(graph, OUTPUT_DIR)
    save_comparison([graphs[(float(v), FIXED_M)] for v in ALPHA_VALUES], "alpha", OUTPUT_DIR)
    save_comparison([graphs[(FIXED_ALPHA, v)] for v in M_VALUES], "m", OUTPUT_DIR)
    print("Redrew Appendix A from unchanged stored node data", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-data", action="store_true", help="Only redraw existing network_summary/nodes CSVs.")
    if parser.parse_args().reuse_data:
        redraw_existing_data()
    else:
        main()
