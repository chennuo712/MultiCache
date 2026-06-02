use core::cmp::Ordering;
use std::cell::RefMut;
use std::collections::{HashMap, VecDeque};
use std::{cell::RefCell, cmp::Eq, fmt::Debug, hash::Hash, rc::Rc};

use rand::Rng;

use super::InstanceCachePolicy;
use crate::fn_dag::FnContainer;
use crate::sim_env::SimEnv;
use serde::{Deserialize, Serialize};

// ...所有可调参数...
#[derive(Serialize, Deserialize)]
pub struct TempConfig {
    cooling_constant: f64, //冷却常数
    insulation_time: u32,  //保温时间
    env_temperature: f64,
    cache_ttl_frames: u32, // 新增TTL配置
                           // prefetch_threshold: f64, // 预取触发阈值
}

impl TempConfig {
    pub fn new_test() -> TempConfig {
        TempConfig {
            cooling_constant: 0.5,
            insulation_time: 0,
            env_temperature: 0.0,
            cache_ttl_frames: rand::thread_rng().gen_range(5..10), // 新增TTL配置
                                                                   // prefetch_threshold: 0.8, // 预取触发阈值
        }
    }
}

//历史队列的可调参数
#[derive(Serialize, Deserialize)]
pub struct HisTempConfig {
    cooling_constant: f64, //冷却常数
    insulation_time: u32,  //保温时间
    env_temperature: f64,
}

impl HisTempConfig {
    pub fn new_test() -> HisTempConfig {
        HisTempConfig {
            cooling_constant: 0.5,
            insulation_time: 0,
            env_temperature: 0.0,
        }
    }
}

// 主副队列双向链表节点
pub struct TempListNode<Payload> {
    conid: Option<Payload>, // None when dummy
    prev: Option<Rc<RefCell<TempListNode<Payload>>>>,
    next: Option<Rc<RefCell<TempListNode<Payload>>>>,

    last_call_time: Option<u32>,    //上次调用帧号
    last_temperature: f64,          //上次调用后当时温度，下次调用时即可视为初始温度再去计算
    call_count: u64,                //总调用次数
    avg_call_interval: Option<f64>, //调用的平均间隔帧数
    conf: TempConfig,
    ttl_frame: Option<u32>,
}

unsafe impl<Payload> Send for TempListNode<Payload> {}
unsafe impl<Payload> Sync for TempListNode<Payload> {}

impl<Payload> TempListNode<Payload> {
    pub fn new(key: Option<Payload>) -> Rc<RefCell<Self>> {
        Rc::new(RefCell::new(TempListNode {
            conid: key,
            prev: None,
            next: None,
            call_count: 0,
            last_call_time: None,
            avg_call_interval: None,
            last_temperature: 0.0,
            conf: TempConfig::new_test(),
            ttl_frame: None,
        }))
    }

    //记录一次调用
    //容器被调用时记录其相关信息，包括更新：call_count、last_call_time、avg_call_interval、last_temperature
    pub fn record_call(
        &mut self,
        current_frame: u32,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
        env: &SimEnv,
    ) {
        if let Some(last_frame) = self.last_call_time {
            //检查是否有上次调用帧号
            let interval = current_frame - last_frame; //计算当前时间与上次调用间隔帧数
            self.update_avg_call_interval(interval);
        }

        self.call_count += 1;

        // 计算最新的温度，里面包含计算衰减后的温度
        self.last_temperature = self.calculate_temperature(
            current_frame,
            cold_start_time,
            cold_start_cpu_use,
            cold_start_mem_use,
            env,
        );

        //计算衰减后的温度需要上次调用时间，故算完再更新
        self.last_call_time = Some(current_frame); //更新最后一次调用时间为当前时间

        // 更新TTL
        self.update(current_frame, self.conf.cache_ttl_frames);
    }

