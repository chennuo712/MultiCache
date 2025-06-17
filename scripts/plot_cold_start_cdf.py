import json
import numpy as np
import matplotlib.pyplot as plt
import os
import yaml
import records_cold_start_read

# 初始化设置
CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
os.chdir(CUR_FDIR)

def calculate_cdf(data):
    """计算数据的CDF"""
    sorted_data = np.sort(data)
    p = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
    return sorted_data, p

def draw_cdf_plot(policy_delays):
    """绘制CDF图表"""
    plt.style.use('seaborn-v0_8')
    fig, ax = plt.subplots(figsize=(10, 4))  # 增大图表尺寸
    
    # 设置线条样式
    styles = {
        'Contemp': {'color': 'black', 'linestyle': '-', 'linewidth': 2.0},
        'CFC': {'color': '#4C72B0', 'linestyle': '-', 'linewidth': 2.0},
        'Duo': {'color': '#55A868', 'linestyle': '--', 'linewidth': 2.0},
        'FaasCache': {'color': '#C44E52', 'linestyle': '-', 'linewidth': 2.0},
        'LRU': {'color': '#8172B2', 'linestyle': '-.', 'linewidth': 2.0},
        'TTL': {'color': '#937860', 'linestyle': ':', 'linewidth': 2.0}
    }
    
    print("\nDebug - Data sizes:", {k: len(v) for k, v in policy_delays.items()})
    
    if not any(len(delays) > 0 for delays in policy_delays.values()):
        print("\nError: No valid cold start delay data found!")
        return
    
    # 绘制CDF曲线
    # 确保 Contemp 排在第一位
    sorted_policies = sorted(policy_delays.keys(), key=lambda x: (x != 'Contemp', x))
    
    for policy_name in sorted_policies:
        delays = policy_delays[policy_name]
        if delays:
            sorted_delays, cdf = calculate_cdf(delays)
            style = styles.get(policy_name, {'color': 'gray', 'linestyle': '-', 'linewidth': 2.0})
            ax.plot(sorted_delays, cdf, label=policy_name, **style)
            print(f"Plotted {len(delays)} points for {policy_name}")
    
    # 配置图表
    ax.set_xlabel('Cold Start Latency (ms)', fontsize=24)
    ax.set_ylabel('CDF', fontsize=24)  # 横向显示Y轴标签
    # ax.yaxis.set_label_coords(-0.1, 0.9)  # 调整Y轴标签位置
    
    # ax.set_title('Cold Start Latency CDF', fontsize=16)
    ax.grid(True, linestyle=':', alpha=0.3)
    ax.set_xlim(31, 39)
    ax.set_ylim(0.1, 1.0)
    
    # 设置 X 轴刻度和标签
    xticks = ax.get_xticks()
    ax.set_xticklabels([int(x * 10) for x in xticks], fontsize=24)
    
    # 设置Y轴刻度
    ax.set_yticks([0.1, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(['0.1', '0.25', '0.5', '0.75', '1.0'], fontsize=24)
    
    # 设置X轴刻度字体
    ax.tick_params(axis='x', labelsize=24)
    
    # 放大图例并调整位置
    # legend = ax.legend(
    #     loc='lower right',
    #     fontsize=14,  # 增大图例字体
    #     bbox_to_anchor=(0.98, 0.02),
    #     bbox_transform=ax.transAxes,
    #     frameon=True,
    #     framealpha=0.8,
    #     edgecolor='gray',
    #     borderaxespad=1.0,  # 增加边距
    #     handlelength=3.0,   # 增加图例线条长度
    #     handletextpad=1.0   # 增加文本和线条间距
    # )
    
    plt.tight_layout()
    
    # 保存为SVG格式
    output_dir = os.path.join(CUR_FDIR, 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'cold_start_cdf.svg')
    plt.savefig(output_path, dpi=300, bbox_inches='tight', format='svg')
    plt.close()
    print(f"\nCDF plot has been saved as '{output_path}'")

def main():
    """主函数"""
    print("\n[Phase 1/2] 加载冷启动延迟数据...")
    policy_delays = records_cold_start_read.load_all_cold_start_data()
    
    print("\n[Phase 2/2] 生成CDF图表...")
    draw_cdf_plot(policy_delays)

if __name__ == "__main__":
    main() 