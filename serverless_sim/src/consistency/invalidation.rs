use std::collections::{HashMap, HashSet};
use crate::fn_dag::FnId;

/// 一致性级别
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ConsistencyLevel {
    /// 强一致性 (g_sc): ε_v=0, ε_t=0，副本与源端版本完全一致
    Strong,
    /// 单调读一致性 (g_mr): 同一会话内后续读取版本号不低于前序
    MonotonicRead,
    /// 最终一致性 (g_ec): 允许短期版本偏差，控制最大不一致窗口
    Eventual,
}

impl ConsistencyLevel {
    pub fn name(&self) -> &'static str {
        match self {
            ConsistencyLevel::Strong => "strong",
            ConsistencyLevel::MonotonicRead => "monotonic_read",
            ConsistencyLevel::Eventual => "eventual",
        }
    }
}

/// 失效通知
#[derive(Debug, Clone)]
pub struct InvalidationNotice {
    /// 失效的函数
    pub fn_id: FnId,
    /// 旧版本号
    pub old_version: u64,
    /// 新版本号
    pub new_version: u64,
    /// 失效类型
    pub invalidation_type: InvalidationType,
    /// 传播的目标节点列表（None 表示广播）
    pub target_nodes: Option<Vec<usize>>,
    /// 发出帧号
    pub issued_frame: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InvalidationType {
    /// 直接失效（强一致性）：立即清理所有副本
    Direct,
    /// 延迟失效（单调读）：当前请求结束后失效
    Deferred,
    /// 后台异步失效（最终一致性）：批量处理
    Background,
}

/// 各节点缓存状态的快照（用于定向失效传播）
#[derive(Debug, Clone)]
pub struct NodeCacheState {
    pub node_id: usize,
    /// 该节点上缓存的函数及其版本
    pub cached_fns: HashMap<FnId, u64>,
}

/// 失效传播管理器
///
/// 实现定向失效传播：仅向持有旧版本副本的节点发送失效通知。
/// 支持三种一致性级别的差异化失效策略。
pub struct InvalidationManager {
    /// 待处理的失效通知队列
    pending_invalidations: Vec<InvalidationNotice>,
    /// 已处理的失效通知历史
    processed_history: Vec<InvalidationNotice>,
    /// 最大不一致窗口（帧数），用于最终一致性
    max_inconsistency_window: usize,
    /// 失效传播延迟（帧数）
    propagation_delay: usize,
    /// 当前一致性级别
    consistency_level: ConsistencyLevel,
    /// 会话版本记录（单调读用）：会话 ID -> (FnId, 读取到的版本号)
    session_versions: HashMap<usize, HashMap<FnId, u64>>,
}

impl InvalidationManager {
    pub fn new(
        consistency_level: ConsistencyLevel,
        max_inconsistency_window: usize,
        propagation_delay: usize,
    ) -> Self {
        Self {
            pending_invalidations: Vec::new(),
            processed_history: Vec::new(),
            max_inconsistency_window,
            propagation_delay,
            consistency_level,
            session_versions: HashMap::new(),
        }
    }

    /// 获取当前一致性级别
    pub fn consistency_level(&self) -> ConsistencyLevel {
        self.consistency_level
    }

    /// 设置一致性级别
    pub fn set_consistency_level(&mut self, level: ConsistencyLevel) {
        self.consistency_level = level;
    }

    /// 发布失效通知（Algorithm 4-2）
    ///
    /// 根据一致性级别决定失效方式：
    /// - 强一致性：直接失效，立即传播
    /// - 单调读一致性：延迟到当前请求结束后失效
    /// - 最终一致性：后台异步失效，批量处理
    pub fn issue_invalidation(
        &mut self,
        fn_id: FnId,
        old_version: u64,
        new_version: u64,
        current_frame: usize,
        node_cache_states: &[NodeCacheState],
    ) -> InvalidationNotice {
        let invalidation_type = match self.consistency_level {
            ConsistencyLevel::Strong => InvalidationType::Direct,
            ConsistencyLevel::MonotonicRead => InvalidationType::Deferred,
            ConsistencyLevel::Eventual => InvalidationType::Background,
        };

        // 定向失效：只向持有旧版本的节点发送通知
        let target_nodes: Option<Vec<usize>> = {
            let nodes: Vec<usize> = node_cache_states
                .iter()
                .filter(|ncs| {
                    ncs.cached_fns.get(&fn_id).map_or(false, |v| *v != new_version)
                })
                .map(|ncs| ncs.node_id)
                .collect();
            if nodes.is_empty() {
                None
            } else {
                Some(nodes)
            }
        };

        let notice = InvalidationNotice {
            fn_id,
            old_version,
            new_version,
            invalidation_type,
            target_nodes: target_nodes.clone(),
            issued_frame: current_frame,
        };

        self.pending_invalidations.push(notice.clone());
        log::info!(
            "失效通知发布: fn={} ver={}->{:?} 目标节点={:?}",
            fn_id,
            old_version,
            new_version,
            target_nodes
        );

        notice
    }

