import random
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter
from tqdm import tqdm
import multiprocessing as mp
import networkx as nx
import math

import ast
import json
import os
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


# 仅用于存储：默认结果目录为脚本所在文件夹，与启动命令所在目录无关。
RESULT_DIR = os.path.dirname(os.path.abspath(__file__))
# 额外旧结果目录；同时自动检查 RESULT_DIR 和本次启动目录。
# 示例：LEGACY_RESULT_DIRS = [r"D:\old_results"]
LEGACY_RESULT_DIRS = []
RECORD_VERSION = 1


def result_filename(n, alpha, g, b, p, mc_steps):
    """保留 MPD v1 原有文件名，兼容已完成的旧 TXT。"""
    return f"G={g}_N={n}_alpha={alpha:.1f}_p={p:.3f}_b={b:.3f}_steps={mc_steps}.txt"


def recording_parameters(args, mc_steps, out_steps):
    n, alpha, g, b, p = args
    return dict(network="URH", n=int(n), alpha=float(alpha), g=int(g),
                b=float(b), p=float(p), mc_steps=int(mc_steps), out_steps=int(out_steps))


def make_summary_row(args, mc_steps, out_steps, average_fc, record_kind, filepath):
    n, alpha, g, b, p = args
    return [int(n), int(mc_steps), int(out_steps), int(g), float(alpha),
            float(p), float(b), float(average_fc), record_kind, os.path.abspath(filepath)]


def valid_node_records(records, n):
    """校验节点列表完整性，避免把半截记录当成完成结果。"""
    if not isinstance(records, list) or len(records) != n:
        return False
    for row in records:
        if not isinstance(row, list) or len(row) != 5:
            return False
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in row):
            return False
        if row[1] not in (0, 1) or row[2] < 0 or row[3] < 0 or int(row[3]) != row[3]:
            return False
        if not 0.0 <= row[4] <= 1.0:
            return False
    return True


def read_completed_file(filepath, args, mc_steps, out_steps):
    """新版需完整节点记录和完成标记；原版用最后写出的全局均值判定。"""
    n, alpha, g, b, p = args
    filename = result_filename(n, alpha, g, b, p, mc_steps)
    average_prefix = f"最终平均合作率 (最后 {out_steps} 步均值): "
    average_fc = None
    version = None
    parameters = None
    complete_nodes = False
    complete_network = False
    new_record_seen = False
    last_nonempty_line = ""

    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            if f.readline().strip() != filename[:-4]:
                return None
            for line in f:
                # 原版和新版的每个完整记录行均以换行符结束。
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
                    new_record_seen = True
                    complete_network = stripped.startswith("超边列表=[") and stripped.endswith("]")
                elif line.startswith("节点记录="):
                    new_record_seen = True
                    records = ast.literal_eval(line.split("=", 1)[1].strip())
                    complete_nodes = valid_node_records(records, n)
                elif line.startswith("记录完成="):
                    new_record_seen = True
    except (FileNotFoundError, UnicodeError, ValueError, SyntaxError, TypeError, OverflowError):
        return None

    if average_fc is None or not math.isfinite(average_fc) or not 0.0 <= average_fc <= 1.0:
        return None
    if new_record_seen:
        if (version != RECORD_VERSION
                or parameters != recording_parameters(args, mc_steps, out_steps)
                or not complete_nodes or not complete_network
                or last_nonempty_line != "记录完成=1"):
            return None
        record_kind = "完整记录"
    else:
        # 老文件没有精确参数元数据，只有原文件名精度内的参数可以安全复用。
        if (float(alpha) != float(f"{alpha:.1f}")
                or float(p) != float(f"{p:.3f}")
                or float(b) != float(f"{b:.3f}")
                or not last_nonempty_line.startswith(average_prefix)):
            return None
        record_kind = "旧版仅全局结果"

    return make_summary_row(args, mc_steps, out_steps, average_fc, record_kind, filepath)


def read_completed_result(args, mc_steps=1000000, out_steps=100000):
    """在创建网络前按参数查找完成记录；忽略 .tmp 文件。"""
    filename = result_filename(*args, mc_steps)
    directories = [RESULT_DIR, *LEGACY_RESULT_DIRS, os.getcwd()]
    visited = set()
    legacy_result = None
    for directory in directories:
        directory = os.path.abspath(directory)
        identity = os.path.normcase(directory)
        if identity in visited:
            continue
        visited.add(identity)
        result = read_completed_file(os.path.join(directory, filename), args, mc_steps, out_steps)
        if result is not None:
            if result[8] == "完整记录":
                return result
            if legacy_result is None:
                legacy_result = result
    return legacy_result