    //更新平均调用时间间隔
    pub fn update_avg_call_interval(&mut self, interval: u32) {
        match self.avg_call_interval {
            Some(avg) => {
                if interval as f64 > (2.0 * avg) {
                    // 如果当前时间间隔大于两倍的平均时间间隔，认为是新的调用
                    self.avg_call_interval = None;
                    //新调用则将调用次数更新为1（这里修改成0，record_call方法中后面的步骤会加1）
                    self.call_count = 0;
                } else {
                    // 否则，更新平均时间间隔
                    let new_avg = (avg + interval as f64) / 2.0;
                    self.avg_call_interval = Some(new_avg);
                }
            }
            None => {
                // 如果没有之前的平均时间间隔，直接设置为当前时间间隔
                self.avg_call_interval = Some(interval as f64);
            }
        }
    }

    //温度计算，先算时间衰减，再算本次调用增加
    //本方法用于 计算本次被调用的容器的温度
    pub fn calculate_temperature(
        &self,
        current_frame: u32,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
        _env: &SimEnv,
    ) -> f64 {
        let cs_cpu_use = cold_start_cpu_use as f64;
        let cs_mem_use = cold_start_mem_use as f64;
        let cold_start_time = cold_start_time as f64;

        if self.call_count == 1 {
            //第一次调用，给一个初始温度
            // cpu_use_rate * mem_use_rate * 1.0
            // cold_start_time * cs_cpu_use * cs_mem_use
            // cold_start_time * cs_cpu_use * cs_mem_use
            cold_start_time * cs_mem_use * cs_cpu_use
        } else {
            // 先计算时间衰减后的温度
            let attenuated_temperature = self.calculate_attenuation(current_frame);

            attenuated_temperature
                + (cold_start_time * cs_mem_use * cs_cpu_use / self.avg_call_interval.unwrap())
            // + (cold_start_time * cs_cpu_use * cs_mem_use / self.avg_call_interval.unwrap())
        }
    }

    //参考液体冷却（牛顿冷却定律）
    //env_temperature：环境温度
    //cooling_constant:冷却常数
    //insulation_time:保温时间(帧数)
    pub fn calculate_attenuation(&self, current_frame: u32) -> f64 {
        let cooling_constant = self.conf.cooling_constant; //冷却常数。表示每单位时间温度下降 8%
        let mut insulation_time = self.conf.insulation_time; //保温时间。若为第一次调用则温度立即衰减
        let env_temperature = self.conf.env_temperature; //环境温度设置为 0

        //cur2last_interval: 当前距离上次调用的间隔帧数
        let mut cur2last_interval = 0 as u32;
        if let Some(last_frame) = self.last_call_time {
            //检查是否有上次调用时间
            cur2last_interval = current_frame - last_frame; //计算当前时间与上次调用时间间隔
        }

        if let Some(avg) = self.avg_call_interval {
            insulation_time = (cooling_constant / avg) as u32;
        }

        if cur2last_interval <= insulation_time {
            // 在保温时间内，温度保持不变
            self.last_temperature
        } else {
            // 超过保温时间后，按牛顿冷却定律衰减
            // let env_temperature = env_temperature / 2.0; //环境温度设置为当前缓存最低温的一半
            let initial_temperature = self.last_temperature;
            let decay_time = (cur2last_interval - insulation_time) as f64; //超出保温时间的帧数
            let temperature = env_temperature
                + (initial_temperature - env_temperature) * (-cooling_constant * decay_time).exp();
            temperature
        }
    }

    // 新增过期检查方法
    pub fn is_expired(&self, current_frame: u32) -> bool {
        self.ttl_frame.map_or(false, |ttl| ttl <= current_frame)
    }

    //纯更新，该方法通常用在 判断出容器未过期或不能被移除后 再调用，故无需在这个方法里再判断是否过期
    fn update(&mut self, current_frame: u32, ttl_frames: u32) {
        self.last_call_time = Some(current_frame);
        self.ttl_frame = Some(current_frame + ttl_frames);
    }
}

//历史记录———历史列表里的每条记录的结构体
pub struct HistoryList<Payload: Eq + Hash + Clone + Debug> {
    conid: Payload,                 //容器id
    last_call_time: Option<u32>,    //上次调用帧号
    last_temperature: f64,          //上次调用后当时温度，下次调用时即可视为初始温度再去计算
    call_count: u64,                //总调用次数
    avg_call_interval: Option<f64>, //调用的平均时间间隔
    conf: HisTempConfig,
    call_timestamps: VecDeque<u32>, // 新增调用时间序列
}

