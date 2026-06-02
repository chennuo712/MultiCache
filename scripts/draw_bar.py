import os
CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
# chdir to the directory of this script
os.chdir(CUR_FDIR)

import requests
from pprint import pprint
import yaml
import re
import matplotlib.pyplot as plt
import numpy as np

### doc: https://fvd360f8oos.feishu.cn/docx/RMjfdhRutoDmOkx4f4Lcl1sjnzd

# class PackedRecord:
#     # configstr.clone().into(),
#     # cost_per_req,
#     # time_per_req,
#     # score,
#     # rps.into(),
#     # f.time_str.clone().into()
#     raw_record=[]

#     configstr=""
#     cost_per_req=0.0
#     time_per_req=0.0
#     score=0.0
#     rps=0.0
#     coldstart_time_per_req=0.0
#     waitsche_time_per_req=0.0
#     datarecv_time_per_req=0.0
#     exe_time_per_req=0.0
    
#     filename=""

#     rand_seed=""
#     request_freq=""
#     dag_type=""
#     cold_start=""
#     scale_num=""
#     scale_down_exec=""
#     scale_up_exec=""
#     fn_type=""
#     instance_cache_policy=""
    

#     def __init__(self, raw_record):
#         if len(raw_record) != 10:
#             raise ValueError("The input list must contain exactly 10 elements.")
#         self.configstr = raw_record[0]
#         self.cost_per_req = raw_record[1]
#         self.time_per_req = raw_record[2]
#         self.score = raw_record[3]
#         self.rps = raw_record[4]
#         self.coldstart_time_per_req=raw_record[5]
#         self.waitsche_time_per_req=raw_record[6]
#         self.datarecv_time_per_req=raw_record[7]
#         self.exe_time_per_req=raw_record[8]
#         self.filename = raw_record[9]
        

#         # compute sub values by config str
#         self.parse_configstr()

#     def parse_configstr(self):
#         config_patterns = [
#             (r'sd(\w+)\.rf', 'rand_seed'),
#             (r'\.rf(\w+)\.', 'request_freq'),
#             (r'\.dt(\w+)\.', 'dag_type'),
#             (r'\.cs(\w+)\.', 'cold_start'),
#             (r'\.ft(\w+)\.', 'fn_type'),
#             (r'\.scl\(([^)]+)\)\(([^)]+)\)\(([^)]+)\)\.', 'scale_num', 'scale_down_exec', 'scale_up_exec'),
#             (r'\.scd\(([^)]+)\)', 'sche'),
#             (r'\.ic\(([^)]+)\)', 'instance_cache_policy')
#         ]

#         for pattern, *keys in config_patterns:
#             match = re.search(pattern, self.configstr)
#             if match:
#                 values = match.groups()
#                 for key, value in zip(keys, values):
#                     setattr(self, key, value)
#         self.print_attributes()

        
#     def print_attributes(self):
#         attributes = [
#             'configstr', 'cost_per_req', 'time_per_req', 'score', 'rps', 'filename',
#             'rand_seed', 'request_freq', 'dag_type', 'cold_start', 'fn_type', 
#             'scale_num', 'scale_down_exec', 'scale_up_exec', 'sche'
#         ]
#         for attr in attributes:
#             print(f"{attr}={getattr(self, attr)}")

import records_read
# {
#     confstr: [files...]
# }
def get_record_filelist(drawconf):
    conf_2_files=records_read.group_by_conf_files()
    # filter out we dont care
    new={}
    for confstr in conf_2_files:
        conf=records_read.FlattenConfig(confstr)
        confjson=conf.json()
        
        nomatch_filter=False

        # check match draw filter
        for drawfilter in drawconf['filter']:
            if drawfilter in confjson:
                if confjson[drawfilter]!=drawconf['filter'][drawfilter]:
                    # continue
                    nomatch_filter=True
                    break
        
        if nomatch_filter:
            continue


        nomatch_targets=True
        # check match draw targets_alias
        for target in drawconf['targets_alias']:
            nomatch_target=False
            for targetkey in target[0]:
                if targetkey not in confjson:
                    print("!!! invalid target alias with key",targetkey)
                    exit(1)
                if confjson[targetkey]!=target[0][targetkey]:
                    # continue
                    nomatch_target=True
                    break
            if not nomatch_target:
                nomatch_targets=False
                break
            # if invalid:
            #     continue
        if nomatch_targets:
            continue
        new[confstr]=conf_2_files[confstr]
    return new

# no return
# panic if check failed
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

# {
#     confstr: PackedRecord
# }
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

