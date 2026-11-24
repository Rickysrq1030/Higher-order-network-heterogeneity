"""ORH PGG 完整运行版。

安装依赖：python -m pip install numpy scipy networkx openpyxl tqdm
将本文件放到原结果目录后运行，或在 LEGACY_RESULT_DIRS 中指定旧 TXT 目录。
保留原 V2 的实验网格、演化规则、平均值统计口径和完成结果复用规则。
发生错误时记录参数、解释器、实际加载的函数字节码，随后停止并保留原异常。
"""

from tqdm import tqdm
import ast
import dis
import hashlib
import json
import math
import os
import random
import multiprocessing as mp
import sys
import traceback
import numpy as np
import scipy.stats as stats
import networkx as nx
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

# 存储设置：新结果保存在脚本所在目录，同时查找启动目录里的旧 TXT。
# 如旧结果在其他目录，可将该目录的绝对路径填入 LEGACY_RESULT_DIRS。
RESULT_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_RESULT_DIRS = []
RECORD_VERSION = 1
CODE_VERSION = "ORH_PGG_V2_checked_2026-09-21"
SCRIPT_PATH = os.path.abspath(__file__)
with open(SCRIPT_PATH, "rb") as _source_file:
    LOADED_SOURCE_SHA256 = hashlib.sha256(_source_file.read()).hexdigest()


def unpack_simulation_args(args):
    if len(args) == 7:
        return (*args, 1000000, 100000)
    if len(args) == 9:
        return tuple(args)
    raise ValueError("单次仿真参数数量必须为 7 或 9")


def format_dist_label(value):
    if isinstance(value, (int, float, np.integer, np.floating)):
        return f"{float(value):.3f}"
    return str(value)


def result_filename(args):
    """沿用原 ORH PGG 的文件名，以便识别历史结果。"""
    pro_g, val_g, n, p, alpha, beta, dist_param, mc_steps, out_steps = unpack_simulation_args(args)
    pro_g_str = "-".join(f"{x:.3f}" for x in pro_g)
    return (
        f"ORH_N={n}_proG={pro_g_str}_dist={format_dist_label(dist_param)}_"
        f"p={p:.2f}_alpha={alpha:.3f}_beta={beta:.3f}_steps={mc_steps}.txt"
    )


def recording_parameters(args):
    pro_g, val_g, n, p, alpha, beta, dist_param, mc_steps, out_steps = unpack_simulation_args(args)
    numeric_dist = isinstance(dist_param, (int, float, np.integer, np.floating))
    return {
        "model": "ORH_PGG", "n": int(n), "pro_g": [float(x) for x in pro_g],
        "val_g": [int(x) for x in val_g], "p": float(p), "alpha": float(alpha),
        "beta": float(beta), "dist": float(dist_param) if numeric_dist else str(dist_param),
        "mc_steps": int(mc_steps), "out_steps": int(out_steps), "c": 1.0
    }


def summary_row_from_result(args, average_fc):
    pro_g, val_g, n, p, alpha, beta, dist_param, mc_steps, out_steps = unpack_simulation_args(args)
    if isinstance(dist_param, (int, float, np.integer, np.floating)):
        dist_param = float(dist_param)
    return [int(n), int(mc_steps), float(beta), "-".join(f"{x:.3f}" for x in pro_g),
            dist_param, float(p), float(alpha), float(average_fc)]


def valid_node_records(records, n):
    if not isinstance(records, list) or len(records) != n:
        return False
    for row in records:
        if not isinstance(row, list) or len(row) != 5:
            return False
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in row):
            return False
        if row[1] not in (0, 1) or row[2] < 0 or row[3] < 0 or int(row[3]) != row[3]:
            return False
        if not 0.0 <= row[4] <= 1.0:
            return False
    return True


def legacy_parameters_match(args):
    """旧 TXT 未保存 val_g，只对上传原版的规模取值和无精度歧义的参数复用。"""
    pro_g, val_g, n, p, alpha, beta, dist_param, mc_steps, out_steps = unpack_simulation_args(args)
    if list(val_g) != [2, 3, 4, 5, 6]:
        return False
    values = [(p, 2), (alpha, 3), (beta, 3), *((value, 3) for value in pro_g)]
    if isinstance(dist_param, (int, float, np.integer, np.floating)):
        values.append((dist_param, 3))
    return all(float(value) == float(f"{value:.{digits}f}") for value, digits in values)


