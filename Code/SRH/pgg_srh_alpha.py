# -*- coding: utf-8 -*-
# PGG 的 TXT 详细记录、Excel 汇总和按参数组续跑；未完成参数组从头重算。
import random
from math import comb
import os
import ast
import json
import math
import re
import numpy as np
from tqdm import tqdm
import multiprocessing as mp
import networkx as nx
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


'''
PGG SRH：alpha 参数扫描，保留原旧图生成方法及公共物品博弈函数。
m 为每批新节点数，mh 为每批超边数，末批允许少于 m 个新节点。
从 g 个节点的一条超边开始；每条候选超边独立选择一次随机/偏好分支。
目标仅从已有节点选择；未被选中过的节点权重为 3，否则为旧目标选择计数。
随机和偏好分支均更新计数，重复候选不更新。
alpha 扫描沿用原设置，p 扫描 0、0.25、0.5、0.75、1。
参考 MPD 的完整记录及续跑方式；结果写入脚本旁 old_generator_results。
'''

# 以下模块只处理文件记录和任务续跑，不改变仿真算法或随机数状态。
RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "old_generator_results")
# 可填写使用本记录格式的历史结果目录；原 PGG 简略 TXT 不满足完整性要求。
LEGACY_RESULT_DIRS = []
RECORD_VERSION = 1


def unpack_task(args):
    """兼容原七参数；九参数允许指定模拟步数和统计窗口。"""
    if len(args) not in (7, 9):
        raise ValueError("单次 PGG-SRH 仿真参数数量必须为 7 或 9")
    values = list(args[:7])
    for index in (0, 2, 3, 4):
        value = values[index]
        if isinstance(value, (bool, np.bool_)) or not math.isfinite(float(value)) or int(value) != value:
            raise ValueError("n、g、m、mh 必须是有限整数")
        values[index] = int(value)
    for index in (1, 5, 6):
        values[index] = float(values[index])
        if not math.isfinite(values[index]):
            raise ValueError("alpha、R、p 必须为有限数")
    n, alpha, g, m, mh, R, p = values
    if not (n >= g >= 2 and 1 <= m < g and mh > 0):
        raise ValueError("需要 n >= g >= 2、1 <= m < g、mh > 0")
    if not (0 <= alpha <= 1 and 0 <= p <= 1):
        raise ValueError("alpha 和 p 必须在 [0, 1] 内")
    steps, out = args[7:] if len(args) == 9 else (1000000, 100000)
    for value in (steps, out):
        if isinstance(value, (bool, np.bool_)) or not math.isfinite(float(value)) or int(value) != value:
            raise ValueError("mc_steps、out_steps 必须是正整数")
    if not 1 <= out <= steps:
        raise ValueError("需要 1 <= out_steps <= mc_steps")
    return tuple(values), int(steps), int(out)


def result_filename(args, mc_steps, out_steps):
    n, alpha, g, m, mh, R, p = args
    return (f"PGG_SRH_G={g}_N={n}_m={m}_mh={mh}_"
            f"alpha={alpha:.3f}_p={p:.3f}_R={R:.3f}_r={R / g:.3f}_"
            f"steps={mc_steps}_out={out_steps}.txt")


def result_header(args, mc_steps, out_steps):
    # 沿用 MPD 记录约定：文件名用 out，首行用 out_steps。
    return result_filename(args, mc_steps, out_steps)[:-4].replace(
        f"_out={out_steps}", f"_out_steps={out_steps}")


def recording_parameters(args, mc_steps, out_steps):
    n, alpha, g, m, mh, R, p = args
    return dict(game="PGG", network="SRH", generator="existing_nodes_batch_old",
                n=int(n), alpha=float(alpha), g=int(g), m=int(m), mh=int(mh),
                R=float(R), r=float(R / g), c=1.0, p=float(p),
                mc_steps=int(mc_steps), out_steps=int(out_steps))


def make_summary_row(args, average_fc, filepath):
    n, alpha, g, m, mh, R, p = args
    # 与 TXT 的八位小数一致，避免重启后汇总值发生精度变化。
    return [int(g), int(n), int(m), int(mh), float(alpha), float(p), float(R),
            float(R / g), float(round(average_fc, 8)), os.path.abspath(filepath)]