    /// 处理帧结束时的失效传播
    ///
    /// 返回当前帧应执行的失效操作列表（已过传播延迟的）
    pub fn process_pending(
        &mut self,
        current_frame: usize,
    ) -> Vec<InvalidationNotice> {
        let mut ready = Vec::new();
        let mut remaining = Vec::new();

        for notice in self.pending_invalidations.drain(..) {
            match notice.invalidation_type {
                InvalidationType::Direct => {
                    // 强一致性：立即执行（但添加传播延迟）
                    if current_frame - notice.issued_frame >= self.propagation_delay {
                        ready.push(notice);
                    } else {
                        remaining.push(notice);
                    }
                }
                InvalidationType::Deferred => {
                    // 单调读：允许一定延迟
                    if current_frame - notice.issued_frame >= self.propagation_delay * 2 {
                        ready.push(notice);
                    } else {
                        remaining.push(notice);
                    }
                }
                InvalidationType::Background => {
                    // 最终一致性：最大不一致窗口内可延迟
                    if current_frame - notice.issued_frame >= self.max_inconsistency_window {
                        ready.push(notice);
                    } else {
                        remaining.push(notice);
                    }
                }
            }
        }

        self.pending_invalidations = remaining;
        self.processed_history.extend(ready.clone());
        ready
    }

    /// 执行失效操作：在目标节点的缓存中移除过期条目
    ///
    /// 返回被失效的函数 ID 列表
    pub fn execute_invalidation(
        &mut self,
        notice: &InvalidationNotice,
        // 回调函数：让调用方执行实际的缓存清理
        invalidate_fn: &mut impl FnMut(FnId, u64),
    ) -> Vec<FnId> {
        invalidate_fn(notice.fn_id, notice.new_version);
        vec![notice.fn_id]
    }

    /// 记录会话读取的版本（单调读一致性用）
    pub fn record_session_read(&mut self, session_id: usize, fn_id: FnId, version: u64) {
        self.session_versions
            .entry(session_id)
            .or_default()
            .insert(fn_id, version);
    }

    /// 检查单调读一致性（后续读取版本 >= 前序读取版本）
    pub fn check_monotonic_read(
        &self,
        session_id: usize,
        fn_id: FnId,
        current_version: u64,
    ) -> bool {
        self.session_versions
            .get(&session_id)
            .and_then(|sessions| sessions.get(&fn_id))
            .map_or(true, |prev_version| current_version >= *prev_version)
    }

    /// 获取待处理的失效通知数量
    pub fn pending_count(&self) -> usize {
        self.pending_invalidations.len()
    }

    /// 获取已处理的失效通知历史
    pub fn processed_count(&self) -> usize {
        self.processed_history.len()
    }

    /// 收集所有节点的缓存状态（由外部注入各节点的信息）
    pub fn collect_node_cache_states(
        node_count: usize,
        node_snapshot_fns: &[Vec<FnId>],
        node_data_fns: &[Vec<(FnId, u64)>],
        version_manager: &impl Fn(FnId) -> u64,
    ) -> Vec<NodeCacheState> {
        let mut states = Vec::new();
        for node_id in 0..node_count {
            let mut cached_fns = HashMap::new();
            // 收集快照缓存
            if node_id < node_snapshot_fns.len() {
                for fn_id in &node_snapshot_fns[node_id] {
                    cached_fns.insert(*fn_id, version_manager(*fn_id));
                }
            }
            // 收集数据缓存
            if node_id < node_data_fns.len() {
                for (fn_id, version) in &node_data_fns[node_id] {
                    cached_fns.insert(*fn_id, *version);
                }
            }
            states.push(NodeCacheState {
                node_id,
                cached_fns,
            });
        }
        states
    }

    /// 统计一致性错误率
    pub fn stats(&self) -> ConsistencyStats {
        let total = self.processed_history.len() + self.pending_invalidations.len();
        let pending = self.pending_invalidations.len();
        ConsistencyStats {
            total_invalidations: total,
            pending_invalidations: pending,
            processed_invalidations: self.processed_history.len(),
        }
    }
}

/// 一致性统计
#[derive(Debug, Clone, Default)]
pub struct ConsistencyStats {
    pub total_invalidations: usize,
    pub pending_invalidations: usize,
    pub processed_invalidations: usize,
}