# [
#     {
#         group: xxx
#         values:[record]
#     }
# ]
def group_records(records,conf):
    group_by=conf['group']['by']
    group_types=conf['group']['types']
    groups=[{'group':group_type,'records':[]} for group_type in group_types]
    for record in records:
        attribute_value = getattr(record, group_by)
        groups[group_types.index(attribute_value)]['records'].append(record)
        
    # print("groups",groups)

    return groups

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

def draw_with_draw_meta(drawmeta, conf):
    # 预定义缓存策略颜色和显示顺序
    cache_policy_order = ['contemp','cfc',  'duo', 'lru', 'ttl']
    cache_policy_colors = {
        'contemp': '#FFB62B',
        'cfc': '#FC6B05',
        'duo': '#65B017',
        'lru': '#99D8DB',
        'ttl': '#8A2BE2'
    }

    # 创建图表
    fig, ax = plt.subplots(figsize=(15, 7))
    
    # X轴参数
    n_policies = 5
    bar_width = 0.15
    spacing = 0.4
    
    # 绘制柱子
    x_ticks = []
    x_labels = []
    current_x = 0
    
    for freq_idx, freq in enumerate(conf['group']['types']):
        group_start = current_x
        
        # 按固定顺序绘制策略柱子
        for policy_idx, policy in enumerate(cache_policy_order):
            x_pos = group_start + policy_idx * bar_width
            value = _get_value_by_freq_and_policy(drawmeta, freq, policy)
            ax.bar(x_pos, value, width=bar_width-0.02,
                  color=cache_policy_colors[policy],
                  edgecolor='black',
                  label=policy.upper())  # 添加label参数

        x_ticks.append(group_start + (n_policies-1)*bar_width/2)
        x_labels.append(freq.upper())
        current_x = group_start + n_policies*bar_width + spacing

    # 设置坐标轴
    ax.set_xticks(x_ticks)
    ax.set_xticklabels(x_labels, fontsize=12)
    ax.set_ylabel(drawmeta[0]['value_y'], fontsize=12)
    ax.grid(axis='y', linestyle='--', alpha=0.6)

    # 处理图例（关键修改部分）
    handles, labels = ax.get_legend_handles_labels()
    
    # 去重并保持顺序
    seen = set()
    unique_handles = []
    unique_labels = []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l)
            unique_handles.append(h)
            unique_labels.append(l)
    
    # 横向排列在顶部
    ax.legend(unique_handles, unique_labels,
             loc='lower center',
             bbox_to_anchor=(0.5, 1.05),  # 1.05表示在图表上方5%的位置
             ncol=5,  # 5个策略横向排列
             fontsize=10,
             title_fontsize=12,
             frameon=False,  # 去掉图例外框
             columnspacing=1.5  # 调整标签间距
            )

    # 调整顶部边距
    plt.subplots_adjust(top=0.85)
    
    plt.show()

def _get_value_by_freq_and_policy(drawmeta, freq, policy):
    """从数据中提取具体数值的辅助函数"""
    for value_meta in drawmeta:
        for group in value_meta['groups']:
            if group['group'] == freq:
                for value in group['values']:
                    # 假设value[0]包含策略标识符（如sd...ic(cfc.50)）
                    if f'ic({policy}.' in value[0]:
                        return float(value[1]) if not isinstance(value[1], list) else sum(value[1])
    return 0.0  # 默认值

# def draw_with_draw_meta(drawmeta, conf):
#     # 预定义五种缓存策略颜色
#     cache_policy_colors = {
#         'cfc': '#FC6B05',    # 橙色
#         'contemp': '#FFB62B', # 黄色
#         'duo': '#65B017',    # 绿色
#         'lru': '#99D8DB',    # 青色
#         'ttl': '#8A2BE2'     # 紫色
#     }

#     # 创建单一图表
#     fig, ax = plt.subplots(figsize=(15, 6))
    
#     # X轴参数
#     n_policies = 5  # 5种缓存策略
#     n_freq = 3      # low/mid/high
#     bar_width = 0.15
#     spacing = 0.6   # 不同负载类别之间的间隔
    
#     # 计算柱子位置
#     x_ticks = []
#     x_labels = []
#     current_x = 0
#     for freq_idx, freq in enumerate(conf['group']['types']):
#         # 每组负载的起始位置
#         group_start = current_x
        
#         # 绘制该负载下的五种策略柱子
#         for policy_idx, policy in enumerate(cache_policy_colors.keys()):
#             x_pos = group_start + policy_idx * bar_width
#             # 从数据中提取值（需要根据实际数据结构调整）
#             value = _get_value_by_freq_and_policy(drawmeta, freq, policy)
#             ax.bar(x_pos, value, width=bar_width-0.02, 
#                   color=cache_policy_colors[policy],
#                   edgecolor='black')
        