def valid_node_records(records, n):
    if not isinstance(records, list) or len(records) != n:
        return False
    for row in records:
        if not isinstance(row, list) or len(row) != 5:
            return False
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) for v in row):
            return False
        if row[1] not in (0, 1) or row[2] < 0 or row[3] < 0 or int(row[3]) != row[3]:
            return False
        if not 0.0 <= row[4] <= 1.0:
            return False
    return True


def valid_network_records(edges, records, args):
    n, alpha, g, m, mh, R, p = args
    expected = 1 + mh * ((n - g + m - 1) // m)
    if not isinstance(edges, list) or len(edges) != expected:
        return False
    degrees = [0] * n
    seen = set()
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != g:
            return False
        if not all(type(node) is int and 0 <= node < n for node in edge):
            return False
        key = tuple(sorted(edge))
        if len(set(edge)) != g or key in seen:
            return False
        seen.add(key)
        for node in edge:
            degrees[node] += 1
    return all(row[3] == degree and abs(row[2] - g) <= 1e-8
               for row, degree in zip(records, degrees))


def read_completed_file(filepath, args, mc_steps, out_steps):
    """完整参数、结构、节点记录和末尾完成标记均有效，才视为已完成。"""
    if not str(filepath).endswith('.txt'):
        return None
    average_prefix = f"最终平均合作率 (最后 {out_steps} 步均值): "
    average_fc = None
    version = parameters = edges = records = executed_steps = None
    last_nonempty_line = ''
    counts = {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            first = f.readline()
            if not first.endswith('\n') or first.strip() != result_header(args, mc_steps, out_steps):
                return None
            for line in f:
                if not line.endswith('\n'):
                    return None
                stripped = line.strip()
                if stripped:
                    last_nonempty_line = stripped
                key = line.split('=', 1)[0]
                if key in ('记录格式版本', '实验参数', '超边列表', '节点记录', '实际执行步数', '记录完成'):
                    counts[key] = counts.get(key, 0) + 1
                if line.startswith('记录格式版本='):
                    version = int(line.split('=', 1)[1])
                elif line.startswith('实验参数='):
                    parameters = json.loads(line.split('=', 1)[1])
                elif line.startswith(average_prefix):
                    counts['average'] = counts.get('average', 0) + 1
                    average_fc = float(line[len(average_prefix):].strip())
                elif line.startswith('超边列表='):
                    edges = ast.literal_eval(line.split('=', 1)[1].strip())
                elif line.startswith('节点记录='):
                    records = ast.literal_eval(line.split('=', 1)[1].strip())
                elif line.startswith('实际执行步数='):
                    executed_steps = int(line.split('=', 1)[1])
    except (FileNotFoundError, UnicodeError, ValueError, SyntaxError, TypeError,
            OverflowError, RecursionError):
        return None
    if (version != RECORD_VERSION
            or parameters != recording_parameters(args, mc_steps, out_steps)
            or last_nonempty_line != '记录完成=1'
            or any(counts.get(key) != 1 for key in
                   ('记录格式版本', '实验参数', '超边列表', '节点记录', '实际执行步数', '记录完成', 'average'))):
        return None
    if executed_steps is None or not 1 <= executed_steps <= mc_steps:
        return None
    if average_fc is None or not math.isfinite(average_fc) or not 0 <= average_fc <= 1:
        return None
    if not valid_node_records(records, int(args[0])):
        return None
    if not valid_network_records(edges, records, args):
        return None
    if abs(sum(row[4] for row in records) / len(records) - average_fc) > 2e-8:
        return None
    return make_summary_row(args, average_fc, filepath)


def read_completed_result(task):
    args, mc_steps, out_steps = unpack_task(task)
    filename = result_filename(args, mc_steps, out_steps)
    directories = [RESULT_DIR, *LEGACY_RESULT_DIRS]
    visited = set()
    for directory in directories:
        directory = os.path.abspath(directory)
        key = os.path.normcase(directory)
        if key in visited:
            continue
        visited.add(key)
        result = read_completed_file(os.path.join(directory, filename), args, mc_steps, out_steps)
        if result is not None:
            return result
    return None


def validate_task_filenames(tasks):
    """防止修改扫描参数后，不同精确参数因文件名舍入而写进同一文件。"""
    seen = {}
    for task in tasks:
        args, steps, out = unpack_task(task)
        name = result_filename(args, steps, out)
        parameters = recording_parameters(args, steps, out)
        if name in seen and seen[name] != parameters:
            raise ValueError(f'不同参数对应同一个 TXT 文件名，请提高命名精度：{name}')
        seen[name] = parameters


def old_generator_output_path(filename):
    """旧方法结果固定写入本脚本旁的独立目录，保留原文件名和格式。"""
    output_dir = RESULT_DIR
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, filename)


def check_destination_parameters(filepath, expected):
    """避免先后两次启动时，三位小数舍入造成不同精确参数覆盖。"""
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            for _ in range(4):
                line = f.readline()
                if line.startswith('实验参数='):
                    try:
                        parameters = json.loads(line.split('=', 1)[1])
                    except (ValueError, TypeError):
                        return
                    if isinstance(parameters, dict) and parameters != expected:
                        raise ValueError(f"已有同名 TXT 的精确参数不同，请提高文件名精度或另设 RESULT_DIR：{filepath}")
                    return
    except (FileNotFoundError, UnicodeError):
        return


class Simulation:
    def __init__(self, n, alpha, g, m, mh, R, p,
                 mc_steps=1000000, out_steps=100000):
        self.n = n              # 节点数
        self.alpha = alpha      # 控制连接方式：alpha 概率随机连接，1-alpha 概率偏好连接
        self.g = g              # 超边规模
        self.m = m              # 每批新节点数，末批允许不足 m 个
        self.mh = mh            # 每批创建的超边数

        if self.n < self.g:
            raise ValueError("需要满足 n >= g")
        if not (1 <= self.m < self.g):
            raise ValueError("需要满足 1 <= m < g，因为每条边还需要选取 g-m 个目标节点")
        if self.mh <= 0:
            raise ValueError("mh 必须大于 0")
        if not (0.0 <= self.alpha <= 1.0):
            raise ValueError("alpha 必须在 [0, 1] 内")
        self.m0 = self.g       # 旧方法从 g 个节点的一条超边开始
        self.R = R              # 公共品放大倍数
        self.p = p              # 边策略节点概率

        self.c = 1.0            # 合作者贡献成本
        self.r = self.R / self.g  # reduced synergy factor

        self.hypergraph = []  # 生成顺序存储，成员仍为 frozenset。
        self.neighbor = [[] for _ in range(self.n)]
        self.node_type = []
        self.strategy = [[] for _ in range(self.n)]
        self.node_edge_map = {}

        self.cnt_ns = 0.0       # 点策略合作者计数
        self.cnt_ls = 0.0       # 边策略合作频率计数

        self.total_payoff = [0.0] * self.n
        self.aver_payoff = [0.0] * self.n
        self.edge_c_num = []    # 每条超边当前合作者数量

        self.node_aver_fc = np.zeros(self.n, dtype=float)   #记录每个节点在最后 out_steps 步中的平均合作水平

        self.degrees = np.zeros(n, dtype=np.int64)
        self.k_counts = np.zeros(n, dtype=np.int64)  # 所有成功的旧目标选择次数
        self.is_selected = np.zeros(n, dtype=bool)

        self.aver_fc = 0.0

        # 公共品博弈下的收益差归一化项
        # 参考原 URH 公共品博弈代码中的 delta 形式
        self.delta = (1 + (self.g - 2) * self.r) if self.r < 1 else (self.g * self.r - 1)

        self.all_indices = np.arange(n)

        self.initial()
        self.l = len(self.hypergraph)
        self.calc_payoff()
        self.run(mc_steps, out_steps)

    def initial(self):
        # 创建 SRH 超图结构
        self.generate_hypergraph()
        self.hypergraph = list(self.hypergraph)

        # 检查是否连通
        G = nx.Graph()
        G.add_nodes_from(range(self.n))

        for edge in self.hypergraph:
            edge = list(edge)
            for i in range(len(edge)):
                for j in range(i + 1, len(edge)):
                    G.add_edge(edge[i], edge[j])

        self.is_connected = nx.is_connected(G)
        if self.is_connected:
            pass
            #print("Connected")
        else:
            print("Not Connected")

        # 构造邻居矩阵和 O(1) 局部策略索引映射
        self.neighbor = [[] for _ in range(self.n)]
        self.node_edge_map = {}

        for edge_idx, edge in enumerate(self.hypergraph):
            for node in edge:
                self.neighbor[node].append(edge_idx)
                self.node_edge_map[(node, edge_idx)] = len(self.neighbor[node]) - 1

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
                # 点策略节点：所有参与超边中的策略相同
                strategy = random.randint(0, 1)
                self.strategy[node_idx] = num_neighbors * [strategy]

                if strategy == 1:
                    self.cnt_ns += 1.0

            else:
                # 边策略节点：不同超边中可以采取不同策略
                for _ in range(num_neighbors):
                    strategy = random.randint(0, 1)
                    self.strategy[node_idx].append(strategy)

                    if strategy == 1:
                        self.cnt_ls += 1.0 / num_neighbors
    def calc_cooperate_rate_per_node(self):
        for node_idx in range(self.n):
            num_edges = len(self.strategy[node_idx])

            if num_edges == 0:
                continue

            if self.node_type[node_idx] == 0:
                self.node_aver_fc[node_idx] += (
                    1.0 if self.strategy[node_idx][0] == 1 else 0.0
                )

            else:
                coop_count = sum(
                    1 for s in self.strategy[node_idx]
                    if s == 1
                )

                self.node_aver_fc[node_idx] += coop_count / num_edges

    def calc_cooperate_rate(self):
        self.cnt_ls = 0.0
        self.cnt_ns = 0.0

        for node_idx in range(self.n):
            num_edges = len(self.strategy[node_idx])

            if num_edges == 0:
                continue

            if self.node_type[node_idx] == 0:
                self.cnt_ns += 1.0 if self.strategy[node_idx][0] == 1 else 0.0

            else:
                for s in self.strategy[node_idx]:
                    if s == 1:
                        self.cnt_ls += 1.0 / num_edges

        fc = (self.cnt_ls + self.cnt_ns) / self.n
        return fc

    def calc_payoff(self):
        """
        初始化公共品博弈收益。
        后续策略变化后，不再全局重算收益，而是由 update_payoff() 增量更新。

        公共品博弈收益：
        - 当前超边中 c_num 个合作者；
        - 每个合作者贡献成本 c；
        - 公共池总收益为 c_num * c * R；
        - 平均分配给超边内所有 g 个成员；
        - 合作者收益 = c_num * c * R / g - c；
        - 背叛者收益 = c_num * c * R / g。
        """
        self.aver_payoff = [0.0] * self.n
        self.total_payoff = [0.0] * self.n
        self.edge_c_num = [0] * self.l

        for edge_idx in range(self.l):
            members = self.hypergraph[edge_idx]

            # 计算该超边当前合作者数量
            c_num = 0
            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]
                if self.strategy[node_idx][local_idx] == 1:
                    c_num += 1

            self.edge_c_num[edge_idx] = c_num

            # 当前超边中每个成员获得的公共品收益份额
            shared_benefit = c_num * self.c * self.R / self.g

            # 分配收益
            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]
                is_cooperator = self.strategy[node_idx][local_idx] == 1

                if is_cooperator:
                    self.total_payoff[node_idx] += shared_benefit - self.c
                else:
                    self.total_payoff[node_idx] += shared_benefit

        # 计算平均收益
        for node_idx in range(self.n):
            s_len = len(self.strategy[node_idx])
            self.aver_payoff[node_idx] = self.total_payoff[node_idx] / s_len if s_len > 0 else 0.0

    def update_payoff(self, node_idx, target_strategy, chosen_edge_idx=None, chosen_local_idx=None):
        """
        公共品博弈收益的局部增量更新。

        逻辑：
        1. 边策略节点只更新当前选中的一条超边；
        2. 点策略节点更新其参与的所有超边；
        3. 每条受影响超边先扣除旧收益，再修改策略和合作者数量，再加上新收益；
        4. 只更新受影响超边中成员节点的平均收益。
        """

        # 边策略节点：只影响当前被选中的一条超边
        if self.node_type[node_idx] == 1:
            if chosen_edge_idx is None or chosen_local_idx is None:
                raise ValueError("边策略节点更新时必须提供 chosen_edge_idx 和 chosen_local_idx")

            affected_edges = [(chosen_local_idx, chosen_edge_idx)]

        # 点策略节点：该节点在所有参与超边上的策略同步变化
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
            old_c_num = self.edge_c_num[edge_idx]

            # 1. 扣除该超边旧状态下对所有成员的收益贡献
            old_shared_benefit = old_c_num * self.c * self.R / self.g

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

            # 4. 加回该超边新状态下对所有成员的收益贡献
            new_shared_benefit = new_c_num * self.c * self.R / self.g

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
                self.aver_payoff[member] = self.total_payoff[member] / s_len if s_len > 0 else 0.0

    def find_max_neighbor(self, node_idx, chosen_edge_idx):
        max_profit = -float("inf")
        max_profit_node = -1

        members = self.hypergraph[chosen_edge_idx]

        for n_idx in members:
            if n_idx != node_idx:
                if self.aver_payoff[n_idx] > max_profit:
                    max_profit = self.aver_payoff[n_idx]
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
        """将当前 SRH 超图的结构和统计信息写入单次仿真 TXT。"""
        hyperdegrees = [
            len(self.neighbor[node_idx])
            for node_idx in range(self.n)
        ]
        edge_sizes = [len(edge) for edge in self.hypergraph]
        edge_size_counts = {
            edge_size: edge_sizes.count(edge_size)
            for edge_size in sorted(set(edge_sizes))
        }
        unique_edge_count = len(set(self.hypergraph))
        average_hyperdegree = sum(hyperdegrees) / self.n
        edge_strategy_count = sum(self.node_type)

        f.write("\n网络信息:\n")
        f.write(f"节点数量={self.n}\n")
        f.write(f"固定超边规模g={self.g}\n")
        f.write(f"每步加入新节点数m={self.m}\n")
        f.write(f"每步创建超边数mh={self.mh}\n")
        f.write(f"随机连接概率alpha={self.alpha}\n")
        f.write(f"实际超边数量={self.l}\n")
        f.write(f"不同超边数量={unique_edge_count}\n")
        f.write(f"重复超边记录数量={self.l - unique_edge_count}\n")
        f.write(f"实际平均超边规模={sum(edge_sizes) / self.l:.6f}\n")
        f.write(f"最小超边规模={min(edge_sizes)}\n")
        f.write(f"最大超边规模={max(edge_sizes)}\n")
        f.write(f"各规模超边数量={edge_size_counts}\n")
        f.write(f"平均超度={average_hyperdegree:.6f}\n")
        f.write(f"最小超度={min(hyperdegrees)}\n")
        f.write(f"最大超度={max(hyperdegrees)}\n")
        f.write(f"投影网络是否连通={int(self.is_connected)}\n")
        f.write(f"点策略节点数量={self.n - edge_strategy_count}\n")
        f.write(f"边策略节点数量={edge_strategy_count}\n")

        # 列表下标为超边编号，每个子列表为该超边的成员，成员集合互不相同。
        edges = [[int(node) for node in sorted(edge)] for edge in self.hypergraph]
        f.write("超边列表=" + json.dumps(edges, allow_nan=False) + "\n")

    def write_node_final_info(self, f, out_steps):
        """将所有节点的最终统计信息写入单次仿真 TXT。"""
        # 根据最终策略全局重算一次，消除长期增量更新产生的浮点误差。
        self.calc_payoff()
        node_records = []

        for node_idx in range(self.n):
            edge_indices = self.neighbor[node_idx]
            hyperdegree = len(edge_indices)

            if hyperdegree > 0:
                average_edge_size = sum(
                    len(self.hypergraph[edge_idx])
                    for edge_idx in edge_indices
                ) / hyperdegree
            else:
                average_edge_size = 0.0

            # round(np.float64, 8) 仍是 NumPy 标量；写入前转为内置 float。
            # 先 round 再 float，保留现有八位小数的舍入结果。
            node_records.append([
                float(round(self.aver_payoff[node_idx], 8)),
                int(self.node_type[node_idx]),
                float(round(average_edge_size, 8)),
                hyperdegree,
                float(round(self.node_aver_fc[node_idx], 8))
            ])

        f.write("\n节点最终信息:\n")
        f.write(
            "字段=[最终平均收益, 节点类型, 所属超边平均规模, "
            f"超度, 最后{out_steps}步平均合作率]\n"
        )
        f.write(
            "说明：总列表下标即节点编号，"
            "节点类型0为点策略节点、1为边策略节点\n"
        )
        if not valid_node_records(node_records, self.n):
            raise ValueError("节点记录含非有限数、非法类型或越界合作率，保留临时文件")
        if abs(sum(row[4] for row in node_records) / self.n - self.aver_fc) > 2e-8:
            raise ValueError("节点平均合作率与全局平均合作率不一致，保留临时文件")
        f.write("节点记录=" + json.dumps(node_records, allow_nan=False) + "\n")

    def run(self, mc_steps, out_steps):
        record_args, mc_steps, out_steps = unpack_task(
            (self.n, self.alpha, self.g, self.m, self.mh, self.R, self.p, mc_steps, out_steps))
        self.mc_steps = mc_steps
        self.out_steps = out_steps
        filename = old_generator_output_path(result_filename(record_args, mc_steps, out_steps))
        self.result_filename = filename
        parameters = recording_parameters(record_args, mc_steps, out_steps)
        check_destination_parameters(filename, parameters)
        temp_filename = filename + '.tmp'

        # 未完成的 .tmp 不参与完成判定；重启后该参数组从头计算。
        with open(temp_filename, 'w', encoding='utf-8', buffering=1024 * 1024) as f:
            f.write(result_header(record_args, mc_steps, out_steps) + '\n')
            f.write(f"记录格式版本={RECORD_VERSION}\n")
            f.write('实验参数=' + json.dumps(parameters, ensure_ascii=False,
                                           sort_keys=True, allow_nan=False) + '\n')
            f.write('进度记录间隔=10000\n')
            self.write_network_info(f)
            f.write('\n演化过程:\n')
            f.flush()

            self.aver_fc = 0.0
            last_sum = 0.0
            for step in range(1, mc_steps + 1):
                # 保留原 PGG 的更新顺序、随机调用、吸收态判断和统计窗口。
                for _ in range(self.n):
                    node_idx = random.randint(0, self.n - 1)
                    self.update_node(node_idx)

                fc = self.calc_cooperate_rate()
                if step % 10000 == 0:
                    f.write(f"进度: {step}/{mc_steps}, 合作率: {fc:.4f}\n")
                    f.flush()

                if fc <= 1e-12 or fc >= 1.0 - 1e-12:
                    f.write(f"进入吸收态，step={step}, 合作率为{fc:.4f}\n")
                    last_sum = fc * out_steps
                    self.node_aver_fc[:] = 0.0
                    self.calc_cooperate_rate_per_node()
                    self.node_aver_fc *= out_steps
                    break

                if step > mc_steps - out_steps:
                    last_sum += fc
                    self.calc_cooperate_rate_per_node()

            self.aver_fc = last_sum / out_steps
            # 原记录写的是累计值；仅在演化结束后归一化为节点平均合作率。
            self.node_aver_fc /= out_steps
            f.write(f"\n最终平均合作率 (最后 {out_steps} 步均值): {self.aver_fc:.8f}\n")
            self.write_node_final_info(f, out_steps)
            f.write(f"实际执行步数={step}\n")
            f.write('记录完成=1\n')
            f.flush()
            os.fsync(f.fileno())
        # 仅完整写入、同步并关闭临时文件后发布正式 TXT。
        os.replace(temp_filename, filename)

    def _get_all_weights(self, active_count):
        """一次性计算已有节点 0 ~ active_count-1 的权重，用于偏好链接采样；计数包括随机和优先目标选择"""
        k_array = np.array(self.k_counts)
        selected_array = np.array(self.is_selected)

        # 逻辑：如果没被选过，权重 = k + 3，否则 = k
        weights = k_array + np.where(selected_array, 0, 3)

        return weights[:active_count]

    def generate_hypergraph(self):
        """
        旧方法：仅已有节点连接的 SRH 超图生成逻辑：

        初始阶段：
        - 初始 g 个节点构成一条超边；
        - 初始超边只加入一次；全程不允许成员集合完全相同的超边。

        演化阶段：
        - 每一步同时加入 m 个新节点；
        - 每一步创建 mh 条不同的超边，重复候选重新抽样；
        - 每条超边先包含本批次所有新节点；
        - 再从已有节点中选取 g-len(new_nodes) 个节点补足；
        - 每条候选超边选择一次分支：alpha 概率随机，1-alpha 概率偏好；
        - 成功加入后更新所有旧目标的选择计数（含随机分支）；重复候选不更新。
        """

        # ---------- Step 0：初始化 ----------
        initial_edge = frozenset(range(self.g))

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
                    rand_val = random.random()

                    if rand_val < self.alpha:
                        # 随机链接：从已有节点中无放回选择
                        targets = random.sample(range(existing_count), num_targets_needed)

                    else:
                        # 偏好链接：每次生成超边前，都基于最新 k_counts / is_selected 重算概率
                        current_weights = self._get_all_weights(existing_count)
                        weight_sum = current_weights.sum()

                        if weight_sum == 0:
                            prob = np.ones(existing_count, dtype=float) / existing_count
                        else:
                            prob = current_weights / weight_sum

                        targets = np.random.choice(
                            existing_count,
                            size=num_targets_needed,
                            replace=False,
                            p=prob
                        )

                    for target in targets:
                        edge_nodes.add(int(target))

                edge = frozenset(edge_nodes)
                if edge in edge_set:
                    continue

                edge_set.add(edge)
                self.hypergraph.append(edge)
                edges_created += 1

                # 仅成功加入不同超边后更新旧目标选择计数，随机和偏好分支均计入。
                for target in targets:
                    target = int(target)
                    self.k_counts[target] += 1
                    self.is_selected[target] = True

                # 更新所有参与该超边节点的度
                for node in edge:
                    self.degrees[node] += 1

            # 本批新节点正式成为已有节点
            active_count += new_count