class Simulation:
    def __init__(self, n, alpha, g, b, p):
        self.n = n              #节点数
        self.alpha = alpha      #控制边数
        self.g = g              #边的规模
        self.b = b              #困境强度
        self.p = p              #边策略节点概率

        self.lc = math.floor(self.n / self.g * math.log(self.n))
        self.l = math.floor(self.alpha * self.lc)
        self.hypergraph = set()     #超边结构存储为list，更高效
        self.neighbor = [[] for _ in range(self.n)]
        self.node_type = []
        self.strategy = [[] for _ in range(self.n)]
        self.node_edge_map = {}     #邻居映射
        self.cnt_ns = 0.0  # 点策略合作者计数
        self.cnt_ls = 0.0  # 边策略合作频率计数
        self.total_payoff = [0.0] * self.n     #每个节点的总收益
        self.aver_payoff = [0.0] * self.n   #每个节点的平均收益
        self.edge_c_num = []                #每条超边当前的合作者数量
        self.aver_fc = 0.0
        self.delta = (self.g - 1) + (self.g + 1) * self.b 
        # 预存所有节点的索引，避免重复创建 range 对象
        self.all_indices = np.arange(n)

        self.initial()
        self.calc_payoff()
        self.run(1000000,100000)

    def initial(self):
        #创建超图结构
        self.generate_hypergraph()
        self.hypergraph = list(self.hypergraph)     #将set转换成list，以便后续提速

        # 检查是否连通
        G = nx.Graph()
        G.add_nodes_from(range(self.n))

        for edge in self.hypergraph:
            for i in range(len(edge)):
                for j in range(i + 1, len(edge)):
                    G.add_edge(edge[i], edge[j])

        self.is_connected = nx.is_connected(G)

        #构造邻居矩阵
        for i, edge in enumerate(self.hypergraph):
            for node in edge:
                self.neighbor[node].append(i)
                # 记录 (节点ID, 超边ID) -> 局部的策略索引
                self.node_edge_map[(node, i)] = len(self.neighbor[node]) - 1

        #节点类型
        self.node_type = [1 if random.random() < self.p else 0 for _ in range(self.n)]  # 边策略节点为1，点策略节点为0

        #分配节点策略
        for node_idx in range(self.n):
            num_neighbors = len(self.neighbor[node_idx])
            if self.node_type[node_idx] == 0:   #点策略节点，所有策略相同
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

    def calc_cooperate_rate(self):
        self.cnt_ls = 0.0
        self.cnt_ns = 0.0

        for _ in range(self.n):
            if self.node_type[_] == 0:      #点策略节点
                self.cnt_ns += 1.0 if self.strategy[_][0] == 1 else 0.0
            else:                           #边策略节点
                num_edges = len(self.strategy[_])
                for i in self.strategy[_]:
                    if i == 1:
                        self.cnt_ls += 1.0 / num_edges

        fc = (self.cnt_ls + self.cnt_ns) / self.n
        return fc

    def calc_payoff(self):
        #只负责初始化收益，后续收益由函数update_payoff增量更新
        self.aver_payoff = [0.0] * self.n
        self.total_payoff = [0.0] * self.n # 每次重置总收益
        self.edge_c_num = [0] * self.l
        
        for edge_idx in range(self.l):
            members = self.hypergraph[edge_idx]
            
            # 第一遍循环：计算合作者数量 (直接利用 O(1) 映射查找)
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

        逻辑：
        1. 如果是边策略节点，只更新被选中的那一条超边；
        2. 如果是点策略节点，更新该节点参与的所有超边；
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
            # 如果点策略节点原策略已经等于目标策略，则无需更新
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
        max_profit = -100.0  # 初始阈值
        max_profit_node = -1

        members = self.hypergraph[chosen_edge_idx]
        for n_idx in members:
            if n_idx != node_idx:  # 排除自己
                if self.aver_payoff[n_idx] > max_profit:
                    max_profit = self.aver_payoff[n_idx]
                    max_profit_node = n_idx

        # print(f"最大收益节点 {max_profit_node}，其收益值为 {max_profit:.4f}")
        return max_profit_node, max_profit

    def update_node(self, node_idx):
        edges = self.neighbor[node_idx]
        e_idx = random.randint(0, len(edges) - 1)  # 随机选0~node_degree-1的索引
        chosen_edge_idx = self.neighbor[node_idx][e_idx]  # 转变成全局超边索引值

        target_idx, target_payoff = self.find_max_neighbor(node_idx, chosen_edge_idx)
        #print(f"选择节点{node_idx}，超边{chosen_edge_idx}，最大收益邻居是{target_idx}，其收益值为 {target_payoff:.4f}")
        if target_idx == -1:
            return

        probability = max(0.0, min(1.0, (target_payoff - self.aver_payoff[node_idx]) / self.delta))
        #print(f"在超边{chosen_edge_idx}上，节点 {node_idx} 向 {target_idx} 学习的概率: {probability:.4f}")
        #print(self.aver_payoff)
        #probability = 1
        if random.random() < probability:
            local_idx_target = self.node_edge_map[(target_idx, chosen_edge_idx)]
            target_strategy = self.strategy[target_idx][local_idx_target]

            if self.node_type[node_idx] == 1:  # 待更新节点是边策略
                self.update_payoff(
                node_idx=node_idx,
                target_strategy=target_strategy,
                chosen_edge_idx=chosen_edge_idx,
                chosen_local_idx=e_idx
            )
            else:  # 待更新节点时点策略
                self.update_payoff(
                node_idx=node_idx,
                target_strategy=target_strategy
            )

    def get_node_cooperate_rates(self):
        """只读采样，不改变原合作率计算、策略、收益或随机数状态。"""
        rates = []
        for node_idx in range(self.n):
            strategies = self.strategy[node_idx]
            if not strategies:
                rates.append(0.0)
            elif self.node_type[node_idx] == 0:
                rates.append(float(strategies[0]))
            else:
                rates.append(sum(strategies) / len(strategies))
        return rates

    def write_network_info(self, f):
        """只读取 MPD v1 已生成的 URH，不重排超边、不重新生成网络。"""
        hyperdegrees = [len(edges) for edges in self.neighbor]
        edge_sizes = [len(edge) for edge in self.hypergraph]
        f.write("\n网络信息:\n")
        f.write("网络类型=URH\n")
        f.write(f"节点数量={self.n}\n")
        f.write(f"控制超边数量参数alpha={self.alpha}\n")
        f.write(f"固定超边规模G={self.g}\n")
        f.write(f"基准超边数量lc={self.lc}\n")
        f.write(f"设定超边数量={self.l}\n")
        f.write(f"实际超边数量={len(self.hypergraph)}\n")
        f.write(f"实际平均超边规模={sum(edge_sizes) / len(edge_sizes) if edge_sizes else 0.0:.8f}\n")
        f.write(f"最小超边规模={min(edge_sizes, default=0)}\n")
        f.write(f"最大超边规模={max(edge_sizes, default=0)}\n")
        f.write(f"各规模超边数量={dict(sorted(Counter(edge_sizes).items()))}\n")
        f.write(f"平均超度={sum(hyperdegrees) / self.n:.8f}\n")
        f.write(f"最小超度={min(hyperdegrees, default=0)}\n")
        f.write(f"最大超度={max(hyperdegrees, default=0)}\n")
        f.write(f"投影网络是否连通={int(self.is_connected)}\n")
        f.write(f"困境强度b={self.b}\n")
        f.write(f"设定边策略节点概率p={self.p}\n")
        f.write(f"实际边策略节点数量={sum(self.node_type)}\n")
        f.write(f"实际点策略节点数量={self.n - sum(self.node_type)}\n")
        f.write(f"实际边策略节点比例={sum(self.node_type) / self.n:.8f}\n")
        f.write(f"策略更新归一化参数delta={self.delta}\n")
        f.write(f"超边列表={self.hypergraph}\n")
        f.write(f"节点类型={self.node_type}\n")
        f.write(f"节点所属超边={self.neighbor}\n")
        f.write(f"节点初始策略={self.strategy}\n")

    def write_node_final_info(self, f, out_steps):
        """记录现有最终收益；不额外调用 calc_payoff，以保持原收益状态。"""
        records = []
        for node_idx in range(self.n):
            edge_indices = self.neighbor[node_idx]
            degree = len(edge_indices)
            average_edge_size = (
                sum(len(self.hypergraph[edge_idx]) for edge_idx in edge_indices) / degree
                if degree else 0.0
            )
            records.append([
                float(round(self.aver_payoff[node_idx], 8)),
                int(self.node_type[node_idx]),
                round(average_edge_size, 8),
                degree,
                round(self.node_aver_fc[node_idx], 8)
            ])
        f.write("\n节点最终信息:\n")
        f.write(f"字段=[最终平均收益, 节点类型, 所属超边平均规模, 超度, 最后{out_steps}步平均合作率]\n")
        f.write("说明：总列表下标即节点编号；类型0为点策略节点、1为边策略节点。\n")
        f.write("平均收益为最终时刻总收益除以所属超边数，沿用原程序增量收益状态。\n")
        f.write("合作率沿用原吸收态统计约定：若提前吸收，整个统计窗口取吸收态值。\n")
        f.write("策略列表的局部下标与节点所属超边列表的局部下标一一对应。\n")
        f.write(f"节点记录={records}\n")
        f.write(f"节点最终总收益={[float(value) for value in self.total_payoff]}\n")
        f.write(f"节点最终策略={self.strategy}\n")
        f.write(f"节点最终合作率={self.get_node_cooperate_rates()}\n")

    def run(self, mc_steps, out_steps):
        self.mc_steps = mc_steps
        self.out_steps = out_steps
        args = (self.n, self.alpha, self.g, self.b, self.p)
        filename = result_filename(*args, mc_steps)
        os.makedirs(RESULT_DIR, exist_ok=True)
        self.result_filepath = os.path.join(RESULT_DIR, filename)
        temp_filepath = self.result_filepath + ".tmp"
        # 正常写完并关闭后才替换正式 TXT；中断遗留的 .tmp 不作为完成依据。
        with open(temp_filepath, "w", encoding="utf-8") as f:
            f.write(filename[:-4] + "\n")
            f.write(f"记录格式版本={RECORD_VERSION}\n")
            f.write("实验参数=" + json.dumps(recording_parameters(args, mc_steps, out_steps), ensure_ascii=False, sort_keys=True) + "\n")
            f.write(f"总演化步数={mc_steps}\n")
            f.write(f"合作率统计窗口步数={out_steps}\n")
            f.write("进度记录间隔=5000\n")
            self.write_network_info(f)
            f.write("\n演化过程:\n")
            f.flush()

            self.aver_fc = 0.0
            last_sum = 0.0
            node_fc_sum = [0.0] * self.n
            for step in range(1, mc_steps + 1):    #更新mc_steps步
                for i in range(self.n):     #每一步都异步更新 随机n个节点
                    node_idx = random.randint(0, self.n-1)
                    self.update_node(node_idx)

                fc = self.calc_cooperate_rate()
                if step % 5000 == 0:
                    f.write(f"进度: {step}/{mc_steps}, 合作率: {fc:.4f}\n")
                    f.flush()

                if fc <= 1e-12 or fc >= 1.0 - 1e-12:
                    f.write(f"进入吸收态，合作率为{fc}")
                    last_sum = fc * out_steps
                    # 保持原版吸收态的均值计算约定，节点记录使用相同约定。
                    node_fc_sum = [value * out_steps for value in self.get_node_cooperate_rates()]
                    break

                if step > mc_steps - out_steps:
                    last_sum += fc
                    for node_idx, value in enumerate(self.get_node_cooperate_rates()):
                        node_fc_sum[node_idx] += value

            self.aver_fc = last_sum / out_steps
            self.node_aver_fc = [value / out_steps for value in node_fc_sum]
            f.write(f"\n最终平均合作率 (最后 {out_steps} 步均值): {self.aver_fc:.8f}\n")
            f.write(f"实际执行步数={step}\n")
            self.write_node_final_info(f, out_steps)
            f.write("记录完成=1\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_filepath, self.result_filepath)

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

            # self.hypergraph 是 set，所以这里用 add，不用 append
            self.hypergraph.add(edge)

def run_single_simulation(args):
    # 在建网前再次检查，已完成参数直接返回记录，供主进程补齐 Excel。
    existing_result = read_completed_result(args)
    if existing_result is not None:
        return existing_result
    n, alpha, g, b, p = args
    sim = Simulation(n, alpha, g, b, p)
    return make_summary_row(args, sim.mc_steps, sim.out_steps, sim.aver_fc,
                            "完整记录", sim.result_filepath)


SUMMARY_HEADERS = ["N", "steps", "out_steps", "G", "alpha", "p", "b",
                   "final_avg_fc", "记录完整性", "TXT文件"]


def save_summary_workbook(workbook, filename):
    """临时写出再替换，避免中断时覆盖损坏已有汇总。"""
    temp_filename = filename + ".tmp.xlsx"
    try:
        workbook.save(temp_filename)
        os.replace(temp_filename, filename)
    except PermissionError as exc:
        raise PermissionError(
            f"无法保存汇总，请关闭占用该 Excel 的程序并检查目录写权限后重启。"
            f"已完成 TXT 会自动复用：{filename}"
        ) from exc


def summary_result_key(row):
    # 包括统计窗口；使用数值参数，不将不同参数按文件名显示精度合并。
    return tuple(int(value) for value in row[:4]) + tuple(float(value) for value in row[4:7])


def open_summary_workbook(filename):
    if os.path.isfile(filename):
        workbook = load_workbook(filename)
        if "Simulation Results" not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"汇总文件缺少 Simulation Results 工作表：{filename}")
        worksheet = workbook["Simulation Results"]
        if [cell.value for cell in worksheet[1]] != SUMMARY_HEADERS:
            workbook.close()
            raise ValueError(f"汇总文件表头与 URH 记录增强版不一致：{filename}")
    else:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Simulation Results"
        worksheet.append(SUMMARY_HEADERS)
        for cell in worksheet[1]:
            cell.fill = PatternFill(fill_type="solid", fgColor="1F4E78")
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.freeze_panes = "A2"
        worksheet.sheet_view.showGridLines = False
        worksheet.auto_filter.ref = "A1:J1"
        for column, width in zip("ABCDEFGHIJ", [10, 14, 14, 10, 12, 12, 12, 20, 24, 80]):
            worksheet.column_dimensions[column].width = width

    row_lookup = {}
    for row_idx, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if not all(value is None for value in row):
            row_lookup[summary_result_key(row)] = row_idx
    return workbook, worksheet, row_lookup


