# Rust compiler errors → idiomatic fixes

| Error | Fix |
|---|---|
| E0382 use of moved value | Borrow (`&x`, `for x in &v`), clone deliberately, or restructure ownership |
| E0499 / E0502 conflicting borrows | Shorten the borrow, split borrows (disjoint fields, `split_at_mut`, `get_disjoint_mut`), indices, two-phase update |
| E0505 move while borrowed | End the borrow first; clone only the part needed |
| E0507 move out of borrowed content | `clone()`, `std::mem::take`/`replace`, `Option::take`, match on `&self.x`, `as_ref()`/`as_deref()` |
| E0597 / E0716 does not live long enough / temporary dropped | Bind the temporary with `let`; return owned data; widen the owner's scope |
| E0106 missing lifetime | Return owned, or tie output to one input: `fn f<'a>(s: &'a str) -> &'a str` |
| E0373 closure may outlive borrowed value | `move` + `Arc`/clone, or `std::thread::scope` |
| E0277 not `Send`/`Sync`, "future cannot be sent" | `Arc`/`Mutex` instead of `Rc`/`RefCell`; drop `!Send` values before `.await`; current-thread runtime/`spawn_local` |
| E0308 mismatched types | `as_deref()`, `as_ref()`, `&*s`, `.into()`; check `&String` vs `&str`, `Option<&T>` vs `&Option<T>` |
| E0599 method not found | Import the trait (`std::io::Write`, `futures::StreamExt`), add the trait bound, enable the crate feature |
| E0038 trait not dyn compatible | `where Self: Sized` on generic methods, enum dispatch, or generics instead of `dyn` |
| Edition 2024 migration | `cargo fix --edition`; `gen` is reserved (`r#gen`); RPIT captures all in-scope lifetimes — narrow with `+ use<'a, T>` |
