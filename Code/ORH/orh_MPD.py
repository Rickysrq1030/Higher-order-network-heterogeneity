from tqdm import tqdm
import ast
import math
import os
import random
import multiprocessing as mp
import numpy as np
import scipy.stats as stats
import networkx as nx
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


# 默认在脚本所在文件夹查找和保存结果，不受启动命令所在目录影响。
# 如果旧 txt 在其他目录，请将这里改成该目录的绝对路径。
RESULT_DIR = os.path.dirname(os.path.abspath(__file__))


def format_dist_label(dist_param):
    if isinstance(dist_param, (int, float, np.integer, np.floating)):
        return f"{float(dist_param):.3f}"
    return str(dist_param)


def result_filename(pro_g, n, p, b, dist_param, mc_steps):
    """保持原有文件名格式，以便识别服务器上已经生成的 txt。"""
    pro_g_str = "-".join(f"{x:.3f}" for x in pro_g)
    return (
        f"MPD_ORH_N={n}_proG={pro_g_str}_dist={format_dist_label(dist_param)}_"
        f"p={p:.2f}_b={b:.3f}_steps={mc_steps}.txt"
    )


def unpack_simulation_args(args):
    if len(args) == 6:
        return (*args, 1000000, 100000)
    if len(args) == 8:
        return tuple(args)
    raise ValueError("单次 MPD 仿真参数数量必须为 6 或 8")


def read_completed_result(args):
    """读取已完成的旧版/新版 txt；不存在或未写完整时返回 None。"""
    pro_g, val_g, n, p, b, dist_param, mc_steps, out_steps = unpack_simulation_args(args)
    filename = result_filename(pro_g, n, p, b, dist_param, mc_steps)
    filepath = os.path.join(RESULT_DIR, filename)
    average_prefix = f"最终平均合作率 (最后 {out_steps} 步均值): "
    average_fc = None
    complete_nodes = False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            if f.readline().strip() != filename[:-4]:
                return None
            for line in f:
                if line.startswith(average_prefix):
                    average_fc = float(line[len(average_prefix):].strip())
                elif line.startswith("节点记录="):
                    # 原代码最后写出节点记录。检查列表完整性，防止把中断
                    # 留下的半截 txt 当作已完成任务，也兼容没有完成标记的旧文件。
                    records = ast.literal_eval(line[len("节点记录="):].strip())
                    complete_nodes = (
                        isinstance(records, list)
                        and len(records) == n
                        and all(isinstance(row, list) and len(row) == 5 for row in records)
                    )
    except (FileNotFoundError, UnicodeError, ValueError, SyntaxError):
        return None

    if average_fc is None or not 0.0 <= average_fc <= 1.0 or not complete_nodes:
        return None

    return [
        n, mc_steps, "-".join(f"{x:.3f}" for x in pro_g),
        dist_param, p, b, average_fc
    ]