def run_single_simulation(task):
    args, mc_steps, out_steps = unpack_task(task)
    existing_result = read_completed_result(task)
    if existing_result is not None:
        return existing_result
    sim = Simulation(*args, mc_steps=mc_steps, out_steps=out_steps)
    # 主进程统一写 Excel；使用与续跑相同的回读校验。
    result = read_completed_file(sim.result_filename, args, mc_steps, out_steps)
    if result is None:
        raise ValueError(f"新写入的 TXT 未通过完整性校验：{sim.result_filename}")
    return result


SUMMARY_HEADERS = ["G", "N", "m", "mh", "alpha", "p", "R", "r", "final_avg_fc", "txt_file"]


def save_summary_workbook(workbook, filename):
    """临时工作簿完整保存后再替换；TXT 是可恢复汇总的数据源。"""
    temp_filename = f"{filename}.tmp.xlsx"
    try:
        workbook.save(temp_filename)
        with open(temp_filename, 'rb+') as f:
            os.fsync(f.fileno())
        os.replace(temp_filename, filename)
    except PermissionError as exc:
        raise PermissionError(
            f"无法保存汇总，请关闭占用 Excel 的程序并检查写权限后重启。"
            f"已完成 TXT 会自动复用：{filename}"
        ) from exc


def summary_result_key(row):
    if len(row) < len(SUMMARY_HEADERS):
        raise ValueError('汇总行不足十列')
    match = re.search(r'_steps=(\d+)_out=(\d+)\.txt$', str(row[9]))
    if match is None:
        raise ValueError('txt_file 列未包含可识别的 steps/out')
    args, steps, out = unpack_task(
        (row[1], row[4], row[0], row[2], row[3], row[6], row[5],
         int(match.group(1)), int(match.group(2))))
    if not math.isclose(float(row[7]), args[5] / args[2], rel_tol=1e-14, abs_tol=1e-14):
        raise ValueError('r 与 R/g 不一致')
    return args + (steps, out)


