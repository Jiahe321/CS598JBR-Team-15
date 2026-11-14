Analysis-Version: 1
Failure: src/bin/test.rs:46:5
Observed: SpadeAce
Expected: Heart9
C-Evidence: c/card_test.c:304-320, c/card.c:754-764, c/card.c:723-743
Rust-Evidence: src/bin/test.rs:42-48, src/bin/test.rs:204-217, src/card.rs:293-320, src/card.rs:354-364

Trace:
- Setup: `d = create_shuffled_deck()` (test.rs:204), then `h = create_hand(3, sort_card_by_rank)` (test.rs:206). Three cards dealt and inserted (test.rs:208-212); max-rank assertions pass (R9,R9,R10), so the first three dealt cards are consistent with C's seeded deck.
- C reference (card_test.c:304-320): after 3 inserts, `remove_from_hand(h, SPADE_ACE)` is called, then `iterate_hand(h, test_sort_card_by_rank_4)` expects `{HEART_9, HEART_10}` and count 2.
- Rust test (test.rs:214-217): a 4th `insert_into_hand` is performed (max=3, so `insert_into_hand` returns early at card.rs:355-357 — no-op), then `iterate_hand(test_sort_card_by_rank_4)` is called with NO `remove_from_hand(SPADE_ACE)`.
- So the hand still contains 3 cards including SpadeAce. `iterate_hand` visits position 0 = SpadeAce, but `test_sort_card_by_rank_4` expects `test_data[0] = Heart9` -> assertion fails with left=SpadeAce, right=Heart9.

Hypothesis:
This is a SPEC_GAP in the protected test, not a translation bug. The Rust `test_card_operations` omits the `remove_from_hand(SPADE_ACE)` step present in the C reference (card_test.c:317) before iterating with `test_sort_card_by_rank_4`. The Rust hand correctly retains SpadeAce (insert_into_hand is a no-op at max). The protected test's expected sequence `{Heart9, Heart10}` only holds after removing SpadeAce. Writer cannot fix this without editing the protected test; the discrepancy is in the test setup, not `insert_into_hand`/`iterate_hand`/`remove_from_hand`.

Unresolved: Whether the protected test intends to exercise `remove_from_hand` here (as C does) — the missing call is the sole difference. No implementation change is warranted based on this assertion.
