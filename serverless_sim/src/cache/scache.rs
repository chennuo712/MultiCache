use core::cmp::Ordering;

use std::cell::RefMut;
use std::collections::HashMap;
use std::{cell::RefCell, cmp::Eq, fmt::Debug, hash::Hash, rc::Rc};

use super::InstanceCachePolicy;
use crate::fn_dag::{EnvFnExt, FnContainer};
use crate::sim_env::SimEnv;

// 双向链表节点
pub struct ScacheListNode<Payload> {
    conid: Option<Payload>, // None when dummy
    prev: Option<Rc<RefCell<ScacheListNode<Payload>>>>,
    next: Option<Rc<RefCell<ScacheListNode<Payload>>>>,

    first_call_time: Option<u32>,   //第一次调用帧号
    priority: f64,                  //上次调用后当时优先级，下次调用时即可视为初始优先级再去计算
    call_count: u32,                //总调用次数
    avg_call_interval: Option<f64>, //调用的平均间隔帧数
}

unsafe impl<Payload> Send for ScacheListNode<Payload> {}
unsafe impl<Payload> Sync for ScacheListNode<Payload> {}

impl<Payload> ScacheListNode<Payload> {
    pub fn new(key: Option<Payload>) -> Rc<RefCell<Self>> {
        Rc::new(RefCell::new(ScacheListNode {
            conid: key,
            prev: None,
            next: None,

            first_call_time: None,
            priority: 0.0,
            call_count: 0,
            avg_call_interval: None,
        }))
    }

    //记录一次调用
    //容器被调用时记录其相关信息，包括更新：call_count、first_call_time、avg_call_interval、last_priority
    pub fn record_call(
        &mut self,
        current_frame: u32,
        cold_start_time: usize,
        // cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
        env: &SimEnv,
    ) {
        if self.call_count == 0 {
            self.first_call_time = Some(current_frame);
            self.avg_call_interval = Some(1.0);
        } else {
            let interval = current_frame - self.first_call_time.unwrap();
            self.avg_call_interval = Some((interval / self.call_count) as f64);
        }

        self.call_count += 1;

        // 计算优先级
        self.priority = self.calculate_priority(
            current_frame,
            cold_start_time,
            // cold_start_cpu_use,
            cold_start_mem_use,
            env,
        );
    }

    //优先级计算
    //本方法用于 计算本次被调用的容器的优先级
    pub fn calculate_priority(
        &self,
        current_frame: u32,
        cold_start_time: usize,
        // cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
        env: &SimEnv,
    ) -> f64 {
        // let cs_cpu_use = cold_start_cpu_use as f64;
        let cs_mem_use = cold_start_mem_use as f64;
        let cold_start_time = cold_start_time as f64;

        if self.call_count == 1 {
            //第一次调用，给一个初始优先级
            // cpu_use_rate * mem_use_rate * 1.0
            return current_frame as f64 + cold_start_time / cs_mem_use;
        } else {
            current_frame as f64
                + (cold_start_time) / (cs_mem_use * self.avg_call_interval.unwrap() as f64)
        }
    }
}

//Scache缓存
pub struct SCache<Payload: Eq + Hash + Clone + Debug> {
    capacity: usize,
    cache: HashMap<Payload, Rc<RefCell<ScacheListNode<Payload>>>>,
    head: Rc<RefCell<ScacheListNode<Payload>>>,
    tail: Rc<RefCell<ScacheListNode<Payload>>>,
}

unsafe impl<Payload: Eq + Hash + Clone + Debug> Send for SCache<Payload> {}

