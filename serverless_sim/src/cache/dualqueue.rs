use std::cell::RefMut;
use std::{cell::RefCell, cmp::Eq, collections::HashMap, fmt::Debug, hash::Hash, rc::Rc};

use crate::cache::InstanceCachePolicy;
use crate::cache::ListNode;
use crate::fn_dag::FnContainer;
use crate::sim_env::SimEnv;

pub struct DualQueueCache<Payload: Eq + Hash + Clone + Debug> {
    cache: HashMap<Payload, Rc<RefCell<ListNode<Payload>>>>,
    main_capacity: usize,
    secondary_capacity: usize,
    main_queue: Deque<Payload>,
    secondary_queue: Deque<Payload>,
}

impl<Payload: Eq + Hash + Clone + Debug> DualQueueCache<Payload> {
    pub fn new(main_capacity: usize, secondary_capacity: usize) -> Self {
        DualQueueCache {
            cache: HashMap::new(),
            main_capacity,
            secondary_capacity,
            main_queue: Deque::new(),
            secondary_queue: Deque::new(),
        }
    }
}

unsafe impl<Payload: Eq + Hash + Clone + Debug> Send for DualQueueCache<Payload> {}

impl<Payload: Eq + Hash + Clone + Debug> InstanceCachePolicy<Payload> for DualQueueCache<Payload> {
    fn get(
        &mut self,
        key: Payload,
        _fncon: &RefMut<'_, FnContainer>,
        _env: &SimEnv,
    ) -> Option<Payload> {
        if !self.cache.contains_key(&key) {
            return None;
        }

        // Check in main queue
        // 主队列命中，提到头
        if let Some(main_node) = self.main_queue.traverse(&key) {
            self.main_queue.remove_node_in_queue(main_node.clone());
            self.main_queue.add_to_head(main_node);
            return Some(key);
        }

        // If not found in main queue, check in secondary queue
        // 副队列命中，提到主队列尾部
        if let Some(secondary_node) = self.secondary_queue.traverse(&key) {
            // Move the secondary node to the end of the main queue
            //从副队列移除
            self.secondary_queue
                .remove_node_in_queue(secondary_node.clone());

            //主队列满了
            if self.main_queue.is_full(self.main_capacity) {
                if let Some(main_lru_node) = self.main_queue.remove_from_tail() {
                    //移除主队列尾部,并放到副队列头部
                    self.secondary_queue.add_to_head(main_lru_node);
                }
            }

            self.main_queue.add_to_head(secondary_node);

            // Move the least recently used from main queue to secondary queue

            return Some(key);
        }
        None
    }

    // return Some(payload) if one is evicted
    fn put(
        &mut self,
        key: Payload,
        mut can_be_evict: Box<dyn FnMut(&Payload) -> bool>,
        _env: &SimEnv,
        _cold_start_time: usize,
        _cold_start_cpu_use: f32,
        _cold_start_mem_use: f32,
    ) -> (Option<Payload>, bool) {
        if self.cache.contains_key(&key) {
            // Key already exists, no need to insert again
            if let Some(main_node) = self.main_queue.traverse(&key) {
                self.main_queue.remove_node_in_queue(main_node.clone());
                self.main_queue.add_to_head(main_node);
                return (None, true);
            }

            // If not found in main queue, check in secondary queue
            // 副队列命中，提到主队列头部
            if let Some(secondary_node) = self.secondary_queue.traverse(&key) {
                // Move the secondary node to the end of the main queue
                //从副队列移除
                self.secondary_queue
                    .remove_node_in_queue(secondary_node.clone());

                //主队列满了
                if self.main_queue.is_full(self.main_capacity) {
                    if let Some(main_lru_node) = self.main_queue.remove_from_tail() {
                        //移除主队列尾部,并放到副队列头部
                        self.secondary_queue.add_to_head(main_lru_node);
                    }
                }

                self.main_queue.add_to_head(secondary_node);
                return (None, true);
            }
        }

        let new_node = ListNode::new(Some(key.clone()));

        if !self.main_queue.is_full(self.main_capacity) {
            //主没满，放头
            // Insert into main queue
            self.main_queue.add_to_head(new_node.clone());
            self.cache.insert(key.clone(), new_node.clone());
            (None, true)
        } else if !self.secondary_queue.is_full(self.secondary_capacity) {
            //副没满，移动主尾到副头，key添加到主队列头
            if let Some(lru_main_node) = self.main_queue.remove_from_tail() {
                self.secondary_queue.add_to_head(lru_main_node.clone());

                self.main_queue.add_to_head(new_node.clone());

                self.cache.insert(key.clone(), new_node.clone());
            }
            (None, true)
        } else {
            let mut res = (None, true);
            // 删副队列
            let mut secondary_back_node = self.secondary_queue.tail.borrow().prev.clone().unwrap();
            while secondary_back_node.borrow().key.is_some() {
                if can_be_evict(secondary_back_node.borrow().key.as_ref().unwrap()) {
                    // 取出并返回被淘汰节点的键（Payload），以便外部使用
                    let key_to_remove = secondary_back_node.borrow().key.clone().unwrap();
                    self.cache.remove(&key_to_remove);
                    self.secondary_queue
                        .remove_node_in_queue(secondary_back_node.clone());
                    res = (Some(key_to_remove), true);
                    break;
                } else {
                    let next_back_node = secondary_back_node.borrow().prev.clone().unwrap();
                    secondary_back_node = next_back_node;
                }
            }

            if res.0.is_some() {
                //说明副队列移除掉了一个
                //移除主尾到副头，添加新节点到主队列头
                if let Some(lru_main_node) = self.main_queue.remove_from_tail() {
                    self.secondary_queue.add_to_head(lru_main_node.clone());
                    self.main_queue.add_to_head(new_node.clone());
                    self.cache.insert(key.clone(), new_node.clone());
                    return res;
                }
            } else {
                //说明副队列不能移除
                //删主队列
                let mut main_back_node = self.main_queue.tail.borrow().prev.clone().unwrap();
                while main_back_node.borrow().key.is_some() {
                    if can_be_evict(main_back_node.borrow().key.as_ref().unwrap()) {
                        // 取出并返回被淘汰节点的键（Payload），以便外部使用
                        let key_to_remove = main_back_node.borrow().key.clone().unwrap();
                        self.cache.remove(&key_to_remove);
                        self.main_queue.remove_node_in_queue(main_back_node.clone());
                        res = (Some(key_to_remove), true);
                        break;
                    } else {
                        let next_back_node = main_back_node.borrow().prev.clone().unwrap();
                        main_back_node = next_back_node;
                    }
                }
            }

            if res.0.is_none() {
                return (None, false);
            }

            self.main_queue.add_to_head(new_node.clone());
            self.cache.insert(key.clone(), new_node.clone());
            res
        }
    }