#         # 记录标签位置
#         x_ticks.append(group_start + (n_policies-1)*bar_width/2)
#         x_labels.append(freq.upper())
        
#         # 更新下一个组的起始位置
#         current_x = group_start + n_policies*bar_width + spacing

#     # 设置X轴
#     ax.set_xticks(x_ticks)
#     ax.set_xticklabels(x_labels, fontsize=12)
    
#     # 添加辅助网格线
#     ax.grid(axis='y', linestyle='--', alpha=0.6)
    
#     # 添加图例
#     legend_handles = [
#         plt.Rectangle((0,0),1,1, fc=cache_policy_colors[policy])
#         for policy in cache_policy_colors
#     ]
#     ax.legend(legend_handles, cache_policy_colors.keys(),
#              title='Cache Policy',
#              bbox_to_anchor=(1.02, 1),
#              loc='upper left')

#     plt.show()


# # 辅助函数：根据负载频率和策略获取值（需要根据实际数据结构实现）
# def _get_value_by_freq_and_policy(drawmeta, freq, policy):
#     # 这里需要根据实际数据结构实现数据匹配逻辑
#     # 示例伪代码：
#     for value_group in drawmeta:
#         for group in value_group['groups']:
#             if group['group'] == freq:
#                 for value in group['values']:
#                     if policy in value[0]:  # 假设value[0]包含策略标识
#                         return value[1] if not isinstance(value[1], list) else sum(value[1])
#     return 0
# 调整子图的边距以确保图例不会覆盖图表内容
    
def pipeline():
    import sys
    if len(sys.argv)!=2:
        print("usage: python draw_bar.py <xxx.yaml>")
        exit(1)

    yamlfilepath=sys.argv[1]

    drawconf=yaml.safe_load(open(yamlfilepath, 'r'))

    print("\n\n get_record_filelist")
    conf_2_files=get_record_filelist(drawconf)

    print("\n\n check_first_draw_group_match_avg_cnt")
    check_first_draw_group_match_avg_cnt(drawconf,conf_2_files)

    print("\n\n get_each_group_prev_avg_cnt_file__compute_avg")
    records=get_each_group_prev_avg_cnt_file__compute_avg(drawconf,conf_2_files)

    print("\n\n flatten records")
    records=[records[confstr] for confstr in records]
    for record in records:
        # record.print_attributes()
        print(record.configstr)
    # print([r.configstr for r in records])
    
    print("\n\n group_records")
    groups=group_records(records,drawconf)
    
    print("\n\n to_draw_meta")
    drawmeta=to_draw_meta(groups,drawconf)
    
    print("\n\n")
    pprint(drawmeta)
    draw_with_draw_meta(drawmeta,drawconf)
    # import matplotlib.pyplot as plt
    # from collections import defaultdict


    # groups = defaultdict(list)
    # for record in records:
    #     key_parts = record[0].split(".")
    #     common_part = ".".join(key_parts[1:5])
    #     algorithm = "".join(key_parts[5:len(key_parts) - 1])
    #     algorithm = algorithm.split(")")
    #     algorithm = ")\n".join(algorithm)
    #     record[5] = algorithm
    #     groups[common_part].append(record)


    # for group_name, group_records in groups.items():
    #     data_points = {
    #         'Cost': [row[1] for row in group_records],
    #         'Latency': [row[2] for row in group_records],
    #     }
    #     costs = data_points['Cost']
    #     latencies = data_points['Latency']
    #     value_for_money = [(1 / latency) * 1 / cost if cost != 0 and latency != 0 else float('inf') for latency, cost in zip(latencies, costs)]  # 防止除以零
    #     data_points['Performance_Cost'] = value_for_money

    #     x_ticks = [row[5] for row in group_records]

    #     for key, values in data_points.items():
    #         plt.figure()
    #         bars = plt.bar(range(len(values)), values)
    #         plt.title(f'Comparison of {key} in {group_name}')
    #         plt.xlabel('Experiment')
    #         plt.ylabel(key)
    #         plt.xticks(range(len(values)), x_ticks, fontsize = 9)
    #         plt.subplots_adjust(bottom = 0.21)

    #         for bar in bars:
    #             height = bar.get_height()
    #             plt.text(bar.get_x() + bar.get_width() / 2, height, f'{height:.4f}', ha='center', va='bottom')

    #         plt.show()

pipeline()