def open_summary_workbook(filename):
    """保留历史行及其他工作表，不覆盖无法识别的现有工作簿。"""
    if os.path.isfile(filename):
        workbook = load_workbook(filename)
        if 'Simulation Results' not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f'汇总文件缺少 Simulation Results 工作表，未覆盖：{filename}')
        worksheet = workbook['Simulation Results']
        if [worksheet.cell(1, col).value for col in range(1, 11)] != SUMMARY_HEADERS:
            workbook.close()
            raise ValueError(f'汇总表头与 PGG 十列格式不一致，未覆盖：{filename}')
    else:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = 'Simulation Results'
        worksheet.append(SUMMARY_HEADERS)
        for cell in worksheet[1]:
            cell.fill = PatternFill(fill_type='solid', fgColor='1F4E78')
            cell.font = Font(color='FFFFFF', bold=True)
            cell.alignment = Alignment(horizontal='center', vertical='center')
        worksheet.freeze_panes = 'A2'
        worksheet.auto_filter.ref = 'A1:J1'
        worksheet.sheet_view.showGridLines = False
        for column, width in zip('ABCDEFGHIJ', [8, 10, 8, 8, 12, 10, 10, 10, 18, 80]):
            worksheet.column_dimensions[column].width = width
    row_lookup = {}
    unindexed = 0
    for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if all(value is None for value in row):
            continue
        try:
            row_lookup[summary_result_key(row)] = row_idx
        except (ValueError, TypeError, OverflowError):
            unindexed += 1
    if unindexed:
        print(f'汇总中有 {unindexed} 行无法建立参数索引，已保留原内容。')
    return workbook, worksheet, row_lookup


