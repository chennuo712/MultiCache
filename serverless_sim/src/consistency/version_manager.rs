use std::collections::{HashMap, HashSet};
use crate::fn_dag::FnId;

/// 函数的版本状态
#[derive(Debug, Clone)]
pub struct VersionState {
    /// 函数 ID
    pub fn_id: FnId,
    /// 当前全局版本号（64位语义化：V_major << 32 | V_minor）
    pub current_version: u64,
    /// 主版本号（函数镜像/执行逻辑变更时递增）
    pub major: u32,
    /// 次版本号（配置更新/非核心依赖变更时递增）
    pub minor: u32,
    /// 上次更新时间（帧号）
    pub last_updated_frame: usize,
    /// 本函数依赖的其他函数的版本（函数间依赖校验用）
    pub dependencies: HashMap<FnId, u64>,
}

impl VersionState {
    pub fn new(fn_id: FnId) -> Self {
        Self {
            fn_id,
            current_version: 1, // 初始版本号 1
            major: 0,
            minor: 1,
            last_updated_frame: 0,
            dependencies: HashMap::new(),
        }
    }

    /// 从主次版本号合成 64 位版本号
    pub fn compose_version(major: u32, minor: u32) -> u64 {
        (major as u64) << 32 | minor as u64
    }

    /// 提取主版本号
    pub fn major_of(version: u64) -> u32 {
        (version >> 32) as u32
    }

    /// 提取次版本号
    pub fn minor_of(version: u64) -> u32 {
        version as u32
    }

    /// 递增主版本（函数镜像变更）
    pub fn bump_major(&mut self, current_frame: usize) {
        self.major += 1;
        self.minor = 0;
        self.current_version = Self::compose_version(self.major, self.minor);
        self.last_updated_frame = current_frame;
    }

    /// 递增次版本（配置更新）
    pub fn bump_minor(&mut self, current_frame: usize) {
        self.minor += 1;
        self.current_version = Self::compose_version(self.major, self.minor);
        self.last_updated_frame = current_frame;
    }

    /// 检查版本是否匹配
    pub fn is_compatible(&self, other_version: u64) -> bool {
        self.current_version == other_version
    }

    /// 检查主版本是否兼容（主版本必须一致）
    pub fn is_major_compatible(&self, other_version: u64) -> bool {
        Self::major_of(self.current_version) == Self::major_of(other_version)
    }
}

/// 版本管理器
///
/// 为每个函数维护 64 位语义化全局版本号，并在版本变更时记录变更信息。
pub struct VersionManager {
    /// 每个函数的版本状态
    versions: HashMap<FnId, VersionState>,
    /// 版本变更历史
    change_history: Vec<VersionChange>,
    /// 源端更新频率（每多少帧触发一次模拟更新）
    update_interval: usize,
    /// 上次更新的帧号
    last_update_frame: usize,
}

/// 版本变更记录
#[derive(Debug, Clone)]
pub struct VersionChange {
    pub fn_id: FnId,
    pub old_version: u64,
    pub new_version: u64,
    pub change_type: VersionChangeType,
    pub frame: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VersionChangeType {
    /// 主版本变更（逻辑更新）
    Major,
    /// 次版本变更（配置更新）
    Minor,
}

impl VersionManager {
    pub fn new(update_interval: usize) -> Self {
        Self {
            versions: HashMap::new(),
            change_history: Vec::new(),
            update_interval,
            last_update_frame: 0,
        }
    }

    /// 为函数注册版本状态
    pub fn register_fn(&mut self, fn_id: FnId) {
        self.versions
            .entry(fn_id)
            .or_insert_with(|| VersionState::new(fn_id));
    }

    /// 批量注册函数
    pub fn register_fns(&mut self, fn_ids: &[FnId]) {
        for fn_id in fn_ids {
            self.register_fn(*fn_id);
        }
    }