def read_completed_file(filepath, args):
    """必须有有效最终合作率、网络记录和完整节点记录，才认定仿真已完成。"""
    pro_g, val_g, n, p, alpha, beta, dist_param, mc_steps, out_steps = unpack_simulation_args(args)
    average_prefix = f"最终平均合作率 (最后 {out_steps} 步均值): "
    average_fc = None
    complete_nodes = False
    complete_network = False
    version = None
    parameters = None
    new_record_seen = False
    last_nonempty_line = ""
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            if f.readline().strip() != result_filename(args)[:-4]:
                return None
            for line in f:
                if not line.endswith("\n"):
                    return None
                stripped = line.strip()
                if stripped:
                    last_nonempty_line = stripped
                if line.startswith("记录格式版本="):
                    new_record_seen = True
                    version = int(line.split("=", 1)[1])
                elif line.startswith("实验参数="):
                    new_record_seen = True
                    parameters = json.loads(line.split("=", 1)[1])
                elif line.startswith(average_prefix):
                    average_fc = float(line[len(average_prefix):].strip())
                elif line.startswith("超边列表="):
                    complete_network = stripped.startswith("超边列表=[") and stripped.endswith("]")
                elif line.startswith("节点记录="):
                    records = ast.literal_eval(line.split("=", 1)[1].strip())
                    complete_nodes = valid_node_records(records, n)
                elif line.startswith("记录完成="):
                    new_record_seen = True
    except (FileNotFoundError, UnicodeError, ValueError, SyntaxError, TypeError, OverflowError):
        return None
    if (average_fc is None or not math.isfinite(average_fc)
            or not 0.0 <= average_fc <= 1.0 or not complete_nodes or not complete_network):
        return None
    if new_record_seen:
        if (version != RECORD_VERSION or parameters != recording_parameters(args)
                or last_nonempty_line != "记录完成=1"):
            return None
    elif not legacy_parameters_match(args) or not last_nonempty_line.startswith("节点记录="):
        return None
    return summary_row_from_result(args, average_fc)


def read_completed_result(args):
    """正式 TXT 是完成依据；忽略临时文件，不能仅凭 Excel 行或文件存在就跳过。"""
    filename = result_filename(args)
    visited = set()
    for directory in [RESULT_DIR, *LEGACY_RESULT_DIRS, os.getcwd()]:
        directory = os.path.abspath(directory)
        identity = os.path.normcase(directory)
        if identity in visited:
            continue
        visited.add(identity)
        result = read_completed_file(os.path.join(directory, filename), args)
        if result is not None:
            return result
    return None


