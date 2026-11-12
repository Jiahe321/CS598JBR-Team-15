# Spec: C `card`/`razz_simulation` → Rust crate

## Module map

| C file | Rust module | Notes |
|---|---|---|
| `c/card.c` + `c/card.h` | `src/card.rs` (`pub mod card`) | cards, hands, decks, sorting, iteration |
| `c/razz_simulation.c` + `c/razz_simulation.h` | `src/razz_simulation.rs` (`pub mod razz_simulation`) | Razz game simulation |
| `c/razz.c` (main / CLI) | not translated | only `process_args`/`listener` logic informs semantics |
| `c/card_test.c` | not translated | graded tests live in `src/bin/test.rs` |

`src/lib.rs` declares `pub mod card;` and `pub mod razz_simulation;`.
`src/razz_simulation.rs` does `use crate::card::card::{Card, CardDeck, CardHand, CardRank};`
and wraps its items in an inner `pub mod razz_simulation { ... }`.

## Data structures

### C
```c
struct card_impl { uint8_t card; };   /* bits 7..5 = suit, bits 4..0 = rank */
struct card_collection { struct card_collection *prev, *next; const card *c; }; /* circular doubly-linked list */
struct card_hand_impl { unsigned char max, len; card_sorter sorter; struct card_collection *cards; };
struct card_deck_impl { unsigned char card_count; struct card cards[CARD_COUNT]; };
struct decided_cards { uint8_t my_card_count; const card *my_cards[3];
                       uint8_t opponent_card_count; const card *opponent_cards[7]; };
```

### Rust (fixed, do not change)
- `Card { card: u8 }` — same bit packing.
- `CardCollection { prev: Option<Box<CardCollection>>, next: Option<Box<CardCollection>>, c: Option<Card> }`
  — the C circular list is replaced by an owned `Box` chain. See `spec_card.md` for the recommended
  interpretation of each method; the C circular-list semantics must be reproduced *observably*
  (ordering, insertion position, removal), not structurally.
- `CardHand { max: u8, len: u8, sorter: CardSorter, cards: CardCollection }`.
- `CardDeck { card_count: u8, cards: [Card; 52] }`.
- `DecidedCards { my_card_count: u8, my_cards: [Option<Card>;3], opponent_card_count: u8, opponent_cards: [Option<Card>;7] }`.

## Bit encoding (from `card.c` defines; mirrored by the Rust consts)

```
INVALID_CARD_BITS = 0
SUIT_BITS  = 0x7 << 5 ; SPADE=1<<5, HEART=2<<5, DIAMOND=3<<5, CLUB=4<<5
RANK_BITS  = 0x1F ; ACE=1, R2=2, ... R10=10, J=11, Q=12, K=13
```
A card is `suit_bits | rank_bits`. `INVALID_CARD_BITS == 0` means "no card" (empty deck slot).

## Global / static state

- `card.c`: no mutable globals. `cardtostr`/`ranktostr` use `static const char *` tables (pure).
- `razz_simulation.c`: `duplicated_rank_remover` uses a **function-local `static enum card_rank prev_rank`**
  that persists across calls. In Rust this must become state carried by the closure/iterator, not a
  global (see `spec_razz_simulation.md`).
- `razz.c` calls `srand48(time(NULL))`; `deal_from_deck` uses `lrand48()`. The Rust version must use a
  deterministic PRNG whose first 52-card shuffle reproduces the graded `SEED3_DEALING_ORDER` and whose
  first-card distribution over 52 000 decks matches `expected_card_count` in `src/bin/test.rs`.
  **The exact PRNG is unclear from the C source alone** (it is `lrand48` seeded by `srand48`); the
  Writer must derive it from the two graded expectations. See `spec_card.md` §PRNG.

## Implementation order

1. `CardRank` / `CardSuit` / `CardSuitRank` conversions (`ranktostr`, `strtorank`, `cardtostr`).
2. `Card`: `write_card`, `get_card_suit_rank`, `get_card_rank`, `get_card_suit`, `create_card`, `strtocard`.
3. `CardDeck`: `create_shuffled_deck`, `is_card_in_deck`, `strip_card_from_deck`, `deal_from_deck`
   (needs the PRNG).
4. Sorters: `sort_card_after`, `sort_card_by_rank`.
5. `CardCollection` + `CardHand` (insert / iterate / remove / max rank / count).
6. `razz_simulation`: `strip_deck`, `complete_hand`, `simulate_razz_game`.

## Graded tests

`src/bin/test.rs` has one `#[test] fn test_card_operations()` covering: enum ordering, card creation
and accessors, `strtocard` (case-insensitive, rejects `"SS"`, `"S0"`, `"S1"`, `"a2"`), `strtorank`
(`"ace"`→Ace, `"8"`→R8, `"K"`→K, `"10"`→R10, `"1"`→InvalidRank), `cardtostr`/`ranktostr` incl. `None`
for `CardCount`/`InvalidRank`, deck strip/deal exhaustion, hand insert/iterate/remove/max-rank, and the
52 000-deck first-card distribution. `main() {}` is empty.