impl<Payload: Eq + Hash + Clone + Debug> HistoryList<Payload> {
    /// 创建一个新的历史记录列表
    pub fn new(key: Payload) -> Rc<RefCell<Self>> {
        Rc::new(RefCell::new(HistoryList {
            conid: key,
            call_count: 0,
            last_call_time: None,
            avg_call_interval: None,
            last_temperature: 0.0,
            conf: HisTempConfig::new_test(),
            call_timestamps: VecDeque::new(),
        }))
    }

    //记录一次调用
    //容器被调用时记录其相关信息，包括更新：call_count、last_call_time、avg_call_interval、last_temperature
    pub fn record_his_call(
        &mut self,
        current_frame: u32,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
    ) {
        self.call_timestamps.push_back(current_frame);

        if let Some(last_frame) = self.last_call_time {
            //检查是否有上次调用时间
            let interval = current_frame - last_frame; //计算当前时间与上次调用时间间隔
            self.update_his_avg_call_interval(interval);
        }

        self.call_count += 1;

        // 计算最新的温度，里面包含计算衰减后的温度
        self.last_temperature = self.calculate_his_temperature(
            current_frame,
            cold_start_time,
            cold_start_cpu_use,
            cold_start_mem_use,
        );

        //计算衰减后的温度需要上次调用时间，故算完再更新
        self.last_call_time = Some(current_frame); //更新最后一次调用时间为当前时间
    }

    // 新增方法：获取有效间隔序列
    pub fn get_valid_intervals(&self) -> Vec<u32> {
        self.call_timestamps
            .iter()
            .zip(self.call_timestamps.iter().skip(1))
            .map(|(a, b)| b - a)
            .collect()
    }

    //更新平均调用时间间隔
    pub fn update_his_avg_call_interval(&mut self, interval: u32) {
        match self.avg_call_interval {
            Some(avg) => {
                if interval as f64 > (2.0 * avg) {
                    // 如果当前时间间隔大于两倍的平均时间间隔，认为是新的调用
                    self.avg_call_interval = Some(interval as f64);
                    //新调用则将调用次数更新为1（这里修改成0，record_call方法中后面的步骤会加1）
                    self.call_count = 0;
                } else {
                    // 否则，更新平均时间间隔
                    let new_avg = (avg + interval as f64) / 2.0;
                    self.avg_call_interval = Some(new_avg);
                }
            }
            None => {
                // 如果没有之前的平均时间间隔，直接设置为当前时间间隔
                self.avg_call_interval = Some(interval as f64);
            }
        }
    }

    //温度计算，先算时间衰减，再算本次调用增加
    //本方法用于 计算本次被调用的容器的温度
    pub fn calculate_his_temperature(
        &self,
        current_frame: u32,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
    ) -> f64 {
        let cold_start_time = cold_start_time as f64;
        let cs_cpu_use = cold_start_cpu_use as f64;
        let cs_mem_use = cold_start_mem_use as f64;

        if self.call_count == 1 {
            //第一次调用，给一个初始温度
            //新闻热词0->1
            // cold_start_time * cs_cpu_use * cs_mem_use
            cold_start_time * cs_mem_use * cs_cpu_use
        } else {
            // 先计算时间衰减后的温度
            let attenuated_temperature =
                self.calculate_his_attenuation(current_frame, cold_start_time);
            // 计算本次调用增加的温度
            attenuated_temperature
                + (cold_start_time * cs_cpu_use * cs_mem_use / self.avg_call_interval.unwrap())
        }
    }

