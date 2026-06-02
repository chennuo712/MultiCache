import os
CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
os.chdir(CUR_FDIR)

import matplotlib.pyplot as plt
import numpy as np
import records_read
import re
from collections import defaultdict

plt.style.use('ggplot')
plt.rcParams['font.sans-serif'] = ['Times New Roman']
plt.rcParams['axes.unicode_minus'] = False

# 颜色方案
COLORS = ['#FC6B05', '#FFB62B', '#65B017', '#99D8DB', '#9BB7BB', '#32CD32']
PATTERNS = ('/', '\\', 'x', '.', 'O', '*')

# ========== 数据聚合 ==========

def load_and_aggregate(avg_cnt=3, filter_conf=None):
    """
    加载所有实验记录，按配置字符串聚合，求平均。
    filter_conf: dict, 可选过滤条件，如 {'consistency_level': 'strong'}
    返回: dict[configstr] -> PackedRecord (averaged)
    """
    conf_2_files = records_read.group_by_conf_files()
    result = {}

    for confstr, files in conf_2_files.items():
        conf = records_read.FlattenConfig(confstr)
        confjson = conf.json()

        # 应用过滤
        if filter_conf:
            skip = False
            for k, v in filter_conf.items():
                if k in confjson and confjson[k] != v:
                    skip = True
                    break
            if skip:
                continue

        # 检查是否有足够的文件做平均
        if len(files) < avg_cnt:
            print(f"  [WARN] {confstr} 仅有 {len(files)} 个文件，不足 {avg_cnt}")
            continue

        files.sort()
        selected_files = files[:avg_cnt]
        records = [records_read.load_record_from_file(f) for f in selected_files]
        avg_record = records_read.avg_records(records)
        result[confstr] = avg_record

    return result


def filter_records(records, **kwargs):
    """
    从 records dict 中过滤出符合条件（config 属性匹配）的记录。
    records: dict[configstr] -> PackedRecord
    kwargs: 如 consistency_level='strong', request_freq='high'
    返回: dict[configstr] -> PackedRecord
    """
    result = {}
    for confstr, rec in records.items():
        match = True
        for k, v in kwargs.items():
            if getattr(rec, k, None) != v:
                match = False
                break
        if match:
            result[confstr] = rec
    return result


def group_records(records, group_by):
    """
    按 records 的某个属性分组。
    records: dict[configstr] -> PackedRecord
    group_by: 属性名，如 'request_freq', 'consistency_level'
    返回: dict[group_value] -> [PackedRecord, ...]
    """
    groups = defaultdict(list)
    for confstr, rec in records.items():
        val = getattr(rec, group_by, None)
        groups[val].append(rec)
    return dict(groups)


def sort_group_keys(groups, key_order=None):
    """对分组 key 排序。如果 key_order 提供，按指定顺序排列。"""
    if key_order:
        return [k for k in key_order if k in groups]
    return sorted(groups.keys())


# ========== 通用绘图辅助 ==========

def auto_label(bars, ax, fmt='%.3f', fontsize=9):
    """在柱子上添加数值标签"""
    for bar in bars:
        height = bar.get_height()
        if height != 0 and not np.isnan(height) and not np.isinf(height):
            ax.annotate(fmt % height,
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=fontsize)


def save_fig(fig, name, dpi=300):
    """保存图片到 output 目录"""
    os.makedirs("output", exist_ok=True)
    path = f"output/{name}.png"
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
    print(f"  [OK] 已保存: {path}")
    plt.close(fig)


# ========== 图 1: 一致性错误率 ==========