def append_summary_result(workbook, worksheet, filename, result_row, row_lookup, save=True):
    key = summary_result_key(result_row)
    row_idx = row_lookup.get(key)
    if row_idx is None:
        worksheet.append(result_row)
        row_idx = worksheet.max_row
        row_lookup[key] = row_idx
    else:
        for column_idx, value in enumerate(result_row, start=1):
            worksheet.cell(row=row_idx, column=column_idx, value=value)
    for column_idx in (1, 2, 3, 4):
        worksheet.cell(row=row_idx, column=column_idx).number_format = '0'
    for column_idx in (5, 6, 7, 8):
        worksheet.cell(row=row_idx, column=column_idx).number_format = '0.000'
    worksheet.cell(row=row_idx, column=9).number_format = '0.00000000'
    worksheet.cell(row=row_idx, column=10).number_format = '@'
    worksheet.auto_filter.ref = f'A1:J{worksheet.max_row}'
    if save:
        save_summary_workbook(workbook, filename)


def configure_worker_paths(result_dir, legacy_dirs):
    # Windows spawn 重新导入脚本，显式传递测试或用户设置的输出目录。
    global RESULT_DIR, LEGACY_RESULT_DIRS
    RESULT_DIR = result_dir
    LEGACY_RESULT_DIRS = list(legacy_dirs)