    //参考液体冷却（牛顿冷却定律）
    //env_temperature：环境温度
    //cooling_constant:冷却常数
    //insulation_time:保温时间(帧数)
    pub fn calculate_his_attenuation(&self, current_frame: u32, _cold_start_time: f64) -> f64 {
        let cooling_constant = self.conf.cooling_constant; //冷却常数。表示每单位时间温度下降 8%
        let insulation_time = self.conf.insulation_time; //保温时间。若为第一次调用则温度立即衰减
        let env_temperature = self.conf.env_temperature; //环境温度设置为 0

        //cur2last_interval: 当前距离上次调用的间隔帧数
        let mut cur2last_interval = 0 as u32;
        if let Some(last_frame) = self.last_call_time {
            //检查是否有上次调用时间
            cur2last_interval = current_frame - last_frame; //计算当前时间与上次调用时间间隔
        }

        if cur2last_interval <= insulation_time {
            // 在保温时间内，温度保持不变
            self.last_temperature
        } else {
            // 超过保温时间后，按牛顿冷却定律衰减
            // let env_temperature = env_temperature / 2.0; //环境温度设置为当前缓存最低温的一半
            let initial_temperature = self.last_temperature;
            let decay_time = (cur2last_interval - insulation_time) as f64; //超出保温时间的帧数
            let temperature = env_temperature
                + (initial_temperature - env_temperature) * (-cooling_constant * decay_time).exp();
            temperature
        }
    }
}

/// 真正的历史列表————容器历史记录管理器
pub struct HistoryManager<Payload: Eq + Hash + Clone + Debug> {
    history: HashMap<Payload, Rc<RefCell<HistoryList<Payload>>>>, // 映射容器ID到HistoryList
}

impl<Payload: Eq + Hash + Clone + Debug> HistoryManager<Payload> {
    /// 创建一个新的历史记录管理器
    pub fn new() -> Self {
        HistoryManager {
            history: HashMap::new(),
        }
    }

    pub fn hisman_record_call(
        &mut self,
        conid: Payload,
        current_frame: u32,
        _env: &SimEnv,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
    ) {
        let history_list = self
            .history
            .entry(conid.clone())
            .or_insert_with(|| HistoryList::new(conid));

        history_list.borrow_mut().record_his_call(
            current_frame,
            cold_start_time,
            cold_start_cpu_use,
            cold_start_mem_use,
        );
    }
}

//容器温度缓存
pub struct ContempCache<Payload: Eq + Hash + Clone + Debug> {
    // node_id: usize,
    capacity: usize,
    cache: HashMap<Payload, Rc<RefCell<TempListNode<Payload>>>>,
    head: Rc<RefCell<TempListNode<Payload>>>,
    tail: Rc<RefCell<TempListNode<Payload>>>,
    history_manager: HistoryManager<Payload>,
    conf: TempConfig,
}

unsafe impl<Payload: Eq + Hash + Clone + Debug> Send for ContempCache<Payload> {}

impl<Payload: Eq + Hash + Clone + Debug> InstanceCachePolicy<Payload> for ContempCache<Payload> {
    fn get(
        &mut self,
        key: Payload,
        _fncon: &RefMut<'_, FnContainer>,
        _env: &SimEnv,
    ) -> Option<Payload> {
        // let current_frame = env.current_frame() as u32;
        // let cs_cpu_use = env.func(fncon.fn_id.clone()).cold_start_container_cpu_use;
        // let cs_mem_use = env.func(fncon.fn_id.clone()).cold_start_container_mem_use;
        // let cold_start_time = env.func(fncon.fn_id.clone()).cold_start_time;

        if let Some(_node) = self.cache.get(&key) {
            // node.borrow_mut().record_call(
            //     current_frame,
            //     cold_start_time,
            //     cs_cpu_use,
            //     cs_mem_use,
            //     env,
            // );
            Some(key)
        } else {
            None
        }
    }