def append_summary_result(workbook, worksheet, filename, result_row, row_lookup, save=True):
    key = summary_result_key(result_row)
    row_idx = row_lookup.get(key)
    if row_idx is None:
        worksheet.append(result_row)
        row_idx = worksheet.max_row
        row_lookup[key] = row_idx
    else:
        for column, value in enumerate(result_row, start=1):
            worksheet.cell(row=row_idx, column=column, value=value)
    for column in range(1, 9):
        worksheet.cell(row=row_idx, column=column).number_format = (
            "0" if column <= 4 else "0.00000000" if column == 8 else "0.000"
        )
    worksheet.auto_filter.ref = f"A1:J{worksheet.max_row}"
    if save:
        save_summary_workbook(workbook, filename)

if __name__ == "__main__":
    g_list = [3,4]
    n = 2000
    P_list = np.round(np.arange(0.0, 1.001, 0.05), 3)
    alpha_list = [1]
    b_list = np.round(np.arange(0.0,1.001,0.025), 3)

    tasks = []
    for g in g_list:
        for p in P_list:
            for b in b_list:
                for alpha in alpha_list:
                    tasks.append((n, alpha, g, b, p))
    
    processes = 32

    os.makedirs(RESULT_DIR, exist_ok=True)
    summary_filename = os.path.join(RESULT_DIR, "MPD_URH_global_results.xlsx")
    summary_workbook, summary_worksheet, summary_row_lookup = open_summary_workbook(summary_filename)

    # Excel 只由主进程写入，多个工作进程各自写自己的参数 TXT。
    try:
        pending_tasks = []
        skipped_count = 0
        legacy_count = 0
        for args in tqdm(tasks, desc="检查已有结果"):
            existing_result = read_completed_result(args)
            if existing_result is None:
                pending_tasks.append(args)
            else:
                skipped_count += 1
                legacy_count += int(existing_result[8] == "旧版仅全局结果")
                append_summary_result(summary_workbook, summary_worksheet, summary_filename,
                                      existing_result, summary_row_lookup, save=False)
        save_summary_workbook(summary_workbook, summary_filename)
        print(f"结果目录：{RESULT_DIR}")
        print(f"总参数组数：{len(tasks)}，已完成跳过：{skipped_count}，待运行：{len(pending_tasks)}")
        if legacy_count:
            print(f"其中 {legacy_count} 组为旧版 TXT，仅有全局结果；历史网络和节点明细无法从旧记录还原。")

        if pending_tasks:
            with mp.Pool(processes=processes) as pool:
                result_iterator = pool.imap_unordered(run_single_simulation, pending_tasks)
                for result_row in tqdm(result_iterator, total=len(pending_tasks), desc="运行剩余仿真"):
                    append_summary_result(summary_workbook, summary_worksheet, summary_filename,
                                          result_row, summary_row_lookup)
    finally:
        summary_workbook.close()
    print("\n" + "=" * 30)
    print("所有仿真已完成！")
    print(f"全局汇总文件：{summary_filename}")
