import os
import re
import json

CUR_FPATH = os.path.abspath(__file__)
CUR_FDIR = os.path.dirname(CUR_FPATH)
os.chdir(CUR_FDIR)

def group_by_conf_files():
    """获取所有记录文件，按配置分组"""
    collect_by_config_str = {}
    if not os.path.exists("../serverless_sim/records"):
        return {}
    for rec in os.listdir("../serverless_sim/records"):
        if rec.find(".UTC_") == -1:
            continue
        prefix = rec.split(".UTC_")[0]
        if prefix not in collect_by_config_str:
            collect_by_config_str[prefix] = []
        collect_by_config_str[prefix].append(rec)
    return collect_by_config_str

class Frame:
    """单帧数据处理类"""
    idxs = {}
    def __init__(self, frame_arr):
        self.frame = frame_arr
        # 初始化索引
        if not self.idxs:
            with open("../serverless_sim/src/metric.rs", 'r', encoding="utf-8") as f:
                for line in f.readlines():
                    if line.find("const FRAME_IDX_") == -1:
                        continue
                    idx_name = line.split()[1][:-1]
                    idx_value = int(line.split()[4][:-1])
                    self.idxs[idx_name] = idx_value

    def get_coldstart_time(self):
        """获取冷启动延迟"""
        return self.frame[self.idxs['FRAME_IDX_REQ_WAIT_COLDSTART_TIME']]

class ColdStartRecord:
    """冷启动记录类"""
    def __init__(self, filename="", configstr=""):
        self.filename = filename
        self.configstr = configstr
        self.frames = []
        self.coldstart_delays = []

    def load_frames(self):
        """加载帧数据"""
        try:
            filepath = os.path.join("../serverless_sim/records", self.filename)
            with open(filepath, 'r') as f:
                data = json.load(f)
                if 'frames' in data:
                    self.frames = [Frame(frame) for frame in data['frames']]
                    # 提取所有冷启动延迟，不再过滤大于0的值
                    self.coldstart_delays = [
                        frame.get_coldstart_time() 
                        for frame in self.frames
                    ]
                    # 打印调试信息
                    zero_delays = sum(1 for d in self.coldstart_delays if d == 0)
                    if zero_delays > 0:
                        print(f"Found {zero_delays} zero delays in {self.filename}")
                    return True
        except Exception as e:
            print(f"Error loading frames from {self.filename}: {str(e)}")
        return False

def get_policy_name(config_str):
    """从配置字符串中提取缓存策略名称"""
    match = re.search(r"\.ic\((\w+?)\.", config_str)
    if match:
        policy = match.group(1).lower()
        return {
            "cfc": "CFC",
            "contemp": "Contemp",
            "duo": "Duo",
            "faascache": "FaasCache",
            "lru": "LRU",
            "ttl": "TTL",
        }.get(policy, policy.upper())
    return None

def load_cold_start_data(config_str, filenames):
    """加载指定配置的冷启动数据"""
    all_delays = []
    for filename in filenames:
        record = ColdStartRecord(filename, config_str)
        if record.load_frames():
            all_delays.extend(record.coldstart_delays)
    return all_delays

def load_all_cold_start_data():
    """加载所有配置的冷启动数据"""
    conf_2_files = group_by_conf_files()
    policy_delays = {}
    
    for config_str, files in conf_2_files.items():
        # 只处理哈希负载均衡的数据
        if 'scd(hash.)' not in config_str:
            continue
            
        policy_name = get_policy_name(config_str)
        if not policy_name:
            continue
            
        delays = load_cold_start_data(config_str, files)
        if delays:
            if policy_name not in policy_delays:
                policy_delays[policy_name] = []
            policy_delays[policy_name].extend(delays)
            zero_delays = sum(1 for d in delays if d == 0)
            total_delays = len(delays)
            print(f"Found {total_delays} delays ({zero_delays} zeros) for {policy_name} from {config_str}")
    
    return policy_delays

# 获取所有策略的冷启动延迟数据
policy_delays = load_all_cold_start_data()

# policy_delays 的结构：
# {
#     "Contemp": [delay1, delay2, ...],
#     "CFC": [delay1, delay2, ...],
#     ...
# } 