    fn put(
        &mut self,
        key: Payload,
        mut can_be_evict: Box<dyn FnMut(&Payload) -> bool>,
        env: &SimEnv,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
    ) -> (Option<Payload>, bool) {
        let current_frame = env.current_frame() as u32;

        // 统一记录到历史管理器（新增）
        self.history_manager.hisman_record_call(
            key.clone(),
            current_frame,
            env,
            cold_start_time,
            cold_start_cpu_use,
            cold_start_mem_use,
        );

        //找到了，id为None，put成功
        if let Some(node) = self.cache.get(&key) {
            node.borrow_mut().record_call(
                current_frame,
                cold_start_time,
                cold_start_cpu_use,
                cold_start_mem_use,
                env,
            );
            return (None, true);
        }

        //2.没有call_count=0的。或者都不能删，再去看温度
        //判断空间是否足够，足够直接加，不够的话，
        // 直接淘汰逻辑
        if self.cache.len() == self.capacity {
            //计算当前容器温度
            let key_temp = self
                .history_manager
                .history
                .get(&key.clone())
                .unwrap()
                .borrow()
                .calculate_his_temperature(
                    current_frame,
                    cold_start_time,
                    cold_start_cpu_use,
                    cold_start_mem_use,
                );

            let temp_candidates: Vec<(f64, Payload)> = self
                .get_sorted_temperatures(current_frame)
                .into_iter()
                .filter(|(temp, _conid)| *temp <= key_temp)
                .collect();

            for (_temp, conid) in temp_candidates {
                if can_be_evict(&conid) {
                    self.list_remove_all(&conid);
                    self.add_all(
                        key.clone(),
                        current_frame,
                        cold_start_time,
                        cold_start_cpu_use,
                        cold_start_mem_use,
                        env,
                    );
                    return (Some(conid), true);
                }
            }
            (None, false)
        } else {
            self.add_all(
                key.clone(),
                current_frame,
                cold_start_time,
                cold_start_cpu_use,
                cold_start_mem_use,
                env,
            );
            (None, true)
        }
    }

    fn remove_all(&mut self, key: &Payload) -> bool {
        if let Some(node) = self.cache.remove(key) {
            self.remove_node(node);
            return true;
        }
        false
    }

    fn check_if_prefetch(&mut self, _current_frame: u32, _env: &SimEnv) -> Vec<Payload> {
        let v = Vec::new();
        v
    }
}

impl<Payload: Eq + Hash + Clone + Debug> ContempCache<Payload> {
    /// 创建一个新的缓存队列
    pub fn new(
        capacity: usize,
        //  node_id: usize,
        //  env: NonNull<SimEnv>
    ) -> Self {
        let head = TempListNode::new(None); // 头部哨兵节点
        let tail = TempListNode::new(None); // 尾部哨兵节点

        // 初始化头部和尾部哨兵节点
        head.borrow_mut().next = Some(tail.clone());
        tail.borrow_mut().prev = Some(head.clone());

        let capacity = capacity; // 缓存容量

        ContempCache {
            // node_id,
            capacity,
            cache: HashMap::new(),
            head,
            tail,
            history_manager: HistoryManager::new(),
            conf: TempConfig::new_test(),
            // env,
        }
    }

    /// 在缓存队列中查找节点(遍历)
    pub fn find(&self, key: &Payload) -> Option<Rc<RefCell<TempListNode<Payload>>>> {
        let mut current = self.head.borrow().next.as_ref().cloned();
        while let Some(node) = current {
            let node_ref = node.borrow();
            if node_ref.conid.as_ref() == Some(key) {
                return Some(node.clone());
            }
            current = node_ref.next.as_ref().cloned();
        }
        None
    }

    //添加节点到双向链表尾部
    fn add_node(&mut self, node: Rc<RefCell<TempListNode<Payload>>>) {
        let prev = self.tail.borrow().prev.clone().unwrap();
        node.borrow_mut().next = Some(self.tail.clone());
        self.tail.borrow_mut().prev = Some(node.clone());
        node.borrow_mut().prev = Some(prev.clone());
        prev.borrow_mut().next = Some(node.clone());
    }

    // 将新节点插入到尾部哨兵节点前面
    // 添加到缓存中
    fn add_all(
        &mut self,
        key: Payload,
        current_frame: u32,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
        env: &SimEnv,
    ) {
        let new_node = TempListNode::new(Some(key.clone()));
        // 将新节点插入到尾部哨兵节点前面
        new_node.borrow_mut().record_call(
            current_frame,
            cold_start_time,
            cold_start_cpu_use,
            cold_start_mem_use,
            env,
        );
        self.add_node(new_node.clone());

        // 将新容器添加到缓存中
        self.cache.insert(key, new_node);
    }