def draw_consistency_error_rate(records, output_name="consistency_error_rate"):
    """
    按 consistency_level 分组，在不同 load (request_freq) 下显示一致性错误率。
    适用于所有记录已过滤为同一种 cold_start / fn_type 等。
    records: dict[configstr] -> PackedRecord
    """
    # 按 request_freq 和 consistency_level 分组
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        rf = rec.request_freq
        cl = rec.consistency_level
        groups[rf][cl].append(rec)

    load_order = ['low', 'middle', 'high']
    level_order = ['none', 'eventual', 'monotonic_read', 'strong']
    load_labels = {'low': 'Low', 'middle': 'Medium', 'high': 'High'}

    # 只保留实际存在的数据
    load_keys = [k for k in load_order if k in groups]
    level_keys = [k for k in level_order if any(k in g for g in groups.values())]

    x = np.arange(len(load_keys))
    n_levels = len(level_keys)
    bar_width = 0.7 / n_levels

    fig, ax = plt.subplots(figsize=(10, 6))

    for i, level in enumerate(level_keys):
        values = []
        for load in load_keys:
            recs = groups[load].get(level, [])
            if recs:
                vals = [r.consistency_error_rate for r in recs]
                values.append(np.mean(vals))
            else:
                values.append(0)
        bars = ax.bar(x + i * bar_width - bar_width * (n_levels - 1) / 2,
                      values, bar_width,
                      label=level,
                      color=COLORS[i % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.4f')

    ax.set_xlabel('Request Load', fontsize=14)
    ax.set_ylabel('Consistency Error Rate', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([load_labels.get(k, k) for k in load_keys], fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 2: 最大不一致窗口 ==========

def draw_max_inconsistency_window(records, output_name="max_inconsistency_window"):
    """按 consistency_level 分组，在不同 load 下显示最大不一致窗口"""
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        rf = rec.request_freq
        cl = rec.consistency_level
        groups[rf][cl].append(rec)

    load_order = ['low', 'middle', 'high']
    level_order = ['none', 'eventual', 'monotonic_read', 'strong']
    load_labels = {'low': 'Low', 'medium': 'Medium', 'high': 'High'}

    load_keys = [k for k in load_order if k in groups]
    level_keys = [k for k in level_order if any(k in g for g in groups.values())]

    x = np.arange(len(load_keys))
    n_levels = len(level_keys)
    bar_width = 0.7 / n_levels

    fig, ax = plt.subplots(figsize=(10, 6))

    for i, level in enumerate(level_keys):
        values = []
        for load in load_keys:
            recs = groups[load].get(level, [])
            if recs:
                vals = [r.max_inconsistency_window for r in recs]
                values.append(np.mean(vals))
            else:
                values.append(0)
        bars = ax.bar(x + i * bar_width - bar_width * (n_levels - 1) / 2,
                      values, bar_width,
                      label=level,
                      color=COLORS[i % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.2f')

    ax.set_xlabel('Request Load', fontsize=14)
    ax.set_ylabel('Max Inconsistency Window (frames)', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([load_labels.get(k, k) for k in load_keys], fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 3: 一致性机制开销 ==========

def draw_consistency_overhead(records, output_name="consistency_overhead"):
    """按 consistency_level 分组，在不同 load 下显示一致性开销"""
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        rf = rec.request_freq
        cl = rec.consistency_level
        groups[rf][cl].append(rec)

    load_order = ['low', 'middle', 'high']
    level_order = ['none', 'eventual', 'monotonic_read', 'strong']
    load_labels = {'low': 'Low', 'medium': 'Medium', 'high': 'High'}

    load_keys = [k for k in load_order if k in groups]
    level_keys = [k for k in level_order if any(k in g for g in groups.values())]

    x = np.arange(len(load_keys))
    n_levels = len(level_keys)
    bar_width = 0.7 / n_levels

    fig, ax = plt.subplots(figsize=(10, 6))

    for i, level in enumerate(level_keys):
        values = []
        for load in load_keys:
            recs = groups[load].get(level, [])
            if recs:
                vals = [r.consistency_overhead for r in recs]
                values.append(np.mean(vals))
            else:
                values.append(0)
        bars = ax.bar(x + i * bar_width - bar_width * (n_levels - 1) / 2,
                      values, bar_width,
                      label=level,
                      color=COLORS[i % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.2f')

    ax.set_xlabel('Request Load', fontsize=14)
    ax.set_ylabel('Consistency Overhead', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([load_labels.get(k, k) for k in load_keys], fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 4: 延迟分解（堆叠柱状图） ==========

def draw_latency_breakdown(records, output_name="latency_breakdown"):
    """
    堆叠柱状图展示各一致性级别下的延迟分解。
    每个柱= waitsche + coldstart + datarecv + exe + consistency_overhead
    """
    # 按 consistency_level 和 request_freq 分组
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        rf = rec.request_freq
        cl = rec.consistency_level
        groups[rf][cl].append(rec)

    load_order = ['low', 'middle', 'high']
    level_order = ['none', 'eventual', 'monotonic_read', 'strong']
    load_labels = {'low': 'Low', 'medium': 'Medium', 'high': 'High'}

    load_keys = [k for k in load_order if k in groups]
    level_keys = [k for k in level_order if any(k in g for g in groups.values())]

    n_loads = len(load_keys)
    n_levels = len(level_keys)
    bar_width = 0.7 / n_levels

    fig, axes = plt.subplots(1, n_loads, figsize=(6 * n_loads, 5))
    if n_loads == 1:
        axes = [axes]

    stack_labels = ['Wait Sche', 'Cold Start', 'Data Recv', 'Execute', 'Consistency']
    stack_colors = ['#FC6B05', '#FFB62B', '#65B017', '#99D8DB', '#E74C3C']

    for li, load in enumerate(load_keys):
        ax = axes[li]
        x = np.arange(n_levels)

        for ni, level in enumerate(level_keys):
            recs = groups[load].get(level, [])
            if not recs:
                continue
            avg_rec = records_read.PackedRecord()
            # 手动求平均
            for attr in ['waitsche_time_per_req', 'coldstart_time_per_req',
                         'datarecv_time_per_req', 'exe_time_per_req',
                         'consistency_overhead']:
                setattr(avg_rec, attr,
                        np.mean([getattr(r, attr) for r in recs]))

            components = [
                avg_rec.waitsche_time_per_req,
                avg_rec.coldstart_time_per_req,
                avg_rec.datarecv_time_per_req,
                avg_rec.exe_time_per_req,
                avg_rec.consistency_overhead,
            ]

            bottom = 0
            for ci, comp in enumerate(components):
                ax.bar(x[ni], comp, bar_width,
                       bottom=bottom,
                       color=stack_colors[ci % len(stack_colors)],
                       edgecolor='black', linewidth=0.5,
                       label=stack_labels[ci] if ni == 0 else "")
                bottom += comp

        ax.set_title(load_labels.get(load, load), fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels(level_keys, fontsize=10, rotation=15)
        ax.set_ylabel('Latency', fontsize=12)
        ax.grid(True, axis='y', alpha=0.3)

    # 统一图例
    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    fig.legend(unique.values(), unique.keys(), loc='upper center',
               bbox_to_anchor=(0.5, -0.02), ncol=len(stack_labels), fontsize=10)

    fig.tight_layout(rect=[0, 0.06, 1, 1])
    save_fig(fig, output_name)


# ========== 图 5: 缓存命中率对比 ==========

def draw_cache_hit_ratios(records, output_name="cache_hit_ratios"):
    """
    按 instance_cache_policy 分组显示 L1/L2/L3/Overall 缓存命中率。
    """
    groups = defaultdict(list)
    for confstr, rec in records.items():
        policy = rec.instance_cache_policy
        groups[policy].append(rec)

    policies = sorted(groups.keys())
    x = np.arange(len(policies))
    bar_width = 0.18

    metrics = [
        ('l1_cache_hit_ratio', 'L1 Hit Ratio'),
        ('l2_cache_hit_ratio', 'L2 Hit Ratio'),
        ('l3_cache_hit_ratio', 'L3 Hit Ratio'),
        ('overall_cache_hit_ratio', 'Overall Hit Ratio'),
    ]

    fig, ax = plt.subplots(figsize=(12, 6))

    for mi, (attr, label) in enumerate(metrics):
        values = []
        for policy in policies:
            recs = groups[policy]
            vals = [np.mean([getattr(r, attr) for r in recs])]
            values.append(vals[0])
        bars = ax.bar(x + mi * bar_width - bar_width * (len(metrics) - 1) / 2,
                      values, bar_width,
                      label=label,
                      color=COLORS[mi % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.3f')

    ax.set_xlabel('Cache Policy', fontsize=14)
    ax.set_ylabel('Hit Ratio', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(policies, fontsize=10, rotation=20)
    ax.legend(fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 6: P99 尾延迟对比 ==========

def draw_p99_latency(records, output_name="p99_latency"):
    """
    按 consistency_level 分组显示 P99 尾延迟。
    """
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        rf = rec.request_freq
        cl = rec.consistency_level
        groups[rf][cl].append(rec)

    load_order = ['low', 'middle', 'high']
    level_order = ['none', 'eventual', 'monotonic_read', 'strong']
    load_labels = {'low': 'Low', 'medium': 'Medium', 'high': 'High'}

    load_keys = [k for k in load_order if k in groups]
    level_keys = [k for k in level_order if any(k in g for g in groups.values())]

    x = np.arange(len(load_keys))
    n_levels = len(level_keys)
    bar_width = 0.7 / n_levels

    fig, ax = plt.subplots(figsize=(10, 6))

    for i, level in enumerate(level_keys):
        values = []
        for load in load_keys:
            recs = groups[load].get(level, [])
            if recs:
                vals = [r.req_done_time_avg_99p for r in recs]
                values.append(np.mean(vals))
            else:
                values.append(0)
        bars = ax.bar(x + i * bar_width - bar_width * (n_levels - 1) / 2,
                      values, bar_width,
                      label=level,
                      color=COLORS[i % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.2f')

    ax.set_xlabel('Request Load', fontsize=14)
    ax.set_ylabel('P99 Latency', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([load_labels.get(k, k) for k in load_keys], fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 7: 综合指标总览 ==========

def draw_all_metrics_summary(records, output_name="metrics_summary"):
    """
    1 行 N 列的多子图，显示各指标对比。
    """
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        cl = rec.consistency_level
        rf = rec.request_freq
        groups[cl][rf].append(rec)

    level_order = ['none', 'eventual', 'monotonic_read', 'strong']
    level_labels = {'none': 'None', 'eventual': 'Eventual',
                    'monotonic_read': 'Monotonic', 'strong': 'Strong'}
    load_order = ['low', 'middle', 'high']
    load_labels = {'low': 'Low', 'medium': 'Medium', 'high': 'High'}

    levels_present = [k for k in level_order if k in groups]
    n_levels = len(levels_present)

    metrics = [
        ('cost_per_req', 'Cost per Request'),
        ('time_per_req', 'Avg Latency'),
        ('consistency_error_rate', 'Consistency Error Rate'),
        ('rps', 'Throughput (RPS)'),
        ('overall_cache_hit_ratio', 'Cache Hit Ratio'),
    ]

    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4.5))
    if len(metrics) == 1:
        axes = [axes]

    x = np.arange(n_levels)
    bar_width = 0.6

    for mi, (attr, title) in enumerate(metrics):
        ax = axes[mi]
        # 按 load 分组显示
        values_per_load = []
        for load in load_order:
            vals = []
            for level in levels_present:
                recs = groups[level].get(load, [])
                if recs:
                    vals.append(np.mean([getattr(r, attr) for r in recs]))
                else:
                    vals.append(0)
            if any(v != 0 for v in vals):
                values_per_load.append((load, vals))

        if not values_per_load:
            continue

        n_loads = len(values_per_load)
        inner_width = bar_width / n_loads
        for li, (load, vals) in enumerate(values_per_load):
            offset = (li - (n_loads - 1) / 2) * inner_width
            bars = ax.bar(x + offset, vals, inner_width * 0.9,
                          label=load_labels.get(load, load),
                          color=COLORS[li % len(COLORS)],
                          edgecolor='black', linewidth=0.5)

        ax.set_title(title, fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels([level_labels.get(k, k) for k in levels_present],
                           fontsize=9, rotation=15)
        ax.grid(True, axis='y', alpha=0.3)
        if mi == 0:
            ax.set_ylabel('Value', fontsize=11)

    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    fig.legend(unique.values(), unique.keys(), loc='upper center',
               bbox_to_anchor=(0.5, -0.02), ncol=len(unique), fontsize=10)

    fig.tight_layout(rect=[0, 0.06, 1, 1])
    save_fig(fig, output_name)


# ========== 主入口 ==========

def pipeline():
    import sys

    avg_cnt = 3
    filter_conf = {}  # 如 {'cold_start': 'high', 'fn_type': 'cpu'}

    # 支持命令行参数
    if len(sys.argv) >= 2:
        filter_conf['cold_start'] = sys.argv[1]
    if len(sys.argv) >= 3:
        filter_conf['fn_type'] = sys.argv[2]
    if len(sys.argv) >= 4:
        try:
            avg_cnt = int(sys.argv[3])
        except ValueError:
            pass
    if len(sys.argv) >= 5:
        filter_conf['dag_type'] = sys.argv[4]
    if len(sys.argv) >= 6:
        filter_conf['no_mech_latency'] = sys.argv[5]

    print("=" * 60)
    print("一致性实验数据聚合与绘图")
    print("=" * 60)
    print(f"平均次数: {avg_cnt}")
    print(f"过滤条件: {filter_conf}")

    print("\n[Step 1] 加载与聚合数据...")
    all_records = load_and_aggregate(avg_cnt=avg_cnt, filter_conf=filter_conf)
    print(f"  加载 {len(all_records)} 个配置组的聚合记录")

    # 列出所有可用的一致性级别
    consistency_levels = set()
    request_freqs = set()
    cache_policies = set()
    for confstr, rec in all_records.items():
        consistency_levels.add(rec.consistency_level)
        request_freqs.add(rec.request_freq)
        cache_policies.add(rec.instance_cache_policy)
    print(f"  一致性级别: {sorted(consistency_levels)}")
    print(f"  请求频率: {sorted(request_freqs)}")
    print(f"  缓存策略: {sorted(cache_policies)}")

    print("\n[Step 2] 生成图表...")

    print("\n  2.1 一致性错误率 (按负载分组)...")
    draw_consistency_error_rate(all_records)

    print("\n  2.2 最大不一致窗口...")
    draw_max_inconsistency_window(all_records)

    print("\n  2.3 一致性机制开销...")
    draw_consistency_overhead(all_records)

    print("\n  2.4 延迟分解（堆叠柱状图）...")
    draw_latency_breakdown(all_records)

    print("\n  2.5 缓存命中率对比...")
    draw_cache_hit_ratios(all_records)

    print("\n  2.6 P99 尾延迟对比...")
    draw_p99_latency(all_records)

    print("\n  2.7 综合指标总览...")
    draw_all_metrics_summary(all_records)

    print("\n" + "=" * 60)
    print("全部完成！图表已保存到 output/ 目录")
    print("=" * 60)


if __name__ == '__main__':
    pipeline()
