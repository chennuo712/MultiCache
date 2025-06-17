import os
CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
os.chdir(CUR_FDIR)

import requests
from pprint import pprint
import yaml
import re
import matplotlib.pyplot as plt
import numpy as np

import records_read

class PackedRecord:
    def __init__(self, raw_record):
        if len(raw_record) != 13:  # 增加字段数量
            raise ValueError("The input list must contain exactly 13 elements.")
        self.configstr = raw_record[0]
        self.cost_per_req = raw_record[1]
        self.time_per_req = raw_record[2]
        self.score = raw_record[3]
        self.rps = raw_record[4]
        self.coldstart_time_per_req = raw_record[5]
        self.waitsche_time_per_req = raw_record[6]
        self.datarecv_time_per_req = raw_record[7]
        self.exe_time_per_req = raw_record[8]
        self.fn_container_cnt = raw_record[9]  # 新增字段
        self.cache_hit_ratio_per_node = raw_record[10]
        self.undone_req_cnt = raw_record[11]
        self.filename = raw_record[12]
        
        self.parse_configstr()

    # 保持原有parse_configstr方法不变
    def parse_configstr(self):
        config_patterns = [
            (r'\.ic\(([^)]+)\)', 'instance_cache_policy')
        ]
        for pattern, *keys in config_patterns:
            match = re.search(pattern, self.configstr)
            if match:
                values = match.groups()
                for key, value in zip(keys, values):
                    setattr(self, key, value.split('.')[0])


def get_cache_policy_alias(config_str):
    """从配置字符串提取简化的缓存策略名称"""
    match = re.search(r'ic\(([\w_]+)\.', config_str)
    if match:
        return match.group(1)
    return "Unknown"

def get_record_filelist(drawconf):
    conf_2_files=records_read.group_by_conf_files()
    new={}
    for confstr in conf_2_files:
        conf=records_read.FlattenConfig(confstr)
        confjson=conf.json()
        
        nomatch_filter=False
        for drawfilter in drawconf['filter']:
            if drawfilter in confjson:
                if confjson[drawfilter]!=drawconf['filter'][drawfilter]:
                    nomatch_filter=True
                    break
        
        if nomatch_filter:
            continue

        nomatch_targets=True
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
    for confstr in conf_2_files:
        conf=records_read.FlattenConfig(confstr)
        if getattr(conf,first_group_k)==first_group_v:
            conf_2_files_only_first_group[confstr]=conf_2_files[confstr]

    for confstr in conf_2_files_only_first_group:
        if len(conf_2_files_only_first_group[confstr])<avg_cnt:
            print("!!!",confstr,"files cnt < avg_cnt")
            exit(1)

def get_each_group_prev_avg_cnt_file__compute_avg(drawconf,conf_2_files):
    avg_cnt=drawconf['avg_cnt']
    for confstr in conf_2_files:
        conf_2_files[confstr].sort()
    for confstr in conf_2_files:
        conf_2_files[confstr]=conf_2_files[confstr][:avg_cnt]
    conf_2_records={}
    for confstr in conf_2_files:
        file_records=[]
        for file in conf_2_files[confstr]:
            file_records.append(records_read.load_record_from_file(file))
        conf_2_records[confstr]=file_records
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

def to_draw_meta(groups,conf):
    def groups_value(groups,valueconf):
        def spec_values(records):
            def spec_value(record):
                return eval(valueconf['trans'], None, {
                    'cost_per_req': record.cost_per_req,
                    'time_per_req': record.time_per_req,
                    'waitsche_time_per_req': record.waitsche_time_per_req,
                    'coldstart_time_per_req': record.coldstart_time_per_req,
                    'datarecv_time_per_req': record.datarecv_time_per_req,
                    'exe_time_per_req': record.exe_time_per_req,
                    'rps': record.rps,
                    'fn_container_cnt': record.fn_container_cnt,  # 新增字段
                    'cache_hit_ratio_per_node': record.cache_hit_ratio_per_node,
                    'undone_req_cnt': record.undone_req_cnt
                })
            def alias(record):
                def match_args(args):
                    for argkey in args:
                        if getattr(record, argkey)!=args[argkey]:
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
    # 初始化画布
    plt.style.use('ggplot')
    plt.rcParams['font.sans-serif'] = ['Times New Roman']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 创建单个图表（因为只关注冷启动延迟）
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # 提取冷却常数值和对应的延迟数据
    cooling_constants = []
    latencies = []
    
    # 从第一个指标（冷启动延迟）和第一个分组中提取数据
    values = drawmeta[0]['groups'][0]['values']
    
    for value in values:
        # 从配置字符串中提取冷却常数
        match = re.search(r'contemp_(\d+)\.10', value[0])
        if match:
            num = int(match.group(1))
            if num == 99:  # 处理0.99的特殊情况
                cooling_constant = 0.99
            else:
                cooling_constant = num / 10  # 转换为实际的冷却常数值
            cooling_constants.append(cooling_constant)
            latencies.append(value[1])
    
    # 按冷却常数排序
    sorted_data = sorted(zip(cooling_constants, latencies))
    cooling_constants, latencies = zip(*sorted_data)
    
    # 绘制折线图
    ax.plot(cooling_constants, latencies, marker='o', linewidth=2, markersize=8)
    
    # 设置标题和标签
    # ax.set_title('冷启动延迟与冷却常数的关系', pad=20, fontsize=14)
    ax.set_xlabel('Cooling Factor', labelpad=10, color='black',fontsize=20)
    ax.set_ylabel('Cold Start Latency (ms)', labelpad=10, color='black',fontsize=20)
    
    # 设置网格
    ax.grid(True, linestyle='--', alpha=0.7)
    
    # 美化x轴刻度
    ax.set_xticks(cooling_constants)
    ax.set_xticklabels([f'{x:.1f}' for x in cooling_constants], fontsize=18,rotation=45)

    yticks =ax.get_yticks()
    ax.set_yticklabels([int(x*10) for x in yticks], fontsize=18)

    # 调整布局
    plt.tight_layout()
    plt.show()
    
def pipeline():
    import sys
    if len(sys.argv)!=2:
        print("usage: python draw_bar.py <xxx.yaml>")
        exit(1)

    yamlfilepath=sys.argv[1]
    drawconf=yaml.safe_load(open(yamlfilepath, 'r'))

    conf_2_files=get_record_filelist(drawconf)
    check_first_draw_group_match_avg_cnt(drawconf,conf_2_files)
    records=get_each_group_prev_avg_cnt_file__compute_avg(drawconf,conf_2_files)
    records=[records[confstr] for confstr in records]
    
    groups=group_records(records,drawconf)
    drawmeta=to_draw_meta(groups,drawconf)
    draw_with_draw_meta(drawmeta,drawconf)

pipeline()