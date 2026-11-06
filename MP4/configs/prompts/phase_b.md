SAFETY AND IDIOM PASS. All CRUST tests currently pass. Your job now is to improve code quality WITHOUT
changing behaviour.

Priorities, in order:
1. Remove every `unsafe` block/fn, raw pointer, pointer cast, pointer arithmetic, `transmute` and manual
   allocation. Replace with `Vec<T>`, slices, `Option`, `Box`, indices into a `Vec`, or safe std APIs.
   Add `#![forbid(unsafe_code)]` to the crate root once nothing unsafe remains.
2. Fix the Clippy findings listed below (correctness first, then complexity, perf, style): replace C-style
   index loops with iterators, drop needless clones/returns/borrows, simplify expressions, use
   `Option`/`Result` and pattern matching.
3. Remove avoidable `unwrap()`/`expect()`/`panic!` for recoverable conditions, as long as tests still pass.

Make small, targeted edits and run `run_cargo cmd="test"` after each. If a change breaks tests and you cannot
fix it, undo it. The pipeline will also revert any round that breaks tests or does not improve the metrics.
