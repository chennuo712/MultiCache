use std::cell::RefMut;
use std::fmt::Debug;
use std::hash::Hash;
use std::marker::PhantomData;

use super::InstanceCachePolicy;

use crate::fn_dag::FnContainer;
use crate::sim_env::SimEnv;

pub struct NoEvict<Payload: Eq + Hash + Clone + Debug + Send> {
    _a: PhantomData<Payload>,
}

impl<Payload: Eq + Hash + Clone + Debug + Send> NoEvict<Payload> {
    pub fn new() -> Self {
        NoEvict { _a: PhantomData }
    }
}

impl<Payload: Eq + Hash + Clone + Debug + Send> InstanceCachePolicy<Payload> for NoEvict<Payload> {
    fn get(
        &mut self,
        key: Payload,
        fncon: &RefMut<'_, FnContainer>,
        env: &SimEnv,
    ) -> Option<Payload> {
        Some(key)
    }

    fn put(
        &mut self,
        _key: Payload,
        can_be_evict: Box<dyn FnMut(&Payload) -> bool>,
        env: &SimEnv,
        cold_start_time: usize,
        cold_start_cpu_use: f32,
        cold_start_mem_use: f32,
    ) -> (Option<Payload>, bool) {
        (None, true)
    }

    fn remove_all(&mut self, _key: &Payload) -> bool {
        true
    }

    fn check_if_prefetch(&mut self, current_frame: u32, env: &SimEnv) -> Vec<Payload> {
        let Vec = Vec::new();
        Vec
    }
}
