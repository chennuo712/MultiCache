# draw_bar_latency.py
import os
import re
import yaml
import numpy as np
import matplotlib.pyplot as plt
from pprint import pprint
import records_read

# ---------------------- 初始化设置 ----------------------
CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
os.chdir(CUR_FDIR)

# ---------------------- 核心绘图函数 ----------------------
def draw_with_draw_meta(drawmeta, conf):
    """绘制混合图表：柱状图+折线图+散点图"""
    plt.style.use('seaborn-v0_8')  # 修复样式名称兼容性
    fig, ax1 = plt.subplots(figsize=(14, 7))
    plt.subplots_adjust(top=0.85)  # 为顶部图例留出空间

    # ----------------- 数据结构初始化 -----------------
    load_levels = ["Low", "Middle", "High"]  # X轴标签，修改 "Mid" 为 "Middle"
    policy_data = {}  # 结构: {policy: {load: (总延迟, 冷启延迟, 缓存命中率)}}
    ax2 = None  # 初始化第二个Y轴变量

    # ----------------- 数据提取处理 -----------------
    for meta in drawmeta:
        metric_type = meta["value_y"]
        for group in meta["groups"]:
            load = group["group"].capitalize()  # 从分组获取负载级别
            for value in group["values"]:
                config_str = value[0]
                policy = _extract_cache_policy(config_str)  # 提取缓存策略
                
                # 初始化数据结构
                if policy not in policy_data:
                    policy_data[policy] = { load: (0, 0, 0) for load in load_levels }
                
                # 填充数据
                if metric_type == "Makespan(ms)":
                    total_lat = sum(value[1])
                    current = policy_data[policy][load]
                    policy_data[policy][load] = (total_lat, current[1], current[2])
                elif metric_type == "Cold Start Latency(ms)":
                    cold_lat = value[1]
                    current = policy_data[policy][load]
                    policy_data[policy][load] = (current[0], cold_lat, current[2])
                elif metric_type == "Cache Hit Ratio":
                    cache_hit = float(value[1]) * 100  # 转换为百分比
                    current = policy_data[policy][load]
                    policy_data[policy][load] = (current[0], current[1], cache_hit)

    print("Debug - Policy Data:", policy_data)  # 添加调试信息

    # ----------------- 可视化参数设置 -----------------
    bar_width = 0.2
    # 修改index的生成方式，增加子图间距
    index = np.array([0, 1.45, 2.9])  # 将间距从2增加到4
    # 更新颜色方案，使 Contemp 为黑色
    colors = {
        'CONTEMP': '#000000',  # 黑色
        'CFC': '#4C72B0',      # 蓝色
        'DUO': '#55A868',      # 绿色
        'FAASCACHE': '#C44E52', # 深红色
        'LRU': '#8172B2',      # 紫色
        'TTL': '#937860'       # 棕色
    }
    markers = ["+", "+", "+", "+", "+", "+"]  # 散点标记

    # ----------------- 绘制每个策略的图形 -----------------
    # 确保 Contemp 排在第一位
    sorted_policies = sorted(policy_data.keys(), key=lambda x: (x != 'CONTEMP', x))
    
    for idx, policy in enumerate(sorted_policies):
        data = policy_data[policy]
        sorted_data = [data[load] for load in load_levels]
        total_lats = [d[0] for d in sorted_data]
        cold_lats = [d[1] for d in sorted_data]
        cache_hits = [d[2] for d in sorted_data]

        # 绘制冷启动延迟柱状图（放在底部）
        ax1.bar(
            index + idx*bar_width, 
            cold_lats,
            width=bar_width,
            color=colors[policy],
            alpha=0.9,  # 加深冷启动延迟的颜色
            label=None  # 不在图例中显示冷启动部分
        )

        # 在冷启动延迟顶部添加黑线
        for i in range(len(cold_lats)):
            ax1.plot(
                [index[i] + idx*bar_width - bar_width/2, index[i] + idx*bar_width + bar_width/2],
                [cold_lats[i], cold_lats[i]],
                color='black',
                linewidth=1,
                zorder=5
            )

        # 绘制非冷启动延迟柱状图（堆叠在上面）
        non_cold_lats = [total - cold for total, cold in zip(total_lats, cold_lats)]
        ax1.bar(
            index + idx*bar_width, 
            non_cold_lats,
            bottom=cold_lats,  # 放在冷启动延迟之上
            width=bar_width,
            color=colors[policy],
            alpha=0.5,  # 增加非冷启动部分的透明度
            label=f'{policy}'  # 只在图例中显示策略名称
        )

        # 在柱状图内部添加缓存命中率标注
        for i in range(len(total_lats)):
            # 计算标注位置（在柱状图左侧）
            x_pos = index[i] + idx*bar_width - 0.075
            y_pos = cold_lats[i] + non_cold_lats[i]/2  # 垂直位置在柱子中间
            
            # 添加缓存命中率标注
            ax1.text(
                x_pos, y_pos,
                f'{cache_hits[i]:.1f}%',
                ha='left',  # 左对齐
                va='center',  # 居中对齐
                fontsize=11,
                color='black',
                rotation=0,  # 不旋转文本
                zorder=10
            )

        # 缓存命中率散点图（需创建第二个Y轴）
        if ax2 is None:  # 延迟创建第二个Y轴
            ax2 = ax1.twinx()
            ax2.spines['right'].set_position(('outward', 0))
        ax2.scatter(
            index + idx*bar_width,
            cache_hits,
            marker=markers[idx],
            s=200,  # 增大标记大小
            color='red',  # 使用统一的红色
            zorder=10
        )

    # ----------------- 图表美化设置 -----------------
    ax1.set_xlabel("Workload Intensity", fontsize=14, labelpad=15)
    ax1.set_ylabel("Latency (ms)", fontsize=14, labelpad=15)
    ax1.set_xticks(index + bar_width * (len(sorted_policies) - 1) / 2)
    ax1.set_xticklabels(load_levels, fontsize=12)
    ax1.grid(True, linestyle='--', alpha=0.6)

    if ax2 is not None:  # 安全设置第二个Y轴
        ax2.set_ylabel("Cache Hit Ratio (%)", fontsize=14, labelpad=20)
        ax2.tick_params(axis='y', labelsize=12)
        ax2.set_ylim(0, 100)  # 设置Y轴范围为0-100%

    # ----------------- 图例整合 -----------------
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2 = ax2.get_legend_handles_labels()[0] if ax2 else []
    legend_labels = labels1 + [f'{policy} Hit%' for policy in sorted_policies]  # 使用排序后的策略列表
    
    plt.legend(
        handles1 + handles2,
        legend_labels,
        loc='upper center',
        bbox_to_anchor=(0.5, 1.25),
        ncol=3,
        fontsize=12,
        frameon=True,
        shadow=True
    )

    plt.tight_layout()
    plt.show()