impl<Payload: Eq + Hash + Clone + Debug> InstanceCachePolicy<Payload> for SCache<Payload> {
    fn get(
        &mut self,
        key: Payload,
        fncon: &RefMut<'_, FnContainer>,
        env: &SimEnv,
    ) -> Option<Payload> {
        let current_frame = env.current_frame() as u32;
        if let Some(node) = self.cache.get(&key) {
            // let cs_cpu_use = env.func(fncon.fn_id.clone()).cold_start_container_cpu_use;
            // let cs_mem_use = env.func(fncon.fn_id.clone()).cold_start_container_mem_use;
            // let cold_start_time = env.func(fncon.fn_id.clone()).cold_start_time;
            // node.borrow_mut().record_call(
            //     current_frame,
            //     cold_start_time,
            //     // cs_cpu_use,
            //     cs_mem_use,
            //     env,
            // ); //找到了直接更新节点数据
            return Some(key);
        }
        None
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

        //找到了，id为None，put成功
        if self.cache.contains_key(&key) {
            return (None, true);
        }

        //判断空间是否足够，足够直接加，不够的话，
        if self.cache.len() == self.capacity {
            let sorted_priority = self.get_sorted_priority();
            for k in 0..sorted_priority.len() {
                if let Some((to_be_evict_priority, to_be_evict_conid)) = sorted_priority.get(k) {
                    //如果最低温能被移除，即can_be_evict为true
                    if can_be_evict(&to_be_evict_conid.clone()) {
                        //移除温队列第k低温，包括删除节点 + 从缓存中移除
                        self.list_remove_all(&to_be_evict_conid.clone());
                        let new_node = ScacheListNode::new(Some(key.clone()));
                        // 将新节点插入到尾部哨兵节点前面
                        self.add_node(new_node.clone());
                        // 将新容器添加到缓存中
                        self.cache.insert(key.clone(), new_node);
                        self.cache.get_mut(&key).unwrap().borrow_mut().record_call(
                            current_frame,
                            cold_start_time,
                            // cold_start_cpu_use,
                            cold_start_mem_use,
                            env,
                        );
                        return (Some(to_be_evict_conid.clone()), true);
                    }
                }
            }
            (None, false)
        } else {
            let new_node = ScacheListNode::new(Some(key.clone()));
            // 将新节点插入到尾部哨兵节点前面
            self.add_node(new_node.clone());
            // 将新容器添加到缓存中
            self.cache.insert(key.clone(), new_node);
            self.cache.get_mut(&key).unwrap().borrow_mut().record_call(
                current_frame,
                cold_start_time,
                // cold_start_cpu_use,
                cold_start_mem_use,
                env,
            );
            return (None, true);
        }
    }

    fn remove_all(&mut self, key: &Payload) -> bool {
        if let Some(node) = self.cache.remove(key) {
            self.remove_node(node);
            return true;
        }
        false
    }

    fn check_if_prefetch(&mut self, current_frame: u32, env: &SimEnv) -> Vec<Payload> {
        let Vec = Vec::new();
        Vec
    }
}

impl<Payload: Eq + Hash + Clone + Debug> SCache<Payload> {
    /// 创建一个新的缓存队列
    pub fn new(capacity: usize) -> Self {
        let head = ScacheListNode::new(None); // 头部哨兵节点
        let tail = ScacheListNode::new(None); // 尾部哨兵节点

        // 初始化头部和尾部哨兵节点
        head.borrow_mut().next = Some(tail.clone());
        tail.borrow_mut().prev = Some(head.clone());

        let capacity = capacity; // 缓存容量

        SCache {
            capacity,
            cache: HashMap::new(),
            head,
            tail,
        }
    }

    //添加节点到双向链表尾部
    fn add_node(&mut self, node: Rc<RefCell<ScacheListNode<Payload>>>) {
        let prev = self.tail.borrow().prev.clone().unwrap();
        node.borrow_mut().next = Some(self.tail.clone());
        self.tail.borrow_mut().prev = Some(node.clone());
        node.borrow_mut().prev = Some(prev.clone());
        prev.borrow_mut().next = Some(node.clone());
    }

    //移除双向链表中的节点
    fn remove_node(&mut self, node: Rc<RefCell<ScacheListNode<Payload>>>) {
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

    /// 获取当前时刻缓存中所有节点的优先级和ID，并按优先级从小到大排序
    pub fn get_sorted_priority(&self) -> Vec<(f64, Payload)> {
        let mut entries: Vec<(f64, Payload)> = self
            .cache
            .iter()
            .map(|(conid, node)| (node.borrow().priority, conid.clone()))
            .collect();

        // 对优先级进行排序
        entries.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(Ordering::Equal));

        entries
    }
}