    /// 获取函数的当前版本号
    pub fn get_version(&self, fn_id: FnId) -> u64 {
        self.versions
            .get(&fn_id)
            .map(|v| v.current_version)
            .unwrap_or(0)
    }

    /// 获取版本状态
    pub fn get_version_state(&self, fn_id: FnId) -> Option<&VersionState> {
        self.versions.get(&fn_id)
    }

    /// 获取版本状态（可变）
    pub fn get_version_state_mut(&mut self, fn_id: FnId) -> Option<&mut VersionState> {
        self.versions.get_mut(&fn_id)
    }

    /// 递增主版本（模拟函数镜像更新）
    pub fn bump_major(&mut self, fn_id: FnId, current_frame: usize) {
        if let Some(state) = self.versions.get_mut(&fn_id) {
            let old_version = state.current_version;
            state.bump_major(current_frame);
            self.change_history.push(VersionChange {
                fn_id,
                old_version,
                new_version: state.current_version,
                change_type: VersionChangeType::Major,
                frame: current_frame,
            });
            log::info!(
                "版本变更[Major] fn={} {}->{}",
                fn_id,
                old_version,
                state.current_version
            );
        }
    }

    /// 递增次版本（模拟配置更新）
    pub fn bump_minor(&mut self, fn_id: FnId, current_frame: usize) {
        if let Some(state) = self.versions.get_mut(&fn_id) {
            let old_version = state.current_version;
            state.bump_minor(current_frame);
            self.change_history.push(VersionChange {
                fn_id,
                old_version,
                new_version: state.current_version,
                change_type: VersionChangeType::Minor,
                frame: current_frame,
            });
            log::info!(
                "版本变更[Minor] fn={} {}->{}",
                fn_id,
                old_version,
                state.current_version
            );
        }
    }

    /// 检查版本是否匹配
    pub fn check_version(&self, fn_id: FnId, expected_version: u64) -> bool {
        self.get_version(fn_id) == expected_version
    }

    /// 模拟帧结束时的版本更新（按 update_interval 随机触发版本变更）
    pub fn maybe_update_versions(
        &mut self,
        current_frame: usize,
        all_fn_ids: &[FnId],
        rng: &mut impl FnMut() -> f64,
    ) -> Vec<VersionChange> {
        let mut changes = Vec::new();

        if current_frame - self.last_update_frame < self.update_interval {
            return changes;
        }
        self.last_update_frame = current_frame;

        // 随机选择 10% 的函数触发版本变更
        for fn_id in all_fn_ids {
            if rng() < 0.1 {
                // 10% 概率
                if rng() < 0.3 {
                    // 30% 概率是主版本变更
                    self.bump_major(*fn_id, current_frame);
                } else {
                    self.bump_minor(*fn_id, current_frame);
                }
                if let Some(state) = self.versions.get(fn_id) {
                    changes.push(VersionChange {
                        fn_id: *fn_id,
                        old_version: 0, // 简化
                        new_version: state.current_version,
                        change_type: VersionChangeType::Minor,
                        frame: current_frame,
                    });
                }
            }
        }

        changes
    }

    /// 获取变更历史
    pub fn change_history(&self) -> &[VersionChange] {
        &self.change_history
    }

    /// 清空变更历史
    pub fn clear_history(&mut self) {
        self.change_history.clear();
    }

    /// 获取所有注册的函数
    pub fn all_fn_ids(&self) -> Vec<FnId> {
        self.versions.keys().cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version_composition() {
        let v = VersionState::compose_version(1, 1);
        assert_eq!(VersionState::major_of(v), 1);
        assert_eq!(VersionState::minor_of(v), 1);
    }

    #[test]
    fn test_bump_major() {
        let mut vs = VersionState::new(0);
        let old = vs.current_version;
        vs.bump_major(100);
        assert!(vs.current_version > old);
        assert_eq!(VersionState::major_of(vs.current_version), 1);
    }
}