def _extract_cache_policy(config_str):
    """安全提取缓存策略名称"""
    match = re.search(r"\.ic\((\w+?)\.", config_str)
    if match:
        policy = match.group(1).upper()
        return {
            "cfc": "CFC",
            "contemp": "Contemp",
            "duo": "Duo",
            "faascache":"FaasCache",
            "lru": "LRU",
            "ttl": "TTL",
        }.get(policy, policy)
    return "Unknown"

# ---------------------- 数据处理管道 ----------------------
def pipeline():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python draw_bar_latency.py <config.yml>")
        sys.exit(1)

    try:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:  # 编码修复
            draw_conf = yaml.safe_load(f)
    except Exception as e:
        print(f"配置读取失败: {str(e)}")
        sys.exit(1)

    # ----------------- 数据加载阶段 -----------------
    print("\n[Phase 1/4] 加载实验记录...")
    conf_to_files = get_record_filelist(draw_conf)
    
    print("[Phase 2/4] 验证数据完整性...")
    check_first_draw_group_match_avg_cnt(draw_conf, conf_to_files)
    
    print("[Phase 3/4] 计算统计指标...")
    avg_records = get_each_group_prev_avg_cnt_file__compute_avg(draw_conf, conf_to_files)
    
    print("[Phase 4/4] 准备可视化数据...")
    flat_records = [avg_records[conf] for conf in avg_records]
    grouped_records = group_records(flat_records, draw_conf)
    draw_meta = to_draw_meta(grouped_records, draw_conf)

    print("\n生成可视化图表...")
    draw_with_draw_meta(draw_meta, draw_conf)

# ---------------------- 保留原始数据处理函数 ----------------------
def get_record_filelist(drawconf):
    conf_2_files = records_read.group_by_conf_files()
    new = {}
    for confstr in conf_2_files:
        conf = records_read.FlattenConfig(confstr)
        confjson = conf.json()
        
        # 过滤不符合条件配置
        if any(confjson.get(k) != v for k, v in drawconf['filter'].items()):
            continue
            
        if not any(all(confjson.get(tk) == tv for tk, tv in target[0].items()) 
            for target in drawconf['targets_alias']):
            continue
            
        new[confstr] = conf_2_files[confstr]
    return new

def check_first_draw_group_match_avg_cnt(drawconf,conf_2_files):
    avg_cnt=drawconf['avg_cnt']
    if avg_cnt==0:
        print("!!! avg_cnt should not be 0")
        exit(1)
    
    first_group_k=drawconf['group']['by']
    first_group_v=drawconf['group']['types'][0]
    conf_2_files_only_first_group={}
    # filter 
    for confstr in conf_2_files:
        conf=records_read.FlattenConfig(confstr)
        if getattr(conf,first_group_k)==first_group_v:
            conf_2_files_only_first_group[confstr]=conf_2_files[confstr]

    # all group files cnt >= avg_cnt
    for confstr in conf_2_files_only_first_group:
        if len(conf_2_files_only_first_group[confstr])<avg_cnt:
            print("!!!",confstr,"files cnt < avg_cnt")
            exit(1)