def run_batch(tasks, processes=1):
    """扫描参数、跳过完整 TXT、补齐 Excel，然后运行剩余任务。"""
    normalized = []
    seen = set()
    for task in tasks:
        args, steps, out = unpack_task(task)
        task = args + (steps, out)
        if task not in seen:
            normalized.append(task)
            seen.add(task)
    validate_task_filenames(normalized)
    if isinstance(processes, bool) or int(processes) != processes or processes < 1:
        raise ValueError('processes 必须为正整数')
    summary_filename = old_generator_output_path('PGG_SRH_global_results.xlsx')
    workbook, worksheet, row_lookup = open_summary_workbook(summary_filename)
    skipped_count = 0
    pending_tasks = []
    try:
        for task in tqdm(normalized, desc='检查已有结果'):
            args, steps, out = unpack_task(task)
            check_destination_parameters(
                os.path.join(RESULT_DIR, result_filename(args, steps, out)),
                recording_parameters(args, steps, out))
            result = read_completed_result(task)
            if result is None:
                pending_tasks.append(task)
            else:
                skipped_count += 1
                append_summary_result(workbook, worksheet, summary_filename, result, row_lookup, save=False)
        save_summary_workbook(workbook, summary_filename)
        print(f'结果目录：{RESULT_DIR}')
        print(f'总参数组数：{len(normalized)}，已完成跳过：{skipped_count}，待运行：{len(pending_tasks)}')
        if pending_tasks:
            with mp.Pool(processes=int(processes), initializer=configure_worker_paths,
                         initargs=(os.path.abspath(RESULT_DIR), LEGACY_RESULT_DIRS)) as pool:
                results = pool.imap_unordered(run_single_simulation, pending_tasks)
                for result in tqdm(results, total=len(pending_tasks), desc='运行剩余仿真'):
                    append_summary_result(workbook, worksheet, summary_filename, result, row_lookup)
    finally:
        workbook.close()
    return dict(total=len(normalized), skipped=skipped_count, completed=len(pending_tasks),
                summary_file=summary_filename)


if __name__ == "__main__":
    g_list = [4]
    n = 2000
    m = 1
    mh = 3

    P_list = [0.0, 0.25, 0.5, 0.75, 1.0]
    alpha_list = np.round(np.arange(0.0, 1.001, 0.05), 3)
    
    tasks = []

    for g in g_list:
        for alpha in alpha_list:
            for p in P_list:
                # R 从 0 到 2g，实际步长为 0.05g（保留原设置）
                R_list = [round(i * g * 0.05, 3) for i in range(41)]

                for R in R_list:
                    tasks.append((n, alpha, g, m, mh, R, p))

    processes = 16

    mp.freeze_support()
    stats = run_batch(tasks, processes=processes)
    print("所有仿真已完成！")
    print(f"全局汇总文件：{stats['summary_file']}")