    /// 从缓存中删除一个节点
    fn remove_all(&mut self, key: &Payload) -> bool {
        if let Some(node) = self.main_queue.traverse(key) {
            self.main_queue.remove_node_in_queue(node.clone());
            self.cache.remove(key);
            return true;
        } else if let Some(node) = self.secondary_queue.traverse(key) {
            self.secondary_queue.remove_node_in_queue(node.clone());
            self.cache.remove(key);
            return true;
        }
        false
    }

    fn check_if_prefetch(&mut self, _current_frame: u32, _env: &SimEnv) -> Vec<Payload> {
        let v = Vec::new();
        v
    }
}

struct Deque<Payload: Eq + Hash + Clone + Debug> {
    head: Rc<RefCell<ListNode<Payload>>>,
    tail: Rc<RefCell<ListNode<Payload>>>,
    size: usize,
}

impl<Payload: Eq + Hash + Clone + Debug> Deque<Payload> {
    fn new() -> Self {
        let head = ListNode::new(None);
        let tail = ListNode::new(None);
        head.borrow_mut().next = Some(tail.clone());
        tail.borrow_mut().prev = Some(head.clone());

        Deque {
            head,
            tail,
            size: 0,
        }
    }

    fn add_to_head(&mut self, node: Rc<RefCell<ListNode<Payload>>>) {
        let mut head_borrowed = self.head.borrow_mut();
        let first_node = head_borrowed.next.clone().unwrap();

        first_node.borrow_mut().prev = Some(node.clone());
        node.borrow_mut().next = Some(first_node);
        node.borrow_mut().prev = Some(self.head.clone());
        head_borrowed.next = Some(node);

        self.size += 1;
    }

    fn remove_from_tail(&mut self) -> Option<Rc<RefCell<ListNode<Payload>>>> {
        let lru_node = self.tail.borrow().prev.clone().unwrap();
        self.remove_node_in_queue(lru_node.clone());

        Some(lru_node)
    }

    fn remove_node_in_queue(&mut self, node: Rc<RefCell<ListNode<Payload>>>) {
        let prev_node = node.borrow().prev.clone().unwrap();
        let next_node = node.borrow().next.clone().unwrap();

        prev_node.borrow_mut().next = Some(next_node.clone());
        next_node.borrow_mut().prev = Some(prev_node);
        self.size -= 1;
    }
    fn is_full(&self, capacity: usize) -> bool {
        self.size >= capacity
    }

    fn traverse(&self, key: &Payload) -> Option<Rc<RefCell<ListNode<Payload>>>> {
        let mut current = self.head.borrow().next.clone();
        while let Some(node) = current {
            if node.borrow().key.as_ref() == Some(key) {
                return Some(node);
            }
            current = node.borrow().next.clone();
        }
        None
    }
}
