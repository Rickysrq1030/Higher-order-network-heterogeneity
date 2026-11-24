import random
from math import comb
import os
import numpy as np
from tqdm import tqdm
import multiprocessing as mp
import networkx as nx
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


'''
MPD SRH：旧图生成方法副本
基于同目录现用 simulation，仅替换构图方法及其状态变量。
m 为每批新节点数，mh 为每批超边数，末批允许少于 m 个新节点。
从 g 个节点的一条超边开始；每条候选超边独立选择一次随机/偏好分支。
目标仅从已有节点选择；未被选中过的节点权重为 3，否则为旧目标选择计数。
随机和偏好分支均更新计数，重复候选不更新。
博弈、扫描参数、记录内容沿用现用文件；结果写入脚本旁 old_generator_results。
'''

def old_generator_output_path(filename):
    """旧方法结果固定写入本脚本旁的独立目录，保留原文件名和格式。"""
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "old_generator_results")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, filename)


class Simulation:
    def __init__(
        self,
        n,
        alpha,
        g,
        m,
        mh,
        b,
        p,
        mc_steps=1000000,
        out_steps=100000
    ):
        self.n = n              # 节点数
        self.alpha = alpha      # 控制连接方式
        self.g = g              # 边的规模
        self.m = m              # 每批新节点数，末批允许不足 m 个
        self.mh = mh            # 每一步创建 mh 条超边
        self.b = b              # 困境强度
        self.p = p              # 边策略节点概率

        if self.n < self.g:
            raise ValueError("需要满足 n >= g")

        if not (1 <= self.m < self.g):
            raise ValueError("需要满足 1 <= m < g，因为每条边还需要选取 g-m 个目标节点")

        if self.mh <= 0:
            raise ValueError("mh 必须大于 0")

        if not (0.0 <= self.alpha <= 1.0):
            raise ValueError("alpha 必须在 [0, 1] 内")

        self.m0 = self.g       # 旧方法从 g 个节点的一条超边开始

        # 列表保留超边编号；生成阶段通过集合检查保证超边不重复。
        self.hypergraph = []

        self.neighbor = [[] for _ in range(self.n)]
        self.node_type = []
        self.strategy = [[] for _ in range(self.n)]
        self.node_edge_map = {}     # 邻居映射

        self.cnt_ns = 0.0           # 点策略合作者计数
        self.cnt_ls = 0.0           # 边策略合作频率计数

        self.total_payoff = [0.0] * self.n
        self.aver_payoff = [0.0] * self.n
        self.edge_c_num = []        # 每条超边当前的合作者数量

        self.degrees = np.zeros(n, dtype=np.int64)
        self.k_counts = np.zeros(n, dtype=np.int64)  # 所有成功的旧目标选择次数
        self.is_selected = np.zeros(n, dtype=bool)

        self.aver_fc = 0.0
        self.node_aver_fc = [0.0] * self.n
        self.delta = (self.g - 1) + (self.g + 1) * self.b

        # 预存所有节点的索引，避免重复创建 range 对象
        self.all_indices = np.arange(n)

        self.initial()
        self.l = len(self.hypergraph)
        self.calc_payoff()
        self.run(mc_steps, out_steps)

    def initial(self):
        # 创建超图结构
        self.generate_hypergraph()

        # 检查是否连通
        G = nx.Graph()
        G.add_nodes_from(range(self.n))

        for edge in self.hypergraph:
            edge = list(edge)
            for i in range(len(edge)):
                for j in range(i + 1, len(edge)):
                    G.add_edge(edge[i], edge[j])

        self.is_connected = nx.is_connected(G)
        if not self.is_connected:
            print("Not Connected")

        # 构造邻居矩阵
        self.neighbor = [[] for _ in range(self.n)]
        self.node_edge_map = {}

        for i, edge in enumerate(self.hypergraph):
            for node in edge:
                self.neighbor[node].append(i)
                # 记录 (节点ID, 超边ID) -> 局部的策略索引
                self.node_edge_map[(node, i)] = len(self.neighbor[node]) - 1

        # 节点类型
        self.node_type = [
            1 if random.random() < self.p else 0
            for _ in range(self.n)
        ]

        # 分配节点策略
        for node_idx in range(self.n):
            num_neighbors = len(self.neighbor[node_idx])

            if self.node_type[node_idx] == 0:
                # 点策略节点，所有策略相同
                strategy = random.randint(0, 1)
                self.strategy[node_idx] = num_neighbors * [strategy]

                if strategy == 1:
                    self.cnt_ns += 1.0

            else:
                # 边策略节点，不同超边可以采取不同策略
                for _ in range(num_neighbors):
                    strategy = random.randint(0, 1)
                    self.strategy[node_idx].append(strategy)

                    if strategy == 1:
                        self.cnt_ls += 1.0 / num_neighbors

    def calc_cooperate_rate(self, node_fc_sum=None):
        """
        计算当前全局合作率。

        如果传入 node_fc_sum，则同时累加每个节点当前的合作率，
        用于计算最后 out_steps 步内的逐节点时间平均合作率。
        """
        self.cnt_ls = 0.0
        self.cnt_ns = 0.0

        for node_idx in range(self.n):
            num_edges = len(self.strategy[node_idx])

            if num_edges == 0:
                node_fc = 0.0
            elif self.node_type[node_idx] == 0:
                node_fc = float(self.strategy[node_idx][0])
                self.cnt_ns += node_fc
            else:
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
        # 根据当前策略完整重算收益；演化过程中由 update_payoff 增量更新。
        # 合作者统一使用 (c_num - 3) * b + (c_num - 1)，c_num=1 时为 -2b。
        self.aver_payoff = [0.0] * self.n
        self.total_payoff = [0.0] * self.n
        self.edge_c_num = [0] * self.l

        for edge_idx in range(self.l):
            members = self.hypergraph[edge_idx]

            # 第一遍循环：计算合作者数量
            c_num = 0
            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]
                if self.strategy[node_idx][local_idx] == 1:
                    c_num += 1

            self.edge_c_num[edge_idx] = c_num

            # 第二遍循环：分配收益
            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]
                is_cooperator = (self.strategy[node_idx][local_idx] == 1)

                if is_cooperator:
                    self.total_payoff[node_idx] += (c_num - 3) * self.b + (c_num - 1)
                else:
                    self.total_payoff[node_idx] += c_num * (self.b + 1)

        # 计算平均收益，增加防除零保护
        for node_idx in range(self.n):
            s_len = len(self.strategy[node_idx])
            self.aver_payoff[node_idx] = self.total_payoff[node_idx] / s_len if s_len > 0 else 0.0

    def update_payoff(self, node_idx, target_strategy, chosen_edge_idx=None, chosen_local_idx=None):
        """
        增量更新收益。

        node_idx: 被更新策略的节点
        target_strategy: 模仿得到的新策略，0 或 1
        chosen_edge_idx: 如果是边策略节点，只更新这条超边
        chosen_local_idx: chosen_edge_idx 在 node_idx 的策略列表中的局部索引
        """

        # 边策略节点：只影响当前被选中的一条超边
        if self.node_type[node_idx] == 1:
            if chosen_edge_idx is None or chosen_local_idx is None:
                raise ValueError("边策略节点更新时必须提供 chosen_edge_idx 和 chosen_local_idx")
            affected_edges = [(chosen_local_idx, chosen_edge_idx)]

        # 点策略节点：该节点在所有参与超边上的策略同步变化
        else:
            if len(self.strategy[node_idx]) == 0 or self.strategy[node_idx][0] == target_strategy:
                return

            affected_edges = [
                (local_idx, edge_idx)
                for local_idx, edge_idx in enumerate(self.neighbor[node_idx])
            ]

        for local_idx, edge_idx in affected_edges:
            old_strategy = self.strategy[node_idx][local_idx]

            # 如果该局部策略没有变化，则该超边收益不变
            if old_strategy == target_strategy:
                continue

            members = self.hypergraph[edge_idx]
            old_c_num = self.edge_c_num[edge_idx]

            # 1. 扣除该超边旧状态下对所有成员的收益贡献
            for member in members:
                member_local_idx = self.node_edge_map[(member, edge_idx)]
                is_cooperator = (self.strategy[member][member_local_idx] == 1)

                if is_cooperator:
                    self.total_payoff[member] -= (old_c_num - 3) * self.b + (old_c_num - 1)
                else:
                    self.total_payoff[member] -= old_c_num * (self.b + 1)

            # 2. 修改被更新节点在该超边上的策略
            self.strategy[node_idx][local_idx] = target_strategy

            # 3. 更新该超边的合作者数量
            new_c_num = old_c_num + target_strategy - old_strategy
            self.edge_c_num[edge_idx] = new_c_num

            # 4. 加回该超边新状态下对所有成员的收益贡献
            for member in members:
                member_local_idx = self.node_edge_map[(member, edge_idx)]
                is_cooperator = (self.strategy[member][member_local_idx] == 1)

                if is_cooperator:
                    self.total_payoff[member] += (new_c_num - 3) * self.b + (new_c_num - 1)
                else:
                    self.total_payoff[member] += new_c_num * (self.b + 1)

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

        # 列表下标为超边编号，每个元组为该超边的成员，成员集合互不相同。
        f.write(f"超边列表={self.hypergraph}\n")

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

            node_records.append([
                round(self.aver_payoff[node_idx], 8),
                int(self.node_type[node_idx]),
                round(average_edge_size, 8),
                hyperdegree,
                round(self.node_aver_fc[node_idx], 8)
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
        f.write(f"节点记录={node_records}\n")

    def run(self, mc_steps, out_steps):
        if out_steps > mc_steps:
            raise ValueError("out_steps 不能大于 mc_steps")

        self.mc_steps = mc_steps
        self.out_steps = out_steps

        filename = (
            f"MPD_SRH_G={self.g}_N={self.n}_m={self.m}_mh={self.mh}_"
            f"alpha={self.alpha:.2f}_p={self.p:.2f}_b={self.b:.3f}_"
            f"steps={mc_steps}_out={out_steps}.txt"
        )
        filename = old_generator_output_path(filename)
        self.result_filename = filename

        with open(
            filename,
            "w",
            encoding="utf-8",
            buffering=1024 * 1024
        ) as f:
            # 第一行记录完整实验参数，便于程序批量检索结果文件。
            f.write(
                f"MPD_SRH_G={self.g}_N={self.n}_m={self.m}_mh={self.mh}_"
                f"alpha={self.alpha:.2f}_p={self.p:.2f}_b={self.b:.3f}_"
                f"steps={mc_steps}_out_steps={out_steps}\n"
            )

            self.write_network_info(f)
            f.write("\n演化过程:\n")

            self.aver_fc = 0.0
            last_sum = 0.0
            node_fc_sum = [0.0] * self.n

            for step in range(1, mc_steps + 1):
                # 每个 MCS 中随机、有放回地更新 n 个节点。
                for _ in range(self.n):
                    node_idx = random.randint(0, self.n - 1)
                    self.update_node(node_idx)

                in_average_window = step > mc_steps - out_steps

                if in_average_window:
                    fc = self.calc_cooperate_rate(node_fc_sum)
                else:
                    fc = self.calc_cooperate_rate()

                if step % 10000 == 0:
                    f.write(
                        f"进度: {step}/{mc_steps}, 合作率: {fc:.4f}\n"
                    )
                    f.flush()

                if fc <= 1e-12 or fc >= 1.0 - 1e-12:
                    f.write(
                        f"进入吸收态，step={step}, 合作率为{fc:.4f}\n"
                    )

                    # 假定进入吸收态后状态保持不变。
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
            f.flush()

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

                edge = tuple(sorted(edge_nodes))
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


def run_single_simulation(args):
    if len(args) == 7:
        n, alpha, g, m, mh, b, p = args
        mc_steps = 1000000
        out_steps = 100000
    elif len(args) == 9:
        n, alpha, g, m, mh, b, p, mc_steps, out_steps = args
    else:
        raise ValueError("单次 MPD-SRH 仿真参数数量必须为 7 或 9")

    sim = Simulation(
        n,
        alpha,
        g,
        m,
        mh,
        b,
        p,
        mc_steps=mc_steps,
        out_steps=out_steps
    )

    # 工作进程只返回普通数据；Excel 始终由主进程写入。
    return [
        sim.g,
        sim.n,
        sim.m,
        sim.mh,
        float(sim.alpha),
        float(sim.p),
        float(sim.b),
        sim.aver_fc,
        sim.result_filename
    ]


SUMMARY_HEADERS = [
    "G",
    "N",
    "m",
    "mh",
    "alpha",
    "p",
    "b",
    "final_avg_fc",
    "txt_file"
]


def save_summary_workbook(workbook, filename):
    """先写临时文件再替换正式文件，降低程序中断造成损坏的风险。"""
    temp_filename = f"{filename}.tmp.xlsx"
    workbook.save(temp_filename)
    os.replace(temp_filename, filename)


def create_summary_workbook(filename):
    """创建新的 MPD-SRH 全局仿真结果 Excel 文件。"""
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
    worksheet.auto_filter.ref = "A1:I1"
    worksheet.sheet_view.showGridLines = False

    column_widths = {
        "A": 8,
        "B": 10,
        "C": 8,
        "D": 8,
        "E": 12,
        "F": 10,
        "G": 10,
        "H": 18,
        "I": 80
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[column].width = width

    save_summary_workbook(workbook, filename)
    return workbook, worksheet


def append_summary_result(workbook, worksheet, filename, result_row):
    """追加一个已完成任务的结果，并立即安全保存 Excel。"""
    worksheet.append(result_row)
    row_idx = worksheet.max_row

    for column_idx in (1, 2, 3, 4):
        worksheet.cell(row=row_idx, column=column_idx).number_format = "0"

    for column_idx in (5, 6, 7):
        worksheet.cell(row=row_idx, column=column_idx).number_format = "0.000"

    worksheet.cell(row=row_idx, column=8).number_format = "0.00000000"
    worksheet.cell(row=row_idx, column=9).number_format = "@"

    worksheet.auto_filter.ref = f"A1:I{row_idx}"
    save_summary_workbook(workbook, filename)


if __name__ == "__main__":
    g_list = [4]
    n = 2000
    m_list = [1, 2, 3]
    mh = 3

    P_list = [0.0, 0.25, 0.5, 0.75, 1.0]

    # 固定使用纯偏好连接，并比较 m=1、2、3 三种情况。
    alpha_list = [0.0]

    b_list = np.round(np.arange(0.0, 1.01, 0.025), 3)

    tasks = []

    for g in g_list:
        for m in m_list:
            if m >= g:
                raise ValueError(f"当前设置 m={m}, g={g} 不合法，需要满足 m < g")

            for alpha in alpha_list:
                for p in P_list:
                    for b in b_list:
                        tasks.append((n, alpha, g, m, mh, b, p))

    processes = 11
    summary_filename = old_generator_output_path("MPD_SRH_global_results.xlsx")

    # 只由主进程维护 Excel，避免多个工作进程同时写文件造成损坏。
    # 每次启动程序都会新建并覆盖同名的全局汇总文件。
    summary_workbook, summary_worksheet = create_summary_workbook(
        summary_filename
    )

    try:
        with mp.Pool(processes=processes) as pool:
            # 任意仿真完成后立即返回并写入汇总文件。
            result_iterator = pool.imap_unordered(
                run_single_simulation,
                tasks
            )

            for result_row in tqdm(
                result_iterator,
                total=len(tasks)
            ):
                append_summary_result(
                    summary_workbook,
                    summary_worksheet,
                    summary_filename,
                    result_row
                )
    finally:
        summary_workbook.close()

    print("\n" + "=" * 30)
    print("所有仿真已完成！")
    print(f"全局汇总文件：{summary_filename}")
