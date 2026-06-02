import os
CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
os.chdir(CUR_FDIR)

import matplotlib.pyplot as plt
import numpy as np
import records_read
from collections import defaultdict

plt.style.use('ggplot')
plt.rcParams['font.sans-serif'] = ['Times New Roman']
plt.rcParams['axes.unicode_minus'] = False

COLORS = ['#FC6B05', '#FFB62B', '#65B017', '#99D8DB', '#9BB7BB', '#32CD32']
PATTERNS = ('/', '\\', 'x', '.', 'O', '*')

# ========== 数据聚合 ==========

def load_and_aggregate(avg_cnt=3, filter_conf=None):
    conf_2_files = records_read.group_by_conf_files()
    result = {}
    for confstr, files in conf_2_files.items():
        conf = records_read.FlattenConfig(confstr)
        confjson = conf.json()
        if filter_conf:
            skip = False
            for k, v in filter_conf.items():
                if k in confjson and confjson[k] != v:
                    skip = True
                    break
            if skip:
                continue
        if len(files) < avg_cnt:
            continue
        files.sort()
        selected = files[:avg_cnt]
        recs = [records_read.load_record_from_file(f) for f in selected]
        result[confstr] = records_read.avg_records(recs)
    return result


def filter_records(records, **kwargs):
    result = {}
    for confstr, rec in records.items():
        match = all(getattr(rec, k, None) == v for k, v in kwargs.items())
        if match:
            result[confstr] = rec
    return result


def auto_label(bars, ax, fmt='%.3f', fontsize=9):
    for bar in bars:
        h = bar.get_height()
        if h != 0 and not np.isnan(h) and not np.isinf(h):
            ax.annotate(fmt % h,
                        xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha='center', va='bottom', fontsize=fontsize)


def save_fig(fig, name, dpi=300):
    os.makedirs("output", exist_ok=True)
    path = f"output/{name}.png"
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
    print(f"  [OK] 已保存: {path}")
    plt.close(fig)


# ========== 图 1: 缓存命中率对比（L1/L2/L3/Overall） ==========

def draw_cache_hit_ratio_comparison(records, output_name="cache_hit_ratio_comparison"):
    """按 instance_cache_policy 分组，展示 L1/L2/L3/Overall 命中率"""
    groups = defaultdict(list)
    for confstr, rec in records.items():
        groups[rec.instance_cache_policy].append(rec)

    policies = sorted(groups.keys())
    x = np.arange(len(policies))
    bar_width = 0.18

    metrics = [
        ('l1_cache_hit_ratio', 'L1 Cache'),
        ('l2_cache_hit_ratio', 'L2 Snapshot'),
        ('l3_cache_hit_ratio', 'L3 Data'),
        ('overall_cache_hit_ratio', 'Overall'),
    ]

    fig, ax = plt.subplots(figsize=(12, 6))

    for mi, (attr, label) in enumerate(metrics):
        values = []
        for pol in policies:
            vals = [getattr(r, attr) for r in groups[pol]]
            values.append(np.mean(vals))
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


# ========== 图 2: 不同策略下的性能指标 ==========

