use super::InstanceCachePolicy;
use crate::{fn_dag::FnContainer, sim_env::SimEnv};
use rand::Rng;
use std::cell::RefMut;
use std::{cell::RefCell, cmp::Eq, collections::HashMap, fmt::Debug, hash::Hash, rc::Rc};

pub struct TTLListNode<Payload> {
    key: Option<Payload>,
    prev: Option<Rc<RefCell<TTLListNode<Payload>>>>,
    next: Option<Rc<RefCell<TTLListNode<Payload>>>>,
    last_call_frame: Option<u32>,
    ttl_frame: Option<u32>, //该被驱逐的帧号
}

impl<Payload> TTLListNode<Payload> {
    pub fn new(key: Option<Payload>) -> Rc<RefCell<Self>> {
        Rc::new(RefCell::new(TTLListNode {
            key: key,
            prev: None,
            next: None,
            last_call_frame: None,
            ttl_frame: None,
        }))
    }

    //纯更新，该方法通常用在 判断出容器未过期或不能被移除后 再调用，故无需在这个方法里再判断是否过期
    fn update(&mut self, current_frame: u32, ttl_frames: u32) {
        self.last_call_frame = Some(current_frame);
        self.ttl_frame = Some(current_frame + ttl_frames);
    }

    //超时true，没超时false
    fn is_expired(&self, current_frame: u32) -> bool {
        if let Some(ttl) = self.ttl_frame {
            if ttl <= current_frame {
                return true;
            }
            return false;
        }
        false
    }
}

pub struct TTLCache<Payload: Eq + Hash + Clone + Debug> {
    cache: HashMap<Payload, Rc<RefCell<TTLListNode<Payload>>>>,
    head: Rc<RefCell<TTLListNode<Payload>>>,
    tail: Rc<RefCell<TTLListNode<Payload>>>,
    capacity: usize,
    ttl_frames: u32, // ttl时间
}

impl<Payload: Eq + Hash + Clone + Debug> TTLCache<Payload> {
    pub fn new(capacity: usize) -> Self {
        let head = TTLListNode::new(None);
        let tail = TTLListNode::new(None);
        head.borrow_mut().next = Some(tail.clone());
        tail.borrow_mut().prev = Some(head.clone());

        Self {
            cache: HashMap::new(),
            head,
            tail,
            capacity,
            ttl_frames: rand::thread_rng().gen_range(5..10),
        }
    }

    fn move_to_head(&mut self, node: Rc<RefCell<TTLListNode<Payload>>>) {
        let next = self.head.borrow().next.clone();
        node.borrow_mut().prev = Some(self.head.clone());
        node.borrow_mut().next = next.clone();
        self.head.borrow_mut().next = Some(node.clone());
        next.unwrap().borrow_mut().prev = Some(node);
    }

    fn remove_node(&mut self, node: Rc<RefCell<TTLListNode<Payload>>>) {
        let prev = node.borrow().prev.clone().unwrap();
        let next = node.borrow().next.clone().unwrap();
        prev.borrow_mut().next = Some(next.clone());
        next.borrow_mut().prev = Some(prev);
    }

    //遍历cache找出当前帧数下已超时的容器，将这些key收集在Vec中一并返回
    fn to_clean_expired_keys(&mut self, current_frame: u32) -> Vec<Payload> {
        let mut to_remove = vec![];
        for (key, node) in &self.cache {
            if node.borrow().is_expired(current_frame) {
                to_remove.push(key.clone());
            }
        }
        to_remove
    }
}

unsafe impl<Payload: Eq + Hash + Clone + Debug> Send for TTLCache<Payload> {}

impl<Payload: Eq + Hash + Clone + Debug> InstanceCachePolicy<Payload> for TTLCache<Payload> {
    fn get(
        &mut self,
        key: Payload,
        fncon: &RefMut<'_, FnContainer>,
        env: &SimEnv,
    ) -> Option<Payload> {
        let current_frame = env.current_frame() as u32;

        if let Some(node) = self.cache.get(&key) {
            // node.borrow_mut().update(current_frame, self.ttl_frames);
            return Some(key);
            //如果按ttl逻辑，get时删除过期项，则需要判断can_be_evict
            //实际上这里不用删除，系统中调用get()是在try_load_container()之后，即put()之后，用于确保put()成功
            //所以这里get到就直接更新了，不管是否过期
            // self.remove_node(node.clone());
            // self.cache.remove(&key);
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

        if let Some(node) = self.cache.get(&key) {
            if !node.borrow().is_expired(current_frame) {
                //没过期
                node.borrow_mut().update(current_frame, self.ttl_frames);
                return (None, true);
            }

            //过期了
            //能删除就直接删了
            let key_to_remove = node.borrow().key.clone().unwrap();
            if can_be_evict(node.borrow().key.as_ref().unwrap()) {
                // res = (Some(key_to_remove), false);
                self.remove_node(node.clone());

                self.cache.remove(&key_to_remove);
                //返回删除的key，也就是要put的key，并且put失败返回false
                return (Some(key_to_remove), false);
            }

            //过期了，但不能删除，则更新他的ttl时间
            node.borrow_mut().update(current_frame, self.ttl_frames);
            return (None, true); //(None,true)
        }

        if self.cache.len() == self.capacity {
            //满了就只删一个，并返回删掉的key
            let expired_keys = self.to_clean_expired_keys(current_frame);
            for key_to_remove in expired_keys {
                if can_be_evict(&key_to_remove) {
                    if let Some(node) = self.cache.remove(&key_to_remove) {
                        self.remove_node(node);
                        let new_node = TTLListNode::new(Some(key.clone()));
                        self.cache.insert(key.clone(), new_node.clone());
                        self.move_to_head(new_node.clone());
                        new_node.borrow_mut().update(current_frame, self.ttl_frames);
                        return (Some(key_to_remove), true);
                    }
                }
            }
        } else {
            let new_node = TTLListNode::new(Some(key.clone()));
            self.cache.insert(key.clone(), new_node.clone());
            self.move_to_head(new_node.clone());
            new_node.borrow_mut().update(current_frame, self.ttl_frames);

            return (None, true);
        }

        (None, false)
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