    fn add_all_by_history_delete(&mut self, history_evict_node: Rc<RefCell<HistoryList<Payload>>>) {
        let warm_node = TempListNode::new(Some(history_evict_node.borrow().conid.clone()));

        warm_node.borrow_mut().last_call_time = history_evict_node.borrow().last_call_time;
        warm_node.borrow_mut().last_temperature = history_evict_node.borrow().last_temperature;
        warm_node.borrow_mut().call_count = history_evict_node.borrow().call_count;
        warm_node.borrow_mut().avg_call_interval = history_evict_node.borrow().avg_call_interval;

        // 将新节点插入到尾部哨兵节点前面
        self.add_node(warm_node.clone());
        // 将新容器添加到缓存中
        self.cache
            .insert(history_evict_node.borrow().conid.clone(), warm_node);
    }

    //移除双向链表中的节点
    fn remove_node(&mut self, node: Rc<RefCell<TempListNode<Payload>>>) {
        let prev = node.borrow().prev.clone().unwrap();
        let next = node.borrow().next.clone().unwrap();
        prev.borrow_mut().next = Some(next.clone());
        next.borrow_mut().prev = Some(prev);
    }

    //移除双向链表中的节点，以及删除缓存中的数据
    fn list_remove_all(&mut self, key: &Payload) -> bool {
        if let Some(node) = self.cache.remove(key) {
            self.remove_node(node);
            return true;
        }
        false
    }

    /// 获取缓存中容器的最低温度(当前时刻衰减后)
    pub fn get_min_temperature(
        &self,
        current_frame: u32,
        _env: &SimEnv,
        _cold_start_time: usize,
    ) -> f64 {
        // let now = Instant::now();
        self.cache
            .values()
            .map(|node| {
                let node_borrowed = node.borrow();
                // let elapsed_time = now.duration_since(node_borrowed.last_call_time.unwrap_or(now));
                node_borrowed.calculate_attenuation(current_frame)
            })
            .fold(f64::INFINITY, |min, temp| min.min(temp))
    }

    /// 获取当前时刻缓存中所有节点的衰减温度和ID，并按温度从小到大排序
    pub fn get_sorted_temperatures(&self, current_frame: u32) -> Vec<(f64, Payload)> {
        let mut entries: Vec<(f64, Payload)> = self
            .cache
            .iter()
            .map(|(conid, node)| {
                (
                    node.borrow().calculate_attenuation(current_frame),
                    conid.clone(),
                )
            })
            .collect();

        // 对温度进行排序
        entries.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(Ordering::Equal));

        entries
    }
}

mod prediction {
    // 改进后的预测算法（动态权重+趋势分析）
    pub fn predict_next_interval(intervals: &[u32]) -> Option<u32> {
        if intervals.is_empty() {
            return None;
        }

        // 异常值过滤（超过3倍标准差）
        let filtered = filter_outliers(intervals);

        match filtered.len() {
            0 => None,
            1 => Some(filtered[0]),
            2 => weighted_moving_average(&filtered, 0.6), //加权移动平均
            3 => exponential_smoothing(&filtered, 0.3),   //指数平滑
            4..=6 => dynamic_weighted_average(&filtered),
            _ => linear_regression_prediction(&filtered),
        }
    }

    /// 加权移动平均（专为2个数据点优化）
    /// intervals: 时间间隔数据（按时间顺序排列，旧数据在前，新数据在后）
    /// recent_weight: 最近一个数据点的权重系数（0.0 ~ 1.0）
    pub fn weighted_moving_average(intervals: &[u32], recent_weight: f64) -> Option<u32> {
        // 输入验证
        assert!(intervals.len() == 2, "本实现专为2个数据点优化");
        assert!(
            (0.0..=1.0).contains(&recent_weight),
            "权重系数必须在0-1之间"
        );

        // 反转数据顺序（确保新数据在前）
        let reversed = [intervals[1], intervals[0]];

        // 计算加权平均值
        let weighted_sum =
            reversed[0] as f64 * recent_weight + reversed[1] as f64 * (1.0 - recent_weight);

        // 向上取整返回
        Some(weighted_sum.ceil() as u32)
    }

    // 指数平滑法
    fn exponential_smoothing(intervals: &[u32], alpha: f64) -> Option<u32> {
        let mut forecast = intervals[0] as f64;
        for &val in &intervals[1..] {
            forecast = alpha * val as f64 + (1.0 - alpha) * forecast;
        }
        Some(forecast.ceil() as u32)
    }