def draw_policy_performance(records, output_name="policy_performance"):
    """展示不同 instance_cache_policy 下的 Cost、Latency、Throughput"""
    groups = defaultdict(list)
    for confstr, rec in records.items():
        groups[rec.instance_cache_policy].append(rec)

    policies = sorted(groups.keys())
    x = np.arange(len(policies))

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    configs = [
        ('cost_per_req', 'Cost per Request', 'Cost'),
        ('time_per_req', 'Avg Latency', 'Latency'),
        ('rps', 'Throughput (RPS)', 'Throughput'),
    ]

    for idx, (attr, title, ylabel) in enumerate(configs):
        ax = axes[idx]
        values = []
        for pol in policies:
            vals = [getattr(r, attr) for r in groups[pol]]
            values.append(np.mean(vals))
        bars = ax.bar(x, values, bar_width=0.5,
                      color=COLORS[idx % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.3f' if idx != 2 else '%.1f')
        ax.set_title(title, fontsize=13)
        ax.set_xticks(x)
        ax.set_xticklabels(policies, fontsize=9, rotation=20)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.grid(True, axis='y', alpha=0.3)

    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 3: 缓存策略 - 成本效率 ==========

def draw_cost_efficiency(records, output_name="cost_efficiency"):
    """展示不同缓存策略的成本效率 (RPS / Cost / Latency)"""
    groups = defaultdict(list)
    for confstr, rec in records.items():
        groups[rec.instance_cache_policy].append(rec)

    policies = sorted(groups.keys())
    x = np.arange(len(policies))

    fig, ax = plt.subplots(figsize=(10, 6))

    values = []
    for pol in policies:
        recs = groups[pol]
        effs = []
        for r in recs:
            if r.cost_per_req > 0 and r.time_per_req > 0:
                effs.append(r.rps / r.cost_per_req / r.time_per_req)
            else:
                effs.append(0)
        values.append(np.mean(effs))

    bars = ax.bar(x, values, bar_width=0.5,
                  color='#65B017',
                  edgecolor='black', linewidth=0.5)
    auto_label(bars, ax, fmt='%.4f')

    ax.set_xlabel('Cache Policy', fontsize=14)
    ax.set_ylabel('Cost Efficiency (RPS/Cost/Latency)', fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(policies, fontsize=10, rotation=20)
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 4: 冷启动延迟对比 ==========

def draw_coldstart_by_policy(records, output_name="coldstart_by_policy"):
    """展示不同缓存策略下的冷启动延迟"""
    groups = defaultdict(list)
    for confstr, rec in records.items():
        groups[rec.instance_cache_policy].append(rec)

    policies = sorted(groups.keys())
    x = np.arange(len(policies))
    bar_width = 0.35

    fig, ax = plt.subplots(figsize=(10, 6))

    values = []
    for pol in policies:
        vals = [r.coldstart_time_per_req for r in groups[pol]]
        values.append(np.mean(vals))

    bars = ax.bar(x, values, bar_width,
                  color='#FC6B05',
                  edgecolor='black', linewidth=0.5)
    auto_label(bars, ax, fmt='%.2f')

    ax.set_xlabel('Cache Policy', fontsize=14)
    ax.set_ylabel('Cold Start Latency', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(policies, fontsize=10, rotation=20)
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 5: 容器数量对比 ==========

def draw_container_count_by_policy(records, output_name="container_count_by_policy"):
    """展示不同缓存策略下的容器数量"""
    groups = defaultdict(list)
    for confstr, rec in records.items():
        groups[rec.instance_cache_policy].append(rec)

    policies = sorted(groups.keys())
    x = np.arange(len(policies))

    fig, ax = plt.subplots(figsize=(10, 6))
    values = []
    for pol in policies:
        vals = [r.fn_container_cnt for r in groups[pol]]
        values.append(np.mean(vals))

    bars = ax.bar(x, values, bar_width=0.5,
                  color='#9BB7BB',
                  edgecolor='black', linewidth=0.5)
    auto_label(bars, ax, fmt='%.1f')

    ax.set_xlabel('Cache Policy', fontsize=14)
    ax.set_ylabel('Container Count', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(policies, fontsize=10, rotation=20)
    ax.grid(True, axis='y', alpha=0.3)
    fig.tight_layout()
    save_fig(fig, output_name)


# ========== 图 6: 冷启动影响综合对比 ==========

def draw_coldstart_comprehensive(records, output_name="coldstart_comprehensive"):
    """
    综合图: 对比不同 cold_start 和 instance_cache_policy 组合下
    的冷启动延迟 (x=cold_start, grouped bars=policy)
    """
    groups = defaultdict(lambda: defaultdict(list))
    for confstr, rec in records.items():
        cs = rec.cold_start
        pol = rec.instance_cache_policy
        groups[cs][pol].append(rec)

    cs_order = ['low', 'high']
    cs_labels = {'low': 'Low', 'high': 'High'}
    policies = sorted(set(
        pol for csg in groups.values() for pol in csg.keys()
    ))

    x = np.arange(len(cs_order))
    n_pol = len(policies)
    bar_width = 0.7 / n_pol

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 子图1: 冷启动延迟
    ax = axes[0]
    for pi, pol in enumerate(policies):
        values = []
        for cs in cs_order:
            recs = groups[cs].get(pol, [])
            if recs:
                values.append(np.mean([r.coldstart_time_per_req for r in recs]))
            else:
                values.append(0)
        bars = ax.bar(x + pi * bar_width - bar_width * (n_pol - 1) / 2,
                      values, bar_width,
                      label=pol,
                      color=COLORS[pi % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.2f')

    ax.set_title('Cold Start Latency', fontsize=13)
    ax.set_xticks(x)
    ax.set_xticklabels([cs_labels.get(c, c) for c in cs_order], fontsize=12)
    ax.set_ylabel('Latency', fontsize=12)
    ax.grid(True, axis='y', alpha=0.3)

    # 子图2: 缓存命中率
    ax = axes[1]
    for pi, pol in enumerate(policies):
        values = []
        for cs in cs_order:
            recs = groups[cs].get(pol, [])
            if recs:
                values.append(np.mean([r.overall_cache_hit_ratio for r in recs]))
            else:
                values.append(0)
        bars = ax.bar(x + pi * bar_width - bar_width * (n_pol - 1) / 2,
                      values, bar_width,
                      label=pol,
                      color=COLORS[pi % len(COLORS)],
                      edgecolor='black', linewidth=0.5)
        auto_label(bars, ax, fmt='%.3f')

    ax.set_title('Overall Cache Hit Ratio', fontsize=13)
    ax.set_xticks(x)
    ax.set_xticklabels([cs_labels.get(c, c) for c in cs_order], fontsize=12)
    ax.set_ylabel('Hit Ratio', fontsize=12)
    ax.grid(True, axis='y', alpha=0.3)

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
    filter_conf = {}

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

    # 移除 instance_cache_policy 过滤，保留全部策略
    print("=" * 60)
    print("缓存策略实验数据聚合与绘图")
    print("=" * 60)
    print(f"平均次数: {avg_cnt}")
    print(f"过滤条件: {filter_conf}")

    print("\n[Step 1] 加载与聚合数据...")
    all_records = load_and_aggregate(avg_cnt=avg_cnt, filter_conf=filter_conf)
    print(f"  加载 {len(all_records)} 个配置组的聚合记录")

    cache_policies = set()
    for confstr, rec in all_records.items():
        cache_policies.add(rec.instance_cache_policy)
    print(f"  缓存策略: {sorted(cache_policies)}")

    print("\n[Step 2] 生成图表...")

    print("\n  2.1 缓存命中率对比 (L1/L2/L3/Overall)...")
    draw_cache_hit_ratio_comparison(all_records)

    print("\n  2.2 策略性能指标 (Cost/Latency/Throughput)...")
    draw_policy_performance(all_records)

    print("\n  2.3 成本效率对比...")
    draw_cost_efficiency(all_records)

    print("\n  2.4 冷启动延迟对比...")
    draw_coldstart_by_policy(all_records)

    print("\n  2.5 容器数量对比...")
    draw_container_count_by_policy(all_records)

    print("\n  2.6 冷启动综合对比...")
    draw_coldstart_comprehensive(all_records)

    print("\n" + "=" * 60)
    print("全部完成！图表已保存到 output/ 目录")
    print("=" * 60)


if __name__ == '__main__':
    pipeline()
