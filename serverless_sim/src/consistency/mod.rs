pub mod version_manager;
pub mod invalidation;


use crate::fn_dag::FnId;
use version_manager::VersionManager;
use invalidation::{
    ConsistencyLevel, InvalidationManager, InvalidationNotice, NodeCacheState,
};

/// 一致性配置
#[derive(Debug, Clone)]
pub struct ConsistencyConfig {
    /// 一致性级别
    pub level: ConsistencyLevel,
    /// 源端更新间隔（帧数）
    pub update_interval: usize,
    /// 最大不一致窗口（帧数，最终一致性用）
    pub max_inconsistency_window: usize,
    /// 失效传播延迟（帧数）
    pub propagation_delay: usize,
    /// 是否启用一致性
    pub enabled: bool,
}

impl Default for ConsistencyConfig {
    fn default() -> Self {
        Self {
            level: ConsistencyLevel::Eventual,
            update_interval: 10,
            max_inconsistency_window: 5,
            propagation_delay: 1,
            enabled: true,
        }
    }
}

/// 一致性管理器
///
/// 整合版本管理和失效传播，在帧结束时统一执行一致性检查和处理。
pub struct ConsistencyManager {
    /// 版本管理器
    pub version_manager: VersionManager,
    /// 失效传播管理器
    pub invalidation_manager: InvalidationManager,
    /// 配置
    config: ConsistencyConfig,
    /// 一致性错误计数
    consistency_error_count: usize,
    /// 最大不一致窗口观测
    max_observed_inconsistency: usize,
}

impl ConsistencyManager {
    pub fn new(config: ConsistencyConfig) -> Self {
        Self {
            version_manager: VersionManager::new(config.update_interval),
            invalidation_manager: InvalidationManager::new(
                config.level,
                config.max_inconsistency_window,
                config.propagation_delay,
            ),
            consistency_error_count: 0,
            max_observed_inconsistency: 0,
            config,
        }
    }

    /// 获取配置
    pub fn config(&self) -> &ConsistencyConfig {
        &self.config
    }

    /// 获取配置（可变）
    pub fn config_mut(&mut self) -> &mut ConsistencyConfig {
        &mut self.config
    }

    /// 注册函数版本
    pub fn register_fn(&mut self, fn_id: FnId) {
        self.version_manager.register_fn(fn_id);
    }

    /// 批量注册
    pub fn register_fns(&mut self, fn_ids: &[FnId]) {
        self.version_manager.register_fns(fn_ids);
    }

    /// 帧结束时的一致性处理入口
    ///
    /// 执行流程：
    /// 1. 检查是否需要触发版本更新（按 update_interval）
    /// 2. 如果版本发生变更，发布失效通知
    /// 3. 处理待处理的失效通知
    /// 4. 返回需要清理的缓存项列表
    pub fn on_frame_end(
        &mut self,
        current_frame: usize,
        all_fn_ids: &[FnId],
        node_cache_states: &[NodeCacheState],
        mut rng: impl FnMut() -> f64,
    ) -> Vec<InvalidationNotice> {
        if !self.config.enabled {
            return Vec::new();
        }

        // Step 1: 检查版本更新
        let changes = self.version_manager.maybe_update_versions(
            current_frame,
            all_fn_ids,
            &mut rng,
        );

        // Step 2: 版本变更时发布失效通知
        for change in &changes {
            // 级联失效：确定需要失效的缓存层级
            let cache_levels = self.version_manager.cascade_invalidate(
                change.fn_id,
                change.change_type,
            );
            if cache_levels.is_empty() {
                continue;
            }
            self.invalidation_manager.issue_invalidation(
                change.fn_id,
                change.old_version,
                change.new_version,
                cache_levels,
                current_frame,
                node_cache_states,
            );
        }

        // Step 3: 处理待处理的失效通知
        self.invalidation_manager.process_pending(current_frame)
    }

    /// 执行失效操作（由外部调用，清理对应节点的缓存）
    pub fn execute_invalidation(
        &mut self,
        notice: &InvalidationNotice,
        invalidate_fn: &mut impl FnMut(FnId, u64),
    ) {
        self.invalidation_manager.execute_invalidation(notice, invalidate_fn);
    }

    /// 记录一致性错误
    pub fn record_consistency_error(&mut self) {
        self.consistency_error_count += 1;
    }

    /// 更新最大不一致窗口
    pub fn update_max_inconsistency(&mut self, window: usize) {
        if window > self.max_observed_inconsistency {
            self.max_observed_inconsistency = window;
        }
    }

    /// 获取统计信息
    pub fn stats(&self) -> ConsistencyManagerStats {
        let inval_stats = self.invalidation_manager.stats();
        ConsistencyManagerStats {
            consistency_error_count: self.consistency_error_count,
            max_observed_inconsistency: self.max_observed_inconsistency,
            total_invalidations: inval_stats.total_invalidations,
            pending_invalidations: inval_stats.pending_invalidations,
            processed_invalidations: inval_stats.processed_invalidations,
        }
    }

    /// 获取当前一致性级别名称
    pub fn level_name(&self) -> &'static str {
        self.config.level.name()
    }
}

/// 一致性管理器统计
#[derive(Debug, Clone, Default)]
pub struct ConsistencyManagerStats {
    pub consistency_error_count: usize,
    pub max_observed_inconsistency: usize,
    pub total_invalidations: usize,
    pub pending_invalidations: usize,
    pub processed_invalidations: usize,
}