def get_each_group_prev_avg_cnt_file__compute_avg(drawconf,conf_2_files):
    avg_cnt=drawconf['avg_cnt']
    # sort
    for confstr in conf_2_files:
        conf_2_files[confstr].sort()
    # left avg_cnt files
    for confstr in conf_2_files:
        conf_2_files[confstr]=conf_2_files[confstr][:avg_cnt]
    # transform files 2 records
    conf_2_records={}
    for confstr in conf_2_files:
        file_records=[]
        for file in conf_2_files[confstr]:
            file_records.append(records_read.load_record_from_file(file))
        conf_2_records[confstr]=file_records
    # compute avg and transform records 2 one record
    conf_2_avg_record={}
    for confstr in conf_2_files:
        records=conf_2_records[confstr]
        avg_record=records_read.avg_records(records)
        conf_2_avg_record[confstr]=avg_record
    return conf_2_avg_record

def group_records(records,conf):
    group_by=conf['group']['by']
    group_types=conf['group']['types']
    groups=[{'group':group_type,'records':[]} for group_type in group_types]
    for record in records:
        attribute_value = getattr(record, group_by)
        groups[group_types.index(attribute_value)]['records'].append(record)
        
    # print("groups",groups)

    return groups

def to_draw_meta(groups,conf):
    def groups_value(groups,valueconf):
        def spec_values(records):
            def spec_value(record):
                cost_per_req=record.cost_per_req
                time_per_req=record.time_per_req
                waitsche_time_per_req =record.waitsche_time_per_req 
                coldstart_time_per_req=record.coldstart_time_per_req
                datarecv_time_per_req =record.datarecv_time_per_req 
                exe_time_per_req=record.exe_time_per_req
                rps=record.rps
                fn_container_cnt=record.fn_container_cnt
                cache_hit_ratio_per_node=record.cache_hit_ratio_per_node
                undone_req_cnt=record.undone_req_cnt
                req_done_time_avg_99p=record.req_done_time_avg_99p
                l1_cache_hit_ratio=record.l1_cache_hit_ratio
                l2_cache_hit_ratio=record.l2_cache_hit_ratio
                l3_cache_hit_ratio=record.l3_cache_hit_ratio
                overall_cache_hit_ratio=record.overall_cache_hit_ratio
                consistency_error_rate=record.consistency_error_rate
                max_inconsistency_window=record.max_inconsistency_window
                consistency_overhead=record.consistency_overhead
                consistency_level=record.consistency_level
                # score=0.0
                # rps=0.0
                # record.
                transs=valueconf['trans']
                if isinstance(transs, list):
                    
                    return [eval(trans) for trans in transs]
                else:
                    return eval(transs)
            def alias(record):
                def match_args(args):
                    for argkey in args:
                        if getattr(record, argkey)!=args[argkey]:
                            # print(argkey,getattr(record, argkey),args[argkey])
                            # record.print_attributes()
                            return False
                    return True
                for target_alias in conf['targets_alias']:
                    if match_args(target_alias[0]):
                        return  target_alias[1]
                print("err!!!!")
                exit(1)
            return [[alias(record),spec_value(record)] for record in records]

        return [{
            'group': group['group'],
            'values': spec_values(group['records'])
        } for group in groups]
    
    values=conf['values']
    res=[
        {
            'value_y': valueconf['alias'],
            'groups':groups_value(groups,valueconf)
        } for valueconf in values
    ]

    if 'sort_by' in conf:
        sort_by_value_alias=conf['sort_by'][0].keys().__iter__().__next__()
        find_value_index=None
        for v in res:
            if v['value_y']==sort_by_value_alias:
                find_value_index=res.index(v)
        if find_value_index==None:
            print("err!!!!!, sort by value not found")
            exit(1)
        
        # [
        #     {
        #         value_y: value_alias
        #         groups:[
        #             {
        #                 group: xxx
        #                 values: [
        #                     [record_alias, value]
        #                 ]
        #             }
        #         ]
        #     }
        # ]

        record_alias__values= res[find_value_index]['groups'][0]['values']
        
        def sort_access(target_alias):
            # get value of target
            v=None
            for record_alias__value in record_alias__values:
                # print("p: ",record_alias__value[0],target_alias[1])
                if record_alias__value[0]==target_alias[1]:
                    v=record_alias__value[1]
    
            if isinstance(v, list):
                return v[-1]
            return v
        conf['targets_alias']=sorted(conf['targets_alias'], key=sort_access)
        # # for reordered_rec_value in sort_value_records:
        # for value_groups in res:
        #     for group in value_groups['groups']:
        #         # sync group values as sort_value_records
        #         new_order_values=[None for _ in range(len(group['values']))]
        #         # find new index for each value
        #         for value in group['values']:
        #             # index by value[0]
        #             for new_index, sorted_value in enumerate(sort_value_records):
        #                 if value[0] == sorted_value[0]:
        #                     new_order_values[new_index] = value
        #                     break
        #         group['values'] = new_order_values
        

    return res


if __name__ == "__main__":
    pipeline()