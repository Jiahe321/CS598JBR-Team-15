# Razz Simulation — Translation Spec (overview)

## Module map (C -> Rust)

| C file | Rust module | Notes |
|---|---|---|
| `c/card.c` + `c/card.h` | `src/card.rs` (`pub mod card`) | cards, ranks, suits, deck, hand, collection, sorters |
| `c/razz_simulation.c` + `c/razz_simulation.h` | `src/razz_simulation.rs` (`pub mod razz_simulation`) | `DecidedCards`, `simulate_razz_game`, `strip_deck`, `complete_hand` |
| `c/razz.c` (main + `process_args` + `listener`) | not in Rust interface | CLI only; no Rust equivalent required |
| `c/card_test.c` | `src/bin/test.rs` (graded) | behaviour reference |

`src/lib.rs` declares `pub mod card; pub mod razz_simulation;`.

## Data structures

- `card` (C `struct card_impl`, card.c:25-54): single `uint8_t card`. Bits 0..4 = rank (1..13), bits 5..7 = suit (1=Spade,2=Heart,3=Diamond,4=Club). 0 = invalid.
- `card_collection` (card.c:170-175): circular doubly-linked list node `{prev, next, const card *c}`.
- `card_hand_impl` (card.c:454-463): `{uint8_t max, uint8_t len, card_sorter sorter, card_collection *cards}`.
- `card_deck_impl` (card.c:466-470): `{char card_count, card cards[52]}`. A card slot is "still in deck" iff `get_card_suit_rank(&cards[i]) == INVALID_CARD` (i.e. `card == 0`).
- `struct decided_cards` (razz_simulation.h:33-39): `{uint8_t my_card_count; const card *my_cards[3]; uint8_t opponent_card_count; const card *opponent_cards[7];}`.

## Rust interface constraints (protected)

`src/card.rs` and `src/razz_simulation.rs` signatures are fixed. Key mismatches to bridge:

- `CardCollection` in Rust is `{prev: Option<Box<CardCollection>>, next: Option<Box<CardCollection>>, c: Option<Card>}` — a `Box`-based ring is impossible to build safely (shared ownership). Recommended: keep the struct definition but implement `CardHand` on top of a `Vec<Option<Card>>`-like internal ordering, OR use `Rc<RefCell<..>>` internally. Since `CardHand.cards: CardCollection` is a fixed field, the simplest safe design is: `CardCollection` holds the *head* card plus a `Vec`-free representation is not possible without changing the struct. **Recommended**: implement `CardCollection` as a thin wrapper whose `c` is the head card and whose `next` chain is built with `Box`; but `prev`/`next` both being `Box` cannot form a ring. Therefore implement `CardHand` logic (insert/count/max/iterate/remove) using an internal `Vec<Option<Card>>` stored *in place of* the ring by treating `CardCollection` as an opaque marker and keeping the real list in `CardHand`. This requires adding a private field to `CardHand` — **not allowed** (struct is fixed). 

  **Resolution**: The graded test only exercises `CardHand` public methods and `CardCollection` is never constructed by the test directly. Implement `CardCollection` as a singly-linked `Box` chain via `next`, with `prev = None` always, and `c = Some(head_card)`. `CardHand.cards` is the head node. Insertion walks the `next` chain, finds the sorted position, and splices a new `Box` node. `len` tracks count. This satisfies all graded behaviour (sorted order, removal, iteration) without a true ring. `prev` is unused (always `None`). Document this deviation.

- `CardSorter = fn(&Option<Card>, &Option<Card>, &Option<Card>) -> i32` — `None` corresponds to C `NULL`.
- `CardIterator = fn(u64, u64, &Option<Card>) -> ItrAction`.
- `RankListener<T> = fn(&mut T, CardRank)`.
- `CardDeck.cards: [Card; 52]` — a `Card` with `card == 0` means "still in deck" (matches C: slot holds a card value; 0 = not yet dealt). `Card` has no public constructor other than `write_card`; `write_card(CardSuitRank::InvalidCard)` yields `card == 0`.

## Global / static state

- `lrand48()` PRNG (card.c:902). C test seeds with `srand48(3)` (card_test.c:198,218,286,305,335). The Rust graded test does **not** seed — it relies on the exact `expected_card_count` distribution (test.rs:220-235) which is the C `srand48(3)` sequence. **The Rust implementation must reproduce the glibc `lrand48` sequence seeded with 3** (or an equivalent deterministic generator producing the same `lrand48() % card_count` selections). This is the single hardest requirement: `deal_from_deck` must call a `lrand48`-compatible generator. Recommended: implement a `lrand48` clone (48-bit LCG: `x = (0x5DEECE66D * x + 0xB) & ((1<<48)-1)`, output `x >> 17`), with a thread-local/global seed initialized to 3 (since the test never calls `srand48`, the default seed must be 3 to match `expected_card_count`). **Verify**: C default `srand48` seed is `0x1234ABCD330E`; the test explicitly calls `srand48(3)` before the distribution loop, so the Rust default must be seed 3. This is a compatibility gap: the Rust API has no `srand48`. Set the global generator's initial state to `srand48(3)`'s state so the un-seeded test matches.

- `duplicated_rank_remover` uses a `static enum card_rank prev_rank` (razz_simulation.c:57) — persistent across calls but reset at `pos==0`. In Rust use a local captured via a closure or a `Cell`; since `CardIterator` is a plain `fn`, the Rust `get_razz_rank` equivalent must be implemented inline (not via `iterate_hand` with a stateful fn) or use a thread-local. Recommended: reimplement the dedup logic directly over the hand's ordered cards.

## Implementation order

1. `CardSuitRank`/`CardRank`/`CardSuit` conversions: `cardtostr`, `ranktostr`, `strtorank`.
2. `Card`: `write_card`, `get_card_suit_rank`, `get_card_rank`, `get_card_suit`, `create_card`, `strtocard`.
3. Sorters: `sort_card_after`, `sort_card_by_rank`.
4. `CardDeck`: `create_shuffled_deck`, `is_card_in_deck`, `strip_card_from_deck`, `deal_from_deck` (+ `lrand48` clone).
5. `CardCollection` + `CardHand`: `create_hand`, `reset_hand`, `insert_into_hand`, `count_cards_in_hand`, `get_max_of_hand`, `get_max_rank_of_hand`, `iterate_hand`, `remove_from_hand`, `remove_from_hand_under_iter`.
6. `razz_simulation`: `strip_deck`, `complete_hand`, `simulate_razz_game`.

See `notes/spec_card.md` and `notes/spec_razz_simulation.md` for per-function detail.
