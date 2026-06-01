// pub mod arc;
pub mod contemp;
pub mod data_cache;
pub mod dualqueue;
pub mod faascache;
pub mod fifo;
pub mod level_cache;
pub mod lru;
pub mod multi_level;
pub mod no_evict;
pub mod scache;
pub mod snapshot_cache;
pub mod ttl;
pub mod types;
pub mod value_scorer;

pub use multi_level::{CapacityConfig, MultiLevelCache, MultiLevelCacheStats};
pub use types::{CacheLevel, CacheObject, DataEntry, LoadDetail, LoadResult, SnapshotEntry};
pub use value_scorer::{ValueScorer, ValueScorerConfig};
// pub mod no_attenuation;
// pub mod no_callcount;
// pub mod no_cpu;
// pub mod no_cst;
// pub mod no_freq;
// pub mod no_mem;

// pub mod ttl_new;

// pub mod contemp_01;
// pub mod contemp_1;
// pub mod contemp_2;
// pub mod contemp_3;
// pub mod contemp_4;
// pub mod contemp_5;
// pub mod contemp_6;
// pub mod contemp_7;
// pub mod contemp_8;
// pub mod contemp_9;
// pub mod contemp_99;

use std::cell::RefMut;
use std::{cell::RefCell, cmp::Eq, fmt::Debug, hash::Hash, rc::Rc};

use crate::fn_dag::FnContainer;
use crate::sim_env::SimEnv;

// 双向链表节点
pub struct ListNode<Payload> {
    key: Option<Payload>, // None when dummy
    // value: Option<FnContainer>,
    prev: Option<Rc<RefCell<ListNode<Payload>>>>,
    next: Option<Rc<RefCell<ListNode<Payload>>>>,
}

unsafe impl<Payload> Send for ListNode<Payload> {}
unsafe impl<Payload> Sync for ListNode<Payload> {}

impl<Payload> ListNode<Payload> {
    fn new(key: Option<Payload>) -> Rc<RefCell<Self>> {
        Rc::new(RefCell::new(ListNode {
            key,
            prev: None,
            next: None,
        }))
    }
}
pub trait InstanceCachePolicy<Payload: Eq + Hash + Clone + Debug>: Send {
    fn get(
        &mut self,
        key: Payload,
        fncon: &RefMut<'_, FnContainer>,
        env: &SimEnv,
    ) -> Option<Payload>;

    /// can_be_evict: check if the payload is pinned
    /// first return: return Some(payload) if one is evcited
    /// second return: return true if put success
    fn put(
        &mut self,
        key: Payload,
        can_be_evict: Box<dyn FnMut(&Payload) -> bool>,
        env: &SimEnv,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
    ) -> (Option<Payload>, bool);
    fn remove_all(&mut self, key: &Payload) -> bool;

    // 新增预取检查接口
    fn check_if_prefetch(&mut self, current_frame: u32, env: &SimEnv) -> Vec<Payload>;
}