class Simulation:
    def __init__(
            self,
            pro_g,
            val_g,
            n,
            p,
            alpha,
            beta,
            dist_param,
            mc_steps=1000000,
            out_steps=100000
    ):
        self.n = n  # 节点数
        self.p = p  # 边策略节点比例
        self.c = 1.0  # 合作者成本

        # 公共品博弈收益参数：
        # 每条边的收益放大因子 R_e = alpha * g_e^beta
        self.alpha = alpha
        self.beta = beta

        # 分布标识：Beta 分布使用数值参数，两个人工分布使用文字标签
        self.dist_param = dist_param

        if isinstance(dist_param, (int, float, np.integer, np.floating)):
            self.dist_label = f"{float(dist_param):.3f}"
        else:
            self.dist_label = str(dist_param)

        self.pro_g = list(pro_g)  # 超边规模分布
        self.val_g = list(val_g)  # 超边规模取值，如 [2, 3, 4, 5, 6]
        self.sum_g = [0.0] * len(self.pro_g)

        # ---------- 参数检查 ----------
        if len(self.pro_g) != len(self.val_g):
            raise ValueError("pro_g 和 val_g 长度不匹配")

        if len(self.pro_g) == 0:
            raise ValueError("pro_g 和 val_g 不能为空")

        if min(self.pro_g) < 0 or max(self.pro_g) > 1:
            raise ValueError("pro_g 中的概率值必须在 [0, 1] 范围内")

        if abs(sum(self.pro_g) - 1.0) > 1e-9:
            raise ValueError(f"pro_g 的总和必须为 1.0，当前为 {sum(self.pro_g)}")

        # ---------- 计算期望超边规模 ----------
        self.expect_g = 0.0
        for i in range(len(self.pro_g)):
            self.expect_g += self.pro_g[i] * self.val_g[i]

        if self.expect_g <= 1:
            raise ValueError("expect_g 必须大于 1，否则无法根据 ORH 公式计算边数")

        # ---------- 根据 expect_g 计算超边数量 ----------
        # 与 ORH.py 逻辑一致
        self.l = math.floor((self.n - 1) / (self.expect_g - 1) * math.log(self.n))

        if self.l <= 0:
            raise ValueError("超边数量 self.l 必须大于 0")

        # ---------- 构造累积概率 ----------
        for i in range(len(self.pro_g)):
            if i == 0:
                self.sum_g[i] = self.pro_g[i]
            else:
                self.sum_g[i] = self.pro_g[i] + self.sum_g[i - 1]

        self.sum_g[-1] = 1.0

        # ---------- 为每条超边预先分配规模 ----------
        self.g = [0] * self.l

        for edge_idx in range(self.l):
            rand_val = random.random()
            for j in range(len(self.sum_g)):
                if rand_val <= self.sum_g[j]:
                    self.g[edge_idx] = int(self.val_g[j])
                    break

        self.aver_g = sum(self.g) / self.l

        # ---------- 每条超边的公共品收益放大因子 ----------
        # 关键公式：R_e = alpha * g_e^beta
        self.R = [0.0] * self.l
        for edge_idx in range(self.l):
            self.R[edge_idx] = self.alpha * (self.g[edge_idx] ** self.beta)

        # ---------- 归一化因子 delta ----------
        self._calc_delta()

        # ---------- 基础数据结构 ----------
        self.hypergraph = set()
        self.neighbor = [[] for _ in range(self.n)]
        self.node_type = []
        self.strategy = [[] for _ in range(self.n)]
        self.node_edge_map = {}

        self.cnt_ns = 0.0
        self.cnt_ls = 0.0

        self.total_payoff = [0.0] * self.n
        self.aver_payoff = [0.0] * self.n
        self.edge_c_num = [0] * self.l

        self.aver_fc = 0.0
        # 每个节点最后 out_steps 步的平均合作率
        self.node_aver_fc = [0.0] * self.n

        self.initial()
        self.calc_payoff()
        self.run(mc_steps, out_steps)

    def _calc_delta(self):
        """
        按照 ORH.py 中给出的公共品博弈归一化因子公式计算 delta。
        """
        self.min_g = min(self.g)
        self.max_g = max(self.g)

        if self.beta < 1:
            threshold = 2 / (
                    self.min_g ** (self.beta - 1)
                    + self.max_g ** (self.beta - 1)
            )

            if self.alpha < threshold:
                self.delta = (
                        self.alpha * (self.min_g ** (self.beta - 1)) * (self.min_g - 1)
                        - self.alpha * (self.max_g ** (self.beta - 1))
                        + 1
                )
            else:
                self.delta = self.alpha * (self.min_g ** self.beta) - 1

        else:
            threshold = 2 / (
                    self.min_g ** (self.beta - 1)
                    + self.max_g ** (self.beta - 1)
            )

            if self.alpha < threshold:
                self.delta = (
                        self.alpha * (self.max_g ** (self.beta - 1)) * (self.max_g - 1)
                        - self.alpha * (self.min_g ** (self.beta - 1))
                        + 1
                )
            else:
                self.delta = self.alpha * (self.max_g ** self.beta) - 1

    def initial(self):
        # 创建 ORH 超图
        self.generate_hypergraph()

        # set 转 list 后顺序可能变化，因此用 sorted 固定顺序
        self.hypergraph = sorted(self.hypergraph)

        # 重新校准实际超边数量、每条边规模和每条边收益因子
        self.l = len(self.hypergraph)
        self.g = [len(edge) for edge in self.hypergraph]
        self.aver_g = sum(self.g) / self.l

        # set 转 list 后，edge_idx 顺序变化，因此必须重算 R 和 delta
        self.R = [0.0] * self.l
        for edge_idx in range(self.l):
            self.R[edge_idx] = self.alpha * (self.g[edge_idx] ** self.beta)

        self._calc_delta()

        # 检查是否连通
        G = nx.Graph()
        G.add_nodes_from(range(self.n))

        for edge in self.hypergraph:
            for i in range(len(edge)):
                for j in range(i + 1, len(edge)):
                    G.add_edge(edge[i], edge[j])

        self.is_connected = nx.is_connected(G)

        if self.is_connected:
            pass
            # print("Connected")
        else:
            print("Not Connected")

        # 构造邻居矩阵和 O(1) 局部索引映射
        self.neighbor = [[] for _ in range(self.n)]
        self.node_edge_map = {}

        for edge_idx, edge in enumerate(self.hypergraph):
            for node in edge:
                self.node_edge_map[(node, edge_idx)] = len(self.neighbor[node])
                self.neighbor[node].append(edge_idx)

        # 节点类型：边策略节点为 1，点策略节点为 0
        self.node_type = [
            1 if random.random() < self.p else 0
            for _ in range(self.n)
        ]

        # 分配节点策略
        for node_idx in range(self.n):
            num_neighbors = len(self.neighbor[node_idx])

            if num_neighbors == 0:
                self.strategy[node_idx] = []
                continue

            if self.node_type[node_idx] == 0:
                strategy = random.randint(0, 1)
                self.strategy[node_idx] = num_neighbors * [strategy]

                if strategy == 1:
                    self.cnt_ns += 1.0

            else:
                for _ in range(num_neighbors):
                    strategy = random.randint(0, 1)
                    self.strategy[node_idx].append(strategy)

                    if strategy == 1:
                        self.cnt_ls += 1.0 / num_neighbors

    def calc_cooperate_rate(self, node_fc_sum=None):
        """
        计算当前全局合作率。

        如果传入 node_fc_sum，则同时将每个节点当前的合作率累加到
        node_fc_sum 中，用于计算逐节点的时间平均合作率。
        """
        self.cnt_ls = 0.0
        self.cnt_ns = 0.0

        for node_idx in range(self.n):
            num_edges = len(self.strategy[node_idx])

            if num_edges == 0:
                node_fc = 0.0
            elif self.node_type[node_idx] == 0:
                # 点策略节点在所有关联超边上使用相同策略
                node_fc = float(self.strategy[node_idx][0])
                self.cnt_ns += node_fc
            else:
                # 边策略节点的当前合作率为其合作超边所占比例
                node_fc = sum(self.strategy[node_idx]) / num_edges
                self.cnt_ls += node_fc

            if node_fc_sum is not None:
                node_fc_sum[node_idx] += node_fc

        fc = (self.cnt_ls + self.cnt_ns) / self.n
        return fc

    def get_node_cooperate_rates(self):
        """返回当前时刻每个节点的合作率。"""
        node_fc = [0.0] * self.n

        for node_idx in range(self.n):
            num_edges = len(self.strategy[node_idx])

            if num_edges == 0:
                node_fc[node_idx] = 0.0
            elif self.node_type[node_idx] == 0:
                node_fc[node_idx] = float(self.strategy[node_idx][0])
            else:
                node_fc[node_idx] = sum(self.strategy[node_idx]) / num_edges

        return node_fc

    def calc_payoff(self):
        """
        初始化公共品博弈收益。
        后续收益由 update_payoff() 增量更新，不再全局重算。

        对每条边 e：
        R_e = alpha * g_e^beta
        total_edge_payoff = c_num * c * R_e
        每个成员获得 total_edge_payoff / g_e
        合作者额外支付成本 c
        """
        self.total_payoff = [0.0] * self.n
        self.aver_payoff = [0.0] * self.n
        self.edge_c_num = [0] * self.l

        for edge_idx in range(self.l):
            members = self.hypergraph[edge_idx]
            g_size = self.g[edge_idx]

            c_num = 0

            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]

                if self.strategy[node_idx][local_idx] == 1:
                    c_num += 1

            self.edge_c_num[edge_idx] = c_num

            total_edge_payoff = c_num * self.c * self.R[edge_idx]
            shared_benefit = total_edge_payoff / g_size

            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]
                is_cooperator = self.strategy[node_idx][local_idx] == 1

                if is_cooperator:
                    self.total_payoff[node_idx] += shared_benefit - self.c
                else:
                    self.total_payoff[node_idx] += shared_benefit

        for node_idx in range(self.n):
            s_len = len(self.strategy[node_idx])
            self.aver_payoff[node_idx] = (
                self.total_payoff[node_idx] / s_len if s_len > 0 else 0.0
            )

    def update_payoff(self, node_idx, target_strategy, chosen_edge_idx=None, chosen_local_idx=None):
        """
        公共品博弈的增量收益更新。
        """

        # 边策略节点：只更新当前被选中的一条超边
        if self.node_type[node_idx] == 1:
            if chosen_edge_idx is None or chosen_local_idx is None:
                raise ValueError("边策略节点更新时必须提供 chosen_edge_idx 和 chosen_local_idx")

            affected_edges = [(chosen_local_idx, chosen_edge_idx)]

        # 点策略节点：该节点参与的所有超边上的策略同步变化
        else:
            if len(self.strategy[node_idx]) == 0:
                return

            if self.strategy[node_idx][0] == target_strategy:
                return

            affected_edges = [
                (local_idx, edge_idx)
                for local_idx, edge_idx in enumerate(self.neighbor[node_idx])
            ]

        for local_idx, edge_idx in affected_edges:
            old_strategy = self.strategy[node_idx][local_idx]

            if old_strategy == target_strategy:
                continue

            members = self.hypergraph[edge_idx]
            g_size = self.g[edge_idx]
            old_c_num = self.edge_c_num[edge_idx]

            # 1. 扣除旧状态下该超边对所有成员的收益贡献
            old_total_edge_payoff = old_c_num * self.c * self.R[edge_idx]
            old_shared_benefit = old_total_edge_payoff / g_size

            for member in members:
                member_local_idx = self.node_edge_map[(member, edge_idx)]
                is_cooperator = self.strategy[member][member_local_idx] == 1

                if is_cooperator:
                    self.total_payoff[member] -= old_shared_benefit - self.c
                else:
                    self.total_payoff[member] -= old_shared_benefit

            # 2. 修改被更新节点在该超边上的策略
            self.strategy[node_idx][local_idx] = target_strategy

            # 3. 更新该超边当前合作者数量
            new_c_num = old_c_num + target_strategy - old_strategy
            self.edge_c_num[edge_idx] = new_c_num

            # 4. 加回新状态下该超边对所有成员的收益贡献
            new_total_edge_payoff = new_c_num * self.c * self.R[edge_idx]
            new_shared_benefit = new_total_edge_payoff / g_size

            for member in members:
                member_local_idx = self.node_edge_map[(member, edge_idx)]
                is_cooperator = self.strategy[member][member_local_idx] == 1

                if is_cooperator:
                    self.total_payoff[member] += new_shared_benefit - self.c
                else:
                    self.total_payoff[member] += new_shared_benefit

            # 5. 只更新该超边内成员的平均收益
            for member in members:
                s_len = len(self.strategy[member])
                self.aver_payoff[member] = (
                    self.total_payoff[member] / s_len if s_len > 0 else 0.0
                )

    def find_max_neighbor(self, node_idx, chosen_edge_idx):
        """在所选超边中，查找除自身以外平均收益最大的成员。"""
        max_profit = -math.inf
        max_profit_node = -1
        members = self.hypergraph[chosen_edge_idx]
        average_payoffs = self.aver_payoff

        for n_idx in members:
            if n_idx == node_idx:
                continue
            payoff = average_payoffs[n_idx]
            if payoff > max_profit:
                max_profit = payoff
                max_profit_node = n_idx

        return max_profit_node, max_profit

    def update_node(self, node_idx):
        edges = self.neighbor[node_idx]

        if len(edges) == 0:
            return

        e_idx = random.randint(0, len(edges) - 1)
        chosen_edge_idx = self.neighbor[node_idx][e_idx]

        target_idx, target_payoff = self.find_max_neighbor(node_idx, chosen_edge_idx)

        if target_idx == -1:
            return

        if self.delta <= 0:
            return

        probability = max(
            0.0,
            min(1.0, (target_payoff - self.aver_payoff[node_idx]) / self.delta)
        )

        if random.random() < probability:
            local_idx_target = self.node_edge_map[(target_idx, chosen_edge_idx)]
            target_strategy = self.strategy[target_idx][local_idx_target]

            if self.node_type[node_idx] == 1:
                self.update_payoff(
                    node_idx=node_idx,
                    target_strategy=target_strategy,
                    chosen_edge_idx=chosen_edge_idx,
                    chosen_local_idx=e_idx
                )

            else:
                self.update_payoff(
                    node_idx=node_idx,
                    target_strategy=target_strategy
                )

    def write_network_info(self, f):
        """将当前超图的结构和统计信息写入结果文件。"""
        hyperdegrees = [
            len(self.neighbor[node_idx])
            for node_idx in range(self.n)
        ]

        edge_size_counts = {
            g_size: self.g.count(g_size)
            for g_size in sorted(set(self.g))
        }

        average_hyperdegree = sum(hyperdegrees) / self.n

        f.write("\n网络信息:\n")
        f.write(f"节点数量={self.n}\n")
        f.write(f"超边数量={self.l}\n")
        f.write(f"期望超边规模={self.expect_g:.6f}\n")
        f.write(f"实际平均超边规模={self.aver_g:.6f}\n")
        f.write(f"最小超边规模={min(self.g)}\n")
        f.write(f"最大超边规模={max(self.g)}\n")
        f.write(f"各规模超边数量={edge_size_counts}\n")
        f.write(f"平均超度={average_hyperdegree:.6f}\n")
        f.write(f"最小超度={min(hyperdegrees)}\n")
        f.write(f"最大超度={max(hyperdegrees)}\n")
        f.write(f"投影网络是否连通={int(self.is_connected)}\n")

        # 完整超图结构：列表下标为超边编号，每个元组为该超边的成员
        f.write(f"超边列表={self.hypergraph}\n")

    def write_node_final_info(self, f, out_steps):
        """将所有节点的最终信息写入结果文件。"""
        # 根据最终策略全局重算一次，消除长期增量更新产生的浮点误差
        self.calc_payoff()

        node_records = []

        for node_idx in range(self.n):
            edge_indices = self.neighbor[node_idx]
            hyperdegree = len(edge_indices)

            if hyperdegree > 0:
                average_edge_size = sum(
                    self.g[edge_idx]
                    for edge_idx in edge_indices
                ) / hyperdegree
            else:
                average_edge_size = 0.0

            node_record = [
                float(round(self.aver_payoff[node_idx], 8)),
                int(self.node_type[node_idx]),
                round(average_edge_size, 8),
                hyperdegree,
                round(self.node_aver_fc[node_idx], 8)
            ]
            node_records.append(node_record)

        f.write("\n节点最终信息:\n")
        f.write(
            "字段=[最终平均收益, 节点类型, 所属超边平均规模, "
            f"超度, 最后{out_steps}步平均合作率]\n"
        )
        f.write(
            "说明：总列表下标即节点编号，"
            "节点类型0为点策略节点、1为边策略节点\n"
        )
        f.write(f"节点记录={node_records}\n")

    def run(self, mc_steps, out_steps):
        if out_steps > mc_steps:
            raise ValueError("out_steps 不能大于 mc_steps")

        self.mc_steps = mc_steps
        self.out_steps = out_steps

        pro_g_str = "-".join(f"{x:.3f}" for x in self.pro_g)

        args = (self.pro_g, self.val_g, self.n, self.p, self.alpha, self.beta,
                self.dist_param, mc_steps, out_steps)
        os.makedirs(RESULT_DIR, exist_ok=True)
        filename = os.path.join(RESULT_DIR, result_filename(args))
        temp_filename = filename + ".tmp"

        # 先写临时文件，完全结束后才替换正式 TXT。
        with open(temp_filename, "w", encoding="utf-8", buffering=1024 * 1024) as f:
            # 第一行记录完整实验参数
            f.write(
                f"ORH_N={self.n}_proG={pro_g_str}_dist={self.dist_label}_"
                f"p={self.p:.2f}_alpha={self.alpha:.3f}_beta={self.beta:.3f}_"
                f"steps={mc_steps}\n"
            )

            f.write(f"记录格式版本={RECORD_VERSION}\n")
            f.write("实验参数=" + json.dumps(recording_parameters(args), ensure_ascii=False, sort_keys=True) + "\n")

            # 参数行之后记录网络结构与统计信息
            self.write_network_info(f)
            f.write("\n演化过程:\n")

            self.aver_fc = 0.0
            last_sum = 0.0
            node_fc_sum = [0.0] * self.n

            for step in range(1, mc_steps + 1):
                # 每个 MCS 中随机有放回更新 n 个节点
                for _ in range(self.n):
                    node_idx = random.randint(0, self.n - 1)
                    self.update_node(node_idx)

                in_average_window = step > mc_steps - out_steps

                # 在最后 out_steps 步同步累计每个节点的合作率
                if in_average_window:
                    fc = self.calc_cooperate_rate(node_fc_sum)
                else:
                    fc = self.calc_cooperate_rate()

                # 每10000个 MCS 记录一次全局合作率
                if step % 10000 == 0:
                    f.write(
                        f"进度: {step}/{mc_steps}, 合作率: {fc:.4f}\n"
                    )

                if fc <= 1e-12 or fc >= 1.0 - 1e-12:
                    f.write(
                        f"进入吸收态，step={step}, 合作率为{fc:.4f}\n"
                    )

                    # 与原代码一致：假定进入吸收态后状态保持不变
                    last_sum = fc * out_steps
                    current_node_fc = self.get_node_cooperate_rates()
                    node_fc_sum = [
                        value * out_steps
                        for value in current_node_fc
                    ]
                    break

                if in_average_window:
                    last_sum += fc

            self.aver_fc = last_sum / out_steps
            self.node_aver_fc = [
                value / out_steps
                for value in node_fc_sum
            ]

            f.write(
                f"\n最终平均合作率 (最后 {out_steps} 步均值): "
                f"{self.aver_fc:.8f}\n"
            )

            self.write_node_final_info(f, out_steps)
            f.write("记录完成=1\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_filename, filename)

    def generate_hypergraph(self):
        edge_sets = set()
        unchosen_nodes = list(range(self.n))
        random.shuffle(unchosen_nodes)

        edge_count = 0

        while len(self.hypergraph) < self.l:
            g_size = self.g[edge_count]

            edge = []
            chosen_node = set()

            for _ in range(g_size):
                if unchosen_nodes:
                    node = unchosen_nodes.pop()
                else:
                    while True:
                        node = random.randint(0, self.n - 1)
                        if node not in chosen_node:
                            break

                edge.append(node)
                chosen_node.add(node)

            edge = tuple(sorted(edge))

            if edge not in edge_sets:
                edge_sets.add(edge)
                self.hypergraph.add(edge)
                edge_count += 1


def _run_single_simulation_impl(args):
    # 在创建网络前检查，已完成参数不再消耗仿真计算。
    existing_result = read_completed_result(args)
    if existing_result is not None:
        return existing_result
    (pro_g, val_g, n, p, alpha, beta, dist_param,
     mc_steps, out_steps) = unpack_simulation_args(args)

    sim = Simulation(
        pro_g,
        val_g,
        n,
        p,
        alpha,
        beta,
        dist_param,
        mc_steps=mc_steps,
        out_steps=out_steps
    )

    pro_g_str = "-".join(f"{x:.3f}" for x in sim.pro_g)

    # 返回一行全局汇总结果，由主进程写入 Excel
    return [
        sim.n,
        sim.mc_steps,
        sim.beta,
        pro_g_str,
        sim.dist_param,
        sim.p,
        sim.alpha,
        sim.aver_fc
    ]


def run_single_simulation(args):
    """运行一个参数组；错误日志只用于定位，失败任务不会伪装成完成。"""
    try:
        return _run_single_simulation_impl(args)
    except Exception:
        failure_traceback = sys.exc_info()[2]
        original_traceback = traceback.format_exc()
        error_filename = None
        try:
            os.makedirs(RESULT_DIR, exist_ok=True)
            error_filename = os.path.join(
                RESULT_DIR, result_filename(args) + f".error.{os.getpid()}.log"
            )
            with open(error_filename, "w", encoding="utf-8") as f:
                f.write(f"代码版本={CODE_VERSION}\n")
                f.write(f"脚本路径={SCRIPT_PATH}\n")
                f.write(f"模块加载时源码SHA256={LOADED_SOURCE_SHA256}\n")
                f.write(f"解释器={sys.executable}\nPython={sys.version}\n")
                f.write(f"PID={os.getpid()}\n参数={args!r}\n\n")
                f.write(original_traceback)
                f.write("\n异常现场（实际执行帧中的对象类型和指令）：\n")
                tb = failure_traceback
                while tb is not None:
                    frame = tb.tb_frame
                    f.write(
                        f"\n{frame.f_code.co_filename}:{tb.tb_lineno} "
                        f"函数={frame.f_code.co_name} 指令偏移={tb.tb_lasti}\n"
                    )
                    for name in ("self", "a", "b", "node_idx", "n_idx", "chosen_edge_idx"):
                        if name in frame.f_locals:
                            value = frame.f_locals[name]
                            value_type = type(value)
                            f.write(f"  {name} 的实际类型={value_type.__module__}.{value_type.__qualname__}")
                            if value_type in (int, float, str, bool, type(None)):
                                f.write(f" 值={value!r}")
                            f.write("\n")
                    for instruction in dis.get_instructions(frame.f_code, adaptive=True):
                        if abs(instruction.offset - tb.tb_lasti) <= 32:
                            f.write(f"  {instruction.offset}: {instruction.opname} {instruction.argrepr}\n")
                    tb = tb.tb_next
                f.write(f"\nrandom 模块路径={getattr(random, '__file__', None)}\n")
                f.write(f"randint 绑定对象类型={type(getattr(random.randint, '__self__', None))}\n")
                if hasattr(sys, "_jit"):
                    f.write(f"JIT 是否启用={sys._jit.is_enabled()}\n")
                f.write("\n实际加载的 randint 字节码：\n")
                dis.dis(random.randint, file=f)
                f.write("\n实际加载的 find_max_neighbor 字节码：\n")
                method = Simulation.find_max_neighbor
                f.write(f"代码文件={method.__code__.co_filename}\n")
                f.write(f"起始行={method.__code__.co_firstlineno}\n")
                dis.dis(method, file=f)
                f.flush()
                os.fsync(f.fileno())
            print(f"仿真失败，诊断日志：{error_filename}", file=sys.stderr, flush=True)
        except Exception as log_error:
            print(f"诊断日志写入失败：{log_error!r}", file=sys.stderr, flush=True)
            print(original_traceback, file=sys.stderr, flush=True)
        # 原样向主进程传播异常；完整 TXT 仍可在下次启动时复用。
        raise


SUMMARY_HEADERS = [
    "N",
    "steps",
    "beta",
    "proG",
    "dist",
    "p",
    "alpha",
    "final_avg_fc"
]


def save_summary_workbook(workbook, filename):
    """以临时文件替换方式保存，降低程序中断造成文件损坏的风险。"""
    temp_filename = f"{filename}.tmp.xlsx"
    workbook.save(temp_filename)
    os.replace(temp_filename, filename)


def create_summary_workbook(filename):
    """创建新的全局仿真结果 Excel 文件。"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Simulation Results"
    worksheet.append(SUMMARY_HEADERS)

    header_fill = PatternFill(
        fill_type="solid",
        fgColor="1F4E78"
    )
    header_font = Font(
        color="FFFFFF",
        bold=True
    )

    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center"
        )

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = "A1:H1"
    worksheet.sheet_view.showGridLines = False

    column_widths = {
        "A": 10,
        "B": 14,
        "C": 10,
        "D": 38,
        "E": 20,
        "F": 10,
        "G": 12,
        "H": 18
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[column].width = width

    save_summary_workbook(workbook, filename)
    return workbook, worksheet


def summary_result_key(row):
    """沿用原 Excel 的八列结构和参数精度，为已有结果建立去重索引。"""
    return (int(row[0]), int(row[1]), f"{float(row[2]):.3f}", str(row[3]),
            format_dist_label(row[4]), f"{float(row[5]):.2f}", f"{float(row[6]):.3f}")


def open_summary_workbook(filename):
    """保留已有汇总；启动扫描会把完整 TXT 补入或更新对应参数行。"""
    if os.path.isfile(filename):
        workbook = load_workbook(filename)
        if "Simulation Results" not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"汇总缺少 Simulation Results 工作表：{filename}")
        worksheet = workbook["Simulation Results"]
        if [cell.value for cell in worksheet[1]] != SUMMARY_HEADERS:
            workbook.close()
            raise ValueError(f"汇总表头与 ORH PGG 原版不一致：{filename}")
    else:
        workbook, worksheet = create_summary_workbook(filename)
    row_lookup = {}
    # 将历史重复参数行合并为最后一行；保留当前任务之外的其他参数结果。
    duplicates = []
    for row_idx in range(worksheet.max_row, 1, -1):
        row = [cell.value for cell in worksheet[row_idx]]
        if all(value is None for value in row):
            continue
        key = summary_result_key(row)
        if key in row_lookup:
            duplicates.append(row_idx)
        else:
            row_lookup[key] = row_idx
    for row_idx in duplicates:
        worksheet.delete_rows(row_idx)
    row_lookup = {}
    for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if not all(value is None for value in row):
            row_lookup[summary_result_key(row)] = row_idx
    worksheet.auto_filter.ref = f"A1:H{worksheet.max_row}"
    return workbook, worksheet, row_lookup


def append_summary_result(workbook, worksheet, filename, result_row, row_lookup, save=True):
    """按参数新增或更新结果，避免重启后重复追加。"""
    key = summary_result_key(result_row)
    row_idx = row_lookup.get(key)
    if row_idx is None:
        worksheet.append(result_row)
        row_idx = worksheet.max_row
        row_lookup[key] = row_idx
    else:
        for column, value in enumerate(result_row, start=1):
            worksheet.cell(row=row_idx, column=column, value=value)

    worksheet.cell(row=row_idx, column=1).number_format = "0"
    worksheet.cell(row=row_idx, column=2).number_format = "0"
    worksheet.cell(row=row_idx, column=3).number_format = "0.000"
    worksheet.cell(row=row_idx, column=4).number_format = "@"

    if isinstance(result_row[4], (int, float, np.integer, np.floating)):
        worksheet.cell(row=row_idx, column=5).number_format = "0.000"
    else:
        worksheet.cell(row=row_idx, column=5).number_format = "@"

    worksheet.cell(row=row_idx, column=6).number_format = "0.000"
    worksheet.cell(row=row_idx, column=7).number_format = "0.000"
    worksheet.cell(row=row_idx, column=8).number_format = "0.00000000"

    worksheet.auto_filter.ref = f"A1:H{worksheet.max_row}"
    if save:
        save_summary_workbook(workbook, filename)


def calc_pro_g(val_gs, alpha, beta):
    """
    使用 Beta 分布生成离散概率分布。
    保留你之前的 pro_g 计算方法。
    """
    low, high = min(val_gs), max(val_gs)

    if high == low:
        return [1.0]

    norm_vals = [(v - low) / (high - low) for v in val_gs]

    eps_boundary = 1e-9
    pro_gs_raw = []

    for x in norm_vals:
        safe_x = max(eps_boundary, min(1.0 - eps_boundary, x))
        p = stats.beta.pdf(safe_x, alpha, beta) + 1e-5
        pro_gs_raw.append(float(p))

    sum_p = sum(pro_gs_raw)
    pro_gs = [round(p / sum_p, 3) for p in pro_gs_raw]

    diff = round(1.0 - sum(pro_gs), 3)

    max_idx = pro_gs.index(max(pro_gs))
    pro_gs[max_idx] = round(pro_gs[max_idx] + diff, 3)

    return [float(p) for p in pro_gs]


def build_distribution_configs(val_gs):
    """
    构造论文中使用的五种超边规模分布。

    每个元素均为 (dist, pro_g)：
    - 两个极端分布由人工直接指定；
    - 中间三个分布由对称 Beta 分布生成。
    """
    return [
        (
            "strongly_convex",
            [0.0, 0.0, 1.0, 0.0, 0.0]
        ),
        (
            0.9,
            calc_pro_g(val_gs, 0.9, 0.9)
        ),
        (
            1.0,
            calc_pro_g(val_gs, 1.0, 1.0)
        ),
        (
            1.2,
            calc_pro_g(val_gs, 1.2, 1.2)
        ),
        (
            "strongly_concave",
            [0.5, 0.0, 0.0, 0.0, 0.5]
        )
    ]


if __name__ == "__main__":
    mp.freeze_support()
    print(f"代码版本：{CODE_VERSION}")
    print(f"脚本路径：{SCRIPT_PATH}")
    print(f"源码 SHA256：{LOADED_SOURCE_SHA256}")
    print(f"Python：{sys.version}")
    print(f"解释器：{sys.executable}", flush=True)

    n = 2000
    val_gs = [2, 3, 4, 5, 6]

    P_list = np.round(np.arange(0.0, 1.001, 0.25), 3)

    # 五种超边规模分布：两个直接指定，三个由对称 Beta 分布生成
    distribution_configs = build_distribution_configs(val_gs)

    # 公共品博弈收益参数：R_e = alpha * g_e^beta

    beta_list = [0.0, 1.0, 2.0]

    tasks = []

    for dist_param, pro_g in distribution_configs:
        for p in P_list:
            for beta in beta_list:
                if beta == 0.0:
                    alpha_list = np.round(np.arange(0.0, 8.01, 0.2), 3)
                elif beta == 1.0:
                    alpha_list = np.round(np.arange(0.0, 2.01, 0.05), 3)
                elif beta == 2.0:
                    alpha_list = np.round(np.arange(0.0, 0.4001, 0.01), 3)
                else:
                    raise ValueError(f"不支持的 beta 值：{beta}")

                for alpha in alpha_list:
                    tasks.append((
                        pro_g,
                        val_gs,
                        n,
                        float(p),
                        float(alpha),
                        float(beta),
                        dist_param
                    ))

    processes = 32
    os.makedirs(RESULT_DIR, exist_ok=True)
    summary_filename = os.path.join(RESULT_DIR, "ORH_global_results.xlsx")

    # 主进程独占 Excel；保留旧汇总，并从完整 TXT 恢复缺失的汇总行。
    summary_workbook, summary_worksheet, summary_row_lookup = open_summary_workbook(summary_filename)
    try:
        pending_tasks = []
        skipped_count = 0
        for args in tqdm(tasks, desc="检查已有结果"):
            existing_result = read_completed_result(args)
            if existing_result is None:
                pending_tasks.append(args)
            else:
                skipped_count += 1
                append_summary_result(
                    summary_workbook, summary_worksheet, summary_filename,
                    existing_result, summary_row_lookup, save=False
                )
        save_summary_workbook(summary_workbook, summary_filename)
        print(f"结果目录：{RESULT_DIR}")
        print(f"总参数组数：{len(tasks)}，已完成跳过：{skipped_count}，待运行：{len(pending_tasks)}")

        if pending_tasks:
            # 显式使用 spawn，使 Windows/Linux 都从保存后的脚本启动工作进程。
            with mp.get_context("spawn").Pool(processes=processes) as pool:
                result_iterator = pool.imap_unordered(run_single_simulation, pending_tasks)
                for result_row in tqdm(result_iterator, total=len(pending_tasks), desc="运行剩余仿真"):
                    append_summary_result(
                        summary_workbook, summary_worksheet, summary_filename,
                        result_row, summary_row_lookup
                    )
    finally:
        summary_workbook.close()

    print("\n" + "=" * 30)
    print("所有仿真已完成！")
    print(f"全局汇总文件：{summary_filename}")
