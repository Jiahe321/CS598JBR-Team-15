# Idiomatic Rust report

Reviewed: 2026-11-13. This report covers the current translated source and the two saved Clippy logs.

## Command and evidence

Run separately in each `translations/project_N` directory:

```bash
cargo +nightly-2025-05-13 clippy --all-targets --all-features -- \
  -W clippy::correctness \
  -W clippy::style \
  -W clippy::complexity \
  -W clippy::perf
```

Both saved runs end with `Finished` and contain no compilation errors:

- [Project 1 log](translations/project_1/clippy.log): finished in 0.74 seconds.
- [Project 2 log](translations/project_2/clippy.log): finished in 1.39 seconds.

Clippy completion does not establish that functional tests pass; this command checks test targets without running their tests. No tests or additional Clippy runs were executed during this report's preparation.

## Four category results

| Project | Correctness | Style | Complexity | Performance | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Project 1 | 0 | 6 | 4 | 0 | 10 |
| Project 2 | 0 | 5 | 0 | 2 | 7 |

Counting method: count each distinct Clippy diagnostic once, using lint name, source file, line and column. Category membership follows the `implied by -W clippy::<category>` notes in the logs. Repeated diagnostics from building the same file for multiple targets are counted once. Cargo warning summaries, duplicate target declarations, and ordinary rustc warnings such as unused imports, variables and fields are excluded from these four Clippy categories.

The totals **include diagnostics in the provided tests**:

| Project | Implementation diagnostics | Provided test diagnostics |
| --- | --- | --- |
| Project 1 | 5 style | 1 style, 4 complexity |
| Project 2 | 4 style, 2 performance | 1 style |

### Project 1 diagnostic inventory

Locations are relative to `translations/project_1/`.

| Category | Lint | Location |
| --- | --- | --- |
| Style | `should_implement_trait` | `src/bigint.rs:59:5` |
| Style | `uninlined_format_args` | `src/bigint.rs:76:9` |
| Style | `unnecessary_map_or` | `src/bigint.rs:318:9` |
| Style | `unnecessary_map_or` | `src/bigint.rs:322:9` |
| Style | `uninlined_format_args` | `src/bigint.rs:618:13` |
| Style | `uninlined_format_args` | `src/bin/test1.rs:20:5` |
| Complexity | `neg_cmp_op_on_partial_ord` | `src/bin/test2.rs:16:13` |
| Complexity | `neg_cmp_op_on_partial_ord` | `src/bin/test2.rs:17:13` |
| Complexity | `neg_cmp_op_on_partial_ord` | `src/bin/test2.rs:23:13` |
| Complexity | `neg_cmp_op_on_partial_ord` | `src/bin/test2.rs:25:13` |

### Project 2 diagnostic inventory

Locations are relative to `translations/project_2/`.

| Category | Lint | Location |
| --- | --- | --- |
| Style | `module_inception` | `src/card.rs:1:1` |
| Style | `manual_range_contains` | `src/card.rs:161:16` |
| Style | `manual_range_contains` | `src/card.rs:168:16` |
| Performance | `missing_const_for_thread_local` | `src/card.rs:458:43` |
| Style | `module_inception` | `src/razz_simulation.rs:2:1` |
| Performance | `missing_const_for_thread_local` | `src/razz_simulation.rs:61:51` |
| Style | `assertions_on_constants` | `src/bin/test.rs:50:5` |

## Structural inspection

| Expectation | Project 1 | Project 2 |
| --- | --- | --- |
| Ownership and borrowing | `BigInt` owns a `Vec<u8>`; arithmetic borrows operands and helpers accept slices. `is_zero` clones and normalizes the entire number for a read-only check (`src/bigint.rs:79`); `gt` also clones operands before comparison (`:531`). These are opportunities to use borrowed views. | Collections use `Option<Box<CardCollection>>`, owned values and mutable borrowing. No raw pointer manipulation was found in the implementation. Hand iteration allocates a temporary vector and rebuilds the linked collection, adding avoidable work. |
| Types | Uses `Vec`, slices, `Ordering`, and formatting/comparison traits. | Uses suit/rank/action enums, `Option<Card>`, `Box`, and fixed-size arrays for bounded card data. Fixed-size arrays are appropriate for the deck and template-defined hand inputs. |
| Control flow | Uses iterators and pattern matching alongside index-based carry/borrow arithmetic. The latter is reasonable for digit algorithms. | Uses `match`, `if let`, `while let`, and loops. The linked-list representation retains some C-like structure, including an unused `prev` field. |
| Error handling | No `unwrap`, `expect`, or explicit panic was found in `bigint.rs`. However, `from_str` assumes digit input and returns `Self`; invalid-input validation is limited. | Constructors and parsers use `Option`, and simulation matches failure cases. The three `unwrap` calls in `card.rs` are guarded by preceding checks or short-circuit conditions; pattern matching could make those guarantees clearer. |
| Organization | Arithmetic helpers and traits provide reasonable decomposition. Public `from_str` triggers a trait-naming lint. | Nested module names trigger Clippy warnings and follow the template's public module layout. `get_razz_rank` retains unused planning variables/comments and uses a thread-local accumulator plus a vector clone; this could be simplified while preserving the interface. |

### Outstanding implementation limitations

Project 2 still contains no-op helpers: `detach_from_collection` (`src/card.rs:314`) and `remove_from_hand_under_iter` (`:444`). Its deck constructor also calls `srand48(3)` for every new deck (`:515`), which resets the random stream rather than preserving state across deck creation. These require functional/specification review; a zero Clippy correctness count does not certify their behavior.

No translated Rust, public interfaces, or provided tests were changed while preparing this report. Test warnings remain included in the totals; the tests should not be edited merely to lower the warning count.

## Assessment

The Clippy runs and the four-category reporting are complete, and this report records the requested structural inspection. Both unique-warning totals fall in the rubric's 0–10 numerical band. The zero-warning target has not been reached in every category, and the structural findings above mean that full idiomaticity credit cannot be guaranteed. Functional correctness is assessed separately.

These results apply to this source snapshot. Regenerate the logs and update this report after changing the translated source.

## Snapshot fingerprints

SHA-256:

```text
project_1/src/bigint.rs
be54739794498d7896252ad7c115638c0cc51eed41965a8787067b958ea5a31d
project_2/src/card.rs
4eb0c5988a2562bcac53e93fd4bdf06c23ba6b7999fe515588247fb9439e1267
project_2/src/razz_simulation.rs
4877b0f1bd77ae202a2bf944ea1cefd86a5bfbdee60f8de4809206e3a949fd91
project_1/clippy.log
9cb17c8e7c335e3a65a9e4f9b0d50462dada2e16d0ab3bdf128881b1b344daea
project_2/clippy.log
e202f61841fffb1065f05c64d203f993aab1e134c2c4a1d28562b08164bbed97
```