    // 动态权重调整（基于方差）
    fn dynamic_weighted_average(intervals: &[u32]) -> Option<u32> {
        let n = intervals.len();
        let weights = calculate_dynamic_weights(intervals);

        let weighted_sum: f64 = intervals
            .iter()
            .rev()
            .take(n)
            .enumerate()
            .map(|(i, &val)| val as f64 * weights[i])
            .sum();

        Some((weighted_sum / weights.iter().sum::<f64>()).ceil() as u32)
    }

    // 线性回归预测
    fn linear_regression_prediction(intervals: &[u32]) -> Option<u32> {
        let n = intervals.len() as f64;
        let sum_x: f64 = (0..intervals.len()).map(|x| x as f64).sum();
        let sum_y: f64 = intervals.iter().map(|&y| y as f64).sum();
        let sum_xy: f64 = intervals
            .iter()
            .enumerate()
            .map(|(x, &y)| x as f64 * y as f64)
            .sum();
        let sum_x2: f64 = (0..intervals.len()).map(|x| (x * x) as f64).sum();

        let slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x.powi(2));
        let intercept = (sum_y - slope * sum_x) / n;

        // 预测下一个时间点
        let next_x = intervals.len() as f64;
        Some((slope * next_x + intercept).ceil() as u32)
    }

    // 异常值过滤（3σ原则）
    fn filter_outliers(data: &[u32]) -> Vec<u32> {
        let mean = data.iter().map(|&x| x as f64).sum::<f64>() / data.len() as f64;
        let variance =
            data.iter().map(|&x| (x as f64 - mean).powi(2)).sum::<f64>() / data.len() as f64;
        let std_dev = variance.sqrt();

        data.iter()
            .filter(|&&x| (x as f64 - mean).abs() <= 3.0 * std_dev)
            .cloned()
            .collect()
    }

    // 动态权重计算（基于近期变化趋势）
    fn calculate_dynamic_weights(data: &[u32]) -> Vec<f64> {
        let n = data.len();
        let mut weights = vec![1.0; n];

        // 计算变化趋势
        let mut trend = 0.0;
        for i in 1..n {
            let diff = data[i] as f64 - data[i - 1] as f64;
            trend += diff.signum(); // 趋势方向累积
        }

        // 调整权重
        if trend.abs() > (n as f64 / 2.0) {
            // 强趋势时加大近期权重
            for i in 0..n {
                weights[i] = (i + 1) as f64;
            }
        } else {
            // 平稳时使用指数衰减权重
            let decay: f64 = 1.2; // 明确指定 decay 为 f64 类型
            for i in 0..n {
                weights[i] = decay.powf((n - i) as f64); // 现在可以正确调用 powf
            }
        }

        // 归一化权重
        let sum: f64 = weights.iter().sum();
        weights.iter().map(|w| w / sum).collect()
    }

    // 改进后的预取条件判断（带置信度评估）
    pub fn should_prefetch(
        predicted_interval: Option<u32>,
        current_frame: u32,
        last_call: Option<u32>,
        intervals: &[u32],
    ) -> bool {
        match (predicted_interval, last_call) {
            (Some(pred), Some(last)) => {
                let elapsed = current_frame - last;
                let confidence = calculate_confidence(intervals);

                // 动态阈值调整
                let base_threshold = (pred as f64 * 0.75) as u32;
                let adjusted_threshold = (base_threshold as f64 * confidence) as u32;

                elapsed >= adjusted_threshold
            }
            _ => false,
        }
    }

    // 计算预测置信度（0-1）
    fn calculate_confidence(intervals: &[u32]) -> f64 {
        if intervals.len() < 2 {
            return 0.5;
        }

        let mean = intervals.iter().sum::<u32>() as f64 / intervals.len() as f64;
        let variance = intervals
            .iter()
            .map(|&x| (x as f64 - mean).powi(2))
            .sum::<f64>()
            / intervals.len() as f64;

        // 方差越小置信度越高
        1.0 / (1.0 + variance.sqrt()).min(1.0)
    }
}
