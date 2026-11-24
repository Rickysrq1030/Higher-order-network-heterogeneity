import random
import numpy as np
from tqdm import tqdm
import multiprocessing as mp
import networkx as nx
import math


class Simulation:
    def __init__(self, n, alpha, g, R, p):
        self.n = n              # 节点数
        self.alpha = alpha      # 控制边数
        self.g = g              # 超边规模
        self.R = R              # 公共品放大倍数
        self.p = p              # 边策略节点概率

        self.c = 1.0            # 合作者贡献成本
        self.r = self.R / self.g  # reduced synergy factor

        self.lc = math.floor(self.n / self.g * math.log(self.n))
        self.l = math.floor(self.alpha * self.lc)

        self.hypergraph = set()
        self.neighbor = [[] for _ in range(self.n)]
        self.node_type = []
        self.strategy = [[] for _ in range(self.n)]
        self.node_edge_map = {}

        self.cnt_ns = 0.0       # 点策略合作者计数
        self.cnt_ls = 0.0       # 边策略合作频率计数

        self.total_payoff = [0.0] * self.n
        self.aver_payoff = [0.0] * self.n
        self.edge_c_num = []    # 每条超边当前合作者数量

        self.aver_fc = 0.0
        self.node_aver_fc = np.zeros(self.n, dtype=float)   #记录每个节点在最后 out_steps 步中的平均合作水平

        # 公共品博弈下的最大收益差归一化项
        # 与原 URH.py 中 PGG 的 delta 逻辑保持一致
        self.delta = (1 + (self.g - 2) * self.r) if self.r < 1 else (self.g * self.r - 1)

        self.all_indices = np.arange(n)

        self.initial()
        self.calc_payoff()
        self.run(1000000, 100000)

    def initial(self):
        # 创建超图结构
        self.generate_hypergraph()
        self.hypergraph = list(self.hypergraph)

        # 检查是否连通
        G = nx.Graph()
        G.add_nodes_from(range(self.n))

        for edge in self.hypergraph:
            for i in range(len(edge)):
                for j in range(i + 1, len(edge)):
                    G.add_edge(edge[i], edge[j])

        self.is_connected = nx.is_connected(G)

        # 构造邻居矩阵和 O(1) 局部策略索引映射
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

    def calc_payoff(self):
        """
        初始化公共品博弈收益。
        后续策略变化后，不再全局重算收益，而是由 update_payoff() 增量更新。

        公共品博弈收益：
        - 每个合作者贡献成本 c；
        - 当前超边中共有 c_num 个合作者；
        - 公共池总收益为 c_num * c * R；
        - 平均分给超边内所有 g 个成员；
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

    def run(self, mc_steps, out_steps):
        filename = (
            f"G={self.g}_N={self.n}_alpha={self.alpha:.3f}_"
            f"p={self.p:.3f}_R={self.R:.3f}_r={self.r:.3f}_steps={mc_steps}.txt"
        )

        with open(filename, "w", encoding="utf-8", buffering=1024 * 1024) as f:
            f.write(
                f"G={self.g}_N={self.n}_alpha={self.alpha:.3f}_"
                f"p={self.p:.3f}_R={self.R:.3f}_r={self.r:.3f}_steps={mc_steps}\n"
                f"graph={self.hypergraph}\n"
            )

            self.aver_fc = 0.0
            last_sum = 0.0

            for step in range(1, mc_steps + 1):
                # 每个 MCS 中随机有放回更新 n 个节点
                for _ in range(self.n):
                    node_idx = random.randint(0, self.n - 1)
                    self.update_node(node_idx)

                fc = self.calc_cooperate_rate()

                # 每步记录一次合作率
                f.write(f"{step}, 合作率: {fc:.4f}\n")

                # 吸收态判断
                if fc <= 1e-12 or fc >= 1.0 - 1e-12:
                    f.write(f"进入吸收态，step={step}, 合作率为{fc:.4f}\n")
                    last_sum = fc * out_steps

                    self.node_aver_fc[:] = 0.0
                    self.calc_cooperate_rate_per_node()
                    self.node_aver_fc *= out_steps
                    break

                # 统计最后 out_steps 步的平均合作率
                if step > mc_steps - out_steps:
                    last_sum += fc
                    self.calc_cooperate_rate_per_node()

            self.aver_fc = last_sum / out_steps
            self.node_aver_fc /= out_steps
            f.write(f"\n后 {out_steps} 步合作率 {self.aver_fc:.4f}\n")
            f.write(f"\n后 {out_steps} 步合作水平:\n")
            np.savetxt(
                f,
                self.node_aver_fc.reshape(1, -1),
                fmt="%.6f",
                delimiter=" "
            )

    def generate_hypergraph(self):
        unchosen_nodes = list(range(self.n))
        random.shuffle(unchosen_nodes)

        while len(self.hypergraph) < self.l:
            edge = []
            chosen_node = set()

            # 每条超边包含 self.g 个不同节点
            for _ in range(self.g):
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
            self.hypergraph.add(edge)

    


def run_single_simulation(args):
    n, alpha, g, R, p = args
    sim = Simulation(n, alpha, g, R, p)
    return sim.aver_fc


if __name__ == "__main__":
    g_list = [5]
    n = 2000

    P_list = np.round(np.arange(0.0, 1.001, 0.05), 3)
    alpha_list = [1]

    tasks = []

    for g in g_list:
        for p in P_list:
            for alpha in alpha_list:
                # R 从 0 到 2g，步长为 0.025g
                R_list = [round(i * g * 0.05, 3) for i in range(41)]

                for R in R_list:
                    tasks.append((n, alpha, g, R, p))

    processes = 32

    with mp.Pool(processes=processes) as pool:
        final_results = list(tqdm(pool.imap(run_single_simulation, tasks), total=len(tasks)))

    print("\n" + "=" * 30)
    print("所有仿真已完成！")