class Simulation:
    def __init__(
        self,
        pro_g,
        val_g,
        n,
        p,
        b,
        dist_param,
        mc_steps=1000000,
        out_steps=100000
    ):
        self.n = n                  # 节点数
        self.p = p                  # 边策略节点比例
        self.pro_g = list(pro_g)    # 超边规模分布
        self.val_g = list(val_g)    # 超边规模取值，如 [2, 3, 4, 5, 6]
        self.sum_g = [0.0] * len(self.pro_g)
        self.alpha = 1              # 控制边数的系数
        self.b = b                  # 囚徒困境强度

        # 分布标识：Beta 分布使用数值参数，两个人工分布使用文字标签
        self.dist_param = dist_param
        self.dist_label = format_dist_label(dist_param)

        # ---------- 参数检查 ----------
        if len(self.pro_g) != len(self.val_g):
            raise ValueError("pro_g 和 val_g 长度不匹配")

        if len(self.pro_g) == 0:
            raise ValueError("pro_g 和 val_g 不能为空")

        if min(self.pro_g) < 0 or max(self.pro_g) > 1:
            raise ValueError("pro_g 中的概率值必须在 [0, 1] 范围内")

        # ---------- 计算期望超边规模 ----------
        self.expect_g = 0.0
        for i in range(len(self.pro_g)):
            self.expect_g += self.pro_g[i] * self.val_g[i]

        if self.expect_g <= 0:
            raise ValueError("expect_g 必须大于 0")

        # ---------- 根据 expect_g 计算超边数量 ----------
        self.lc = math.floor(self.n / self.expect_g * math.log(self.n))
        self.l = math.floor(self.alpha * self.lc)

        if self.l <= 0:
            raise ValueError("超边数量 self.l 必须大于 0")

        # ---------- 构造累积概率 ----------
        for i in range(len(self.pro_g)):
            if i == 0:
                self.sum_g[i] = self.pro_g[i]
            else:
                self.sum_g[i] = self.pro_g[i] + self.sum_g[i - 1]

        if abs(self.sum_g[-1] - 1.0) > 1e-9:
            raise ValueError(f"pro_g 的累积概率必须为 1.0，当前为 {self.sum_g[-1]}")

        # 防止浮点误差导致最后一个区间无法覆盖 r
        self.sum_g[-1] = 1.0

        # ---------- 为每条超边预先分配确切规模 ----------
        self.g = [0] * self.l

        for edge_idx in range(self.l):
            r = random.random()
            for j in range(len(self.sum_g)):
                if r <= self.sum_g[j]:
                    self.g[edge_idx] = self.val_g[j]
                    break

        self.aver_g = sum(self.g) / self.l

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
        self.edge_c_num = []

        self.aver_fc = 0.0
        self.node_aver_fc = [0.0] * self.n

        # 每条超边一个 delta，后续在 update_node 中按 chosen_edge_idx 调用
        self.delta = [
            ((self.g[i] - 1) + (self.g[i] + 1) * self.b)
            for i in range(self.l)
        ]

        self.all_indices = np.arange(n)

        self.initial()
        self.calc_payoff()
        self.run(mc_steps, out_steps)

    def initial(self):
        # 创建超图结构
        self.generate_hypergraph()

        # set 转 list 后顺序可能改变，因此用 sorted 固定顺序
        self.hypergraph = sorted(self.hypergraph)

        # 重新校准实际超边数量和每条边规模，确保 self.g[edge_idx] 与 hypergraph[edge_idx] 对应
        self.l = len(self.hypergraph)
        self.g = [len(edge) for edge in self.hypergraph]
        self.aver_g = sum(self.g) / self.l

        self.delta = [
            ((g_i - 1) + (g_i + 1) * self.b)
            for g_i in self.g
        ]

        # 检查是否连通
        G = nx.Graph()
        G.add_nodes_from(range(self.n))

        for edge in self.hypergraph:
            for i in range(len(edge)):
                for j in range(i + 1, len(edge)):
                    G.add_edge(edge[i], edge[j])

        self.is_connected = nx.is_connected(G)

        if not self.is_connected:
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
        """
        根据当前策略完整重算收益，用于初始化和最终收益校准。
        演化过程中由 update_payoff() 增量更新。
        合作者收益为 (c_num - 3) * b + (c_num - 1)，c_num=1 时为 -2b。
        """
        self.l = len(self.hypergraph)

        self.aver_payoff = [0.0] * self.n
        self.total_payoff = [0.0] * self.n
        self.edge_c_num = [0] * self.l

        for edge_idx in range(self.l):
            members = self.hypergraph[edge_idx]

            # 第一遍：计算该超边当前合作者数量
            c_num = 0
            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]

                if self.strategy[node_idx][local_idx] == 1:
                    c_num += 1

            self.edge_c_num[edge_idx] = c_num

            # 第二遍：根据 c_num 分配该超边收益
            for node_idx in members:
                local_idx = self.node_edge_map[(node_idx, edge_idx)]
                is_cooperator = self.strategy[node_idx][local_idx] == 1

                if is_cooperator:
                    self.total_payoff[node_idx] += (c_num - 3) * self.b + (c_num - 1)
                else:
                    self.total_payoff[node_idx] += c_num * (self.b + 1)

        # 计算平均收益
        for node_idx in range(self.n):
            s_len = len(self.strategy[node_idx])
            self.aver_payoff[node_idx] = (
                self.total_payoff[node_idx] / s_len if s_len > 0 else 0.0
            )

    def update_payoff(self, node_idx, target_strategy, chosen_edge_idx=None, chosen_local_idx=None):
        """
        增量更新收益。

        node_idx: 被更新策略的节点
        target_strategy: 模仿得到的新策略，0 或 1
        chosen_edge_idx: 如果是边策略节点，只更新这条超边
        chosen_local_idx: chosen_edge_idx 在 node_idx 的策略列表中的局部索引
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
            old_c_num = self.edge_c_num[edge_idx]

            # 1. 扣除该超边旧状态下对所有成员的收益贡献
            for member in members:
                member_local_idx = self.node_edge_map[(member, edge_idx)]
                is_cooperator = self.strategy[member][member_local_idx] == 1

                if is_cooperator:
                    self.total_payoff[member] -= (old_c_num - 3) * self.b + (old_c_num - 1)
                else:
                    self.total_payoff[member] -= old_c_num * (self.b + 1)

            # 2. 修改被更新节点在该超边上的策略
            self.strategy[node_idx][local_idx] = target_strategy

            # 3. 更新该超边当前合作者数量
            new_c_num = old_c_num + target_strategy - old_strategy
            self.edge_c_num[edge_idx] = new_c_num

            # 4. 加回该超边新状态下对所有成员的收益贡献
            for member in members:
                member_local_idx = self.node_edge_map[(member, edge_idx)]
                is_cooperator = self.strategy[member][member_local_idx] == 1

                if is_cooperator:
                    self.total_payoff[member] += (new_c_num - 3) * self.b + (new_c_num - 1)
                else:
                    self.total_payoff[member] += new_c_num * (self.b + 1)

            # 5. 只更新该超边内成员的平均收益
            for member in members:
                s_len = len(self.strategy[member])
                self.aver_payoff[member] = (
                    self.total_payoff[member] / s_len if s_len > 0 else 0.0
                )

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

        delta = self.delta[chosen_edge_idx]

        if delta <= 0:
            return

        probability = max(
            0.0,
            min(1.0, (target_payoff - self.aver_payoff[node_idx]) / delta)
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
        f.write(f"控制超边数量参数alpha={self.alpha}\n")
        f.write(f"基准超边数量lc={self.lc}\n")
        f.write(f"实际超边数量={self.l}\n")
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
                round(self.aver_payoff[node_idx], 8),
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

        filename = os.path.join(
            RESULT_DIR,
            result_filename(self.pro_g, self.n, self.p, self.b, self.dist_param, mc_steps)
        )
        temp_filename = f"{filename}.tmp"

        # 先写临时文件，正常结束后才生成正式 txt。重启时忽略残留的 .tmp。
        with open(temp_filename, "w", encoding="utf-8", buffering=1024 * 1024) as f:
            # 第一行记录完整实验参数
            f.write(
                f"MPD_ORH_N={self.n}_proG={pro_g_str}_dist={self.dist_label}_"
                f"p={self.p:.2f}_b={self.b:.3f}_steps={mc_steps}\n"
            )

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


def run_single_simulation(args):
    # 在创建超图前检查，跳过已完成参数的全部计算。
    existing_result = read_completed_result(args)
    if existing_result is not None:
        return existing_result

    (
        pro_g, val_g, n, p, b, dist_param, mc_steps, out_steps
    ) = unpack_simulation_args(args)

    sim = Simulation(
        pro_g,
        val_g,
        n,
        p,
        b,
        dist_param,
        mc_steps=mc_steps,
        out_steps=out_steps
    )

    pro_g_str = "-".join(f"{x:.3f}" for x in sim.pro_g)

    # 返回一行全局汇总结果，由主进程写入 Excel
    return [
        sim.n,
        sim.mc_steps,
        pro_g_str,
        sim.dist_param,
        sim.p,
        sim.b,
        sim.aver_fc
    ]


SUMMARY_HEADERS = [
    "N",
    "steps",
    "proG",
    "dist",
    "p",
    "b",
    "final_avg_fc"
]


def save_summary_workbook(workbook, filename):
    """以临时文件替换方式保存，降低程序中断造成文件损坏的风险。"""
    temp_filename = f"{filename}.tmp.xlsx"
    workbook.save(temp_filename)
    os.replace(temp_filename, filename)


def create_summary_workbook(filename):
    """创建新的 MPD 全局仿真结果 Excel 文件。"""
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
    worksheet.auto_filter.ref = "A1:G1"
    worksheet.sheet_view.showGridLines = False

    column_widths = {
        "A": 10,
        "B": 14,
        "C": 38,
        "D": 20,
        "E": 10,
        "F": 12,
        "G": 18
    }

    for column, width in column_widths.items():
        worksheet.column_dimensions[column].width = width

    save_summary_workbook(workbook, filename)
    return workbook, worksheet


def summary_result_key(result_row):
    """使用与 txt 文件名相同的精度匹配汇总行。"""
    return (
        int(result_row[0]), int(result_row[1]), str(result_row[2]),
        format_dist_label(result_row[3]),
        f"{float(result_row[4]):.2f}", f"{float(result_row[5]):.3f}"
    )


def open_summary_workbook(filename):
    """保留已有汇总，并建立参数到行号的索引，防止重启后重复追加。"""
    if os.path.isfile(filename):
        workbook = load_workbook(filename)
        if "Simulation Results" not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"汇总文件缺少 Simulation Results 工作表：{filename}")
        worksheet = workbook["Simulation Results"]
        if [cell.value for cell in worksheet[1]] != SUMMARY_HEADERS:
            workbook.close()
            raise ValueError(f"汇总文件表头与当前代码不一致：{filename}")
    else:
        workbook, worksheet = create_summary_workbook(filename)

    row_lookup = {}
    for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if all(value is None for value in row):
            continue
        row_lookup[summary_result_key(row)] = row_idx
    return workbook, worksheet, row_lookup


def append_summary_result(workbook, worksheet, filename, result_row, row_lookup, save=True):
    """新增或更新一个参数的结果；默认立即保存 Excel。"""
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
    worksheet.cell(row=row_idx, column=3).number_format = "@"

    if isinstance(result_row[3], (int, float, np.integer, np.floating)):
        worksheet.cell(row=row_idx, column=4).number_format = "0.000"
    else:
        worksheet.cell(row=row_idx, column=4).number_format = "@"

    worksheet.cell(row=row_idx, column=5).number_format = "0.000"
    worksheet.cell(row=row_idx, column=6).number_format = "0.000"
    worksheet.cell(row=row_idx, column=7).number_format = "0.00000000"

    worksheet.auto_filter.ref = f"A1:G{worksheet.max_row}"
    if save:
        save_summary_workbook(workbook, filename)


def calc_pro_g(val_gs, alpha, beta):
    """
    使用 Beta 分布生成离散概率分布，并确保严格符合博弈仿真要求：
    1. 所有概率 > 0
    2. 总和严格等于 1.0
    3. 输出为纯 float 类型
    """
    low, high = min(val_gs), max(val_gs)
    if high == low:
        return [1.0]

    # 映射到 [0, 1]
    norm_vals = [(v - low) / (high - low) for v in val_gs]

    # 1. 计算原始 PDF 值并加入微小偏移 (eps) 防止出现 0
    eps_boundary = 1e-9
    pro_gs_raw = []
    for x in norm_vals:
        safe_x = max(eps_boundary, min(1.0 - eps_boundary, x))
        # 加入一个保底值 1e-5，确保 round(3) 后至少有 0.001
        p = stats.beta.pdf(safe_x, alpha, beta) + 1e-5
        pro_gs_raw.append(float(p))

    # 2. 初步归一化并保留三位小数
    sum_p = sum(pro_gs_raw)
    pro_gs = [round(p / sum_p, 3) for p in pro_gs_raw]

    # 3. 稳健的误差修正逻辑
    diff = round(1.0 - sum(pro_gs), 3)

    # 找到概率最大的项的索引，将误差补偿到最大项上
    max_idx = pro_gs.index(max(pro_gs))
    pro_gs[max_idx] = round(pro_gs[max_idx] + diff, 3)

    return [float(p) for p in pro_gs]


def build_distribution_configs(val_gs):
    """构造论文中使用的五种超边规模分布。"""
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
    n = 2000
    val_gs = [2, 3, 4, 5, 6]

    P_list = np.round(np.arange(0.0, 1.001, 0.25), 3)
    b_list = np.round(np.arange(0.0, 1.01, 0.025), 3)

    # 五种超边规模分布：两个直接指定，三个由对称 Beta 分布生成
    distribution_configs = build_distribution_configs(val_gs)

    tasks = []

    for dist_param, pro_g in distribution_configs:
        for p in P_list:
            for b in b_list:
                tasks.append((
                    pro_g,
                    val_gs,
                    n,
                    float(p),
                    float(b),
                    dist_param
                ))

    processes = 32
    summary_filename = os.path.join(RESULT_DIR, "MPD_ORH_global_results.xlsx")

    # 只由主进程维护 Excel，避免多个工作进程同时写文件造成损坏。
    # 读取已有汇总，不在重启时清空它；txt 中已有的结果也会补入汇总。
    summary_workbook, summary_worksheet, summary_row_lookup = open_summary_workbook(
        summary_filename
    )

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
                    summary_workbook,
                    summary_worksheet,
                    summary_filename,
                    existing_result,
                    summary_row_lookup,
                    save=False
                )

        save_summary_workbook(summary_workbook, summary_filename)
        print(f"结果目录：{RESULT_DIR}")
        print(f"总参数组数：{len(tasks)}，已完成跳过：{skipped_count}，待运行：{len(pending_tasks)}")

        if pending_tasks:
            with mp.Pool(processes=min(processes, len(pending_tasks))) as pool:
                # 任意一个仿真完成后，立即将该结果返回主进程。
                result_iterator = pool.imap_unordered(
                    run_single_simulation,
                    pending_tasks
                )

                for result_row in tqdm(
                    result_iterator,
                    total=len(pending_tasks),
                    desc="运行剩余仿真"
                ):
                    append_summary_result(
                        summary_workbook,
                        summary_worksheet,
                        summary_filename,
                        result_row,
                        summary_row_lookup
                    )
    finally:
        summary_workbook.close()

    print("\n" + "=" * 30)
    print("所有仿真已完成！")
    print(f"全局汇总文件：{summary_filename}")
