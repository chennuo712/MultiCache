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

import records_read

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
                    nomatch_target=True
                    break
            if not nomatch_target:
                nomatch_targets=False
                break
        if nomatch_targets:
            continue
        new[confstr]=conf_2_files[confstr]
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
    return groups

def normalize_values(values, contemp_values):
    """根据 contemp_values 的结构动态归一化"""
    if isinstance(contemp_values, list):
        # 堆叠柱状图（如 Makespan）
        return [
            [v[i]/contemp_values[i] for i in range(len(contemp_values))]
            for v in values
        ]
    else:
        # 单值柱状图（如 Cost）
        return [v/contemp_values for v in values]

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
                
                transs=valueconf['trans']
                if isinstance(transs, list):
                    return [eval(trans) for trans in transs]
                else:
                    return eval(transs)
            def alias(record):
                def match_args(args):
                    for argkey in args:
                        if getattr(record, argkey)!=args[argkey]:
                            return False
                    return True
                for target_alias in conf['targets_alias']:
                    if match_args(target_alias[0]):
                        return target_alias[1]
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
        
        record_alias__values= res[find_value_index]['groups'][0]['values']
        
        def sort_access(target_alias):
            v=None
            for record_alias__value in record_alias__values:
                if record_alias__value[0]==target_alias[1]:
                    v=record_alias__value[1]
    
            if isinstance(v, list):
                return v[-1]
            return v
        conf['targets_alias']=sorted(conf['targets_alias'], key=sort_access)

    return res

def draw_with_draw_meta(drawmeta, conf):
    plotcnt = len(conf['values'])
    fig = plt.figure(figsize=(16, 3.0))
    
    outer_grid = fig.add_gridspec(1, plotcnt, wspace=0.1)
    
    bar_width = 0.25
    cache_policies = [
        ('contemp', '#FF4500'),
        ('ttl', '#90EE90'),
        ('lru', '#A9A9A9'),
        ('faascache', '#87CEEB'),
        ('cfc', '#FFA500'),
        ('duo', '#FF69B4'),
    ]
    colors = dict(cache_policies)
    
    # 添加图例在顶部
    legend_labels = ['Contemp','TTL-Based','LRU','FaasCache','CFC','Duo']
    handles = [plt.Rectangle((0,0),1,1, color=colors[policy[0]]) for policy in cache_policies]
    fig.legend(
        handles,
        legend_labels,
        bbox_to_anchor=(0.5, 0.9),  # 调整位置到顶部中央
        loc='upper center',
        ncol=len(cache_policies),
        frameon=False,
        fontsize='large'
    )

    # 获取所有值的全局最大高度
    global_max_height = 0
    for meta_item in drawmeta:
        for group in meta_item['groups']:
            for value in group['values']:
                raw_value = sum(value[1]) if isinstance(value[1], list) else value[1]
                global_max_height = max(global_max_height, raw_value)

    for plotidx in range(plotcnt):
        meta = drawmeta[plotidx]
        groups = meta['groups']
        
        inner_grid = outer_grid[plotidx].subgridspec(1, 3, wspace=0.08)
        inner_plots = [fig.add_subplot(inner_grid[0, i]) for i in range(3)]
        
        # 设置指标标题
        ax_title = fig.add_subplot(inner_grid[:, :])
        ax_title.set_title(meta['value_y'], pad=18)  # 增加 pad 值，为图例留出空间
        ax_title.axis('off')

        # 获取基准值（contemp）
        contemp_values = {}
        for group in groups:
            freq = group['group']
            for value in group['values']:
                if value[0].endswith('contemp.5)'):
                    contemp_values[freq] = sum(value[1]) if isinstance(value[1], list) else value[1]
                    break

        for subidx, (subplot, freq) in enumerate(zip(inner_plots, ['low', 'middle', 'high'])):
            # 修改y轴范围从0.5到1.65
            subplot.set_ylim(0.5, 1.65)
            
            if plotidx == 0 and freq == 'low':  # 只在第一个指标的第一个子图显示y轴刻度
                subplot.set_yticks(np.arange(0.5, 1.65, 0.5))
            else:
                subplot.set_yticks([])
            
            # 保留网格线
            subplot.grid(True, axis='y', linestyle='--', alpha=0.2)

            # 保留1.0的参考线
            subplot.axhline(y=1.0, color='black', linestyle='-', linewidth=0.5, alpha=0.2)

            # 添加边框
            for spine in subplot.spines.values():
                spine.set_visible(True)
                spine.set_linewidth(0.5)
                spine.set_color('black')

            # 添加顶部数值区域的边框
            rect = plt.Rectangle((-0.6, 1.5), # x位置调整到子图左边界
                               2.0, # 宽度增加以确保覆盖整个子图宽度
                               0.15, # height
                               fill=False,
                               color='black',
                               linewidth=0.5,
                               transform=subplot.transData)
            subplot.add_patch(rect)

            # 设置x轴范围以确保边框对齐
            subplot.set_xlim(-0.6, 1.2)  # 确保与Rectangle的范围一致

            current_group = None
            for group in groups:
                if group['group'] == freq:
                    current_group = group
                    break

            if current_group:
                x_pos = np.arange(1)
                
                for policy_idx, (policy_name, _) in enumerate(cache_policies):
                    for value in current_group['values']:
                        current_policy = value[0].split('ic(')[1].split(')')[0].split('.')[0]
                        if current_policy == policy_name:
                            raw_value = sum(value[1]) if isinstance(value[1], list) else value[1]
                            normalized_value = raw_value / contemp_values[freq]

                            bar = subplot.bar(
                                x_pos + (policy_idx-1.3) * bar_width,
                                normalized_value,
                                bar_width,
                                color=colors[policy_name],
                                edgecolor="black",
                                linewidth=0.5,
                                label=None
                            )

                            # 将数值标注固定在1.51位置
                            subplot.text(
                                x_pos[0] + (policy_idx-1) * bar_width,
                                1.51,
                                f'{normalized_value:.2f}',
                                ha='center',
                                va='bottom',
                                color='black',
                                fontsize=6,
                                rotation=90
                            )

                            # 调整连接线的终点
                            subplot.plot(
                                [x_pos[0] + (policy_idx-1) * bar_width, x_pos[0] + (policy_idx-1) * bar_width],
                                [normalized_value, 1.51],
                                'k-', linewidth=0.5, alpha=0.3
                            )
                            break

            # 设置x轴标签
            subplot.set_xticks([0.3])
            subplot.set_xticklabels([freq.lower()], ha='center')

    plt.tight_layout()
    plt.subplots_adjust(top=0.60,wspace=0.1)  # 为顶部图例留出空间
    plt.show()

def pipeline():
    import sys
    if len(sys.argv)!=2:
        print("usage: python draw_bar_normalized.py <xxx.yaml>")
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
        print(record.configstr)
    
    print("\n\n group_records")
    groups=group_records(records,drawconf)
    
    print("\n\n to_draw_meta")
    drawmeta=to_draw_meta(groups,drawconf)
    
    print("\n\n")
    pprint(drawmeta)
    draw_with_draw_meta(drawmeta,drawconf)

pipeline() 