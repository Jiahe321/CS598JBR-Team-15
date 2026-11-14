# Razz Simulation — Translation Spec (overview)

## Module map (C -> Rust)

| C file | Rust module | Notes |
|---|---|---|
| `c/card.c` + `c/card.h` | `src/card.rs` (`pub mod card`) | cards, ranks, suits, hand, deck, sorters, iterators |
| `c/razz_simulation.c` + `c/razz_simulation.h` | `src/razz_simulation.rs` (`pub mod razz_simulation`) | Razz game simulation |
| `c/razz.c` (`main`, `process_args`, `listener`) | not in the Rust interface | CLI only; no Rust equivalent required |
| `c/card_test.c` | `src/bin/test.rs` (graded) | port of the C test |

`src/lib.rs` declares `pub mod card;` and `pub mod razz_simulation;`.

## Data structures

C `struct card_impl { uint8_t card; }` -> Rust `Card { card: u8 }` (private field).
Bit layout (card.c:27-53): low 5 bits = rank bits 1..13 (`ACE_BITS=1` .. `K_BITS=13`),
bits 5..7 = suit (`SPADE_BITS=1<<5`, `HEART_BITS=2<<5`, `DIAMOND_BITS=3<<5`, `CLUB_BITS=4<<5`),
`INVALID_CARD_BITS = 0` means "no card".

C `struct card_collection { prev, next, const card *c; }` -> Rust
`CardCollection { prev: Option<Box<CardCollection>>, next: Option<Box<CardCollection>>, c: Option<Card> }`.
The C structure is a **circular doubly linked ring**; the Rust struct as given cannot express a ring
with `Box` ownership. See `spec_card.md` for the recommended safe design (arena/`Vec`-backed ring or
index-based ring) that keeps the public signatures.

C `struct card_hand_impl { uint8_t max; uint8_t len; card_sorter sorter; struct card_collection *cards; }`
-> Rust `CardHand { max: u8, len: u8, sorter: CardSorter, cards: CardCollection }`.

C `struct card_deck_impl { char card_count; card cards[CARD_COUNT]; }` -> Rust
`CardDeck { card_count: u8, cards: [Card; 52] }`. A card slot is "in deck" iff its bits are 0
(`get_card_suit_rank == INVALID_CARD`).

C `struct decided_cards { uint8_t my_card_count; const card *my_cards[3]; uint8_t opponent_card_count; const card *opponent_cards[7]; }`
-> Rust `DecidedCards { my_card_count: u8, my_cards: [Option<Card>;3], opponent_card_count: u8, opponent_cards: [Option<Card>;7] }`.

## Global / static state

- `lrand48()` PRNG (card.c:902) — the only randomness source. The graded test relies on the exact
  glibc `lrand48` sequence after `srand48(3)` (see `spec_card.md`, "PRNG").
- `duplicated_rank_remover` uses a `static enum card_rank prev_rank` (razz_simulation.c:57) — a
  function-static that persists across calls; must be modelled as state reset at `pos == 0`.
- `cardtostr`/`ranktostr` use static string tables (card.c:613-618, 631-633).

## Implementation order

1. `CardSuitRank`/`CardRank`/`CardSuit` conversions: `cardtostr`, `ranktostr`, `strtorank`.
2. `Card`: `write_card`, `get_card_suit_rank`, `get_card_rank`, `get_card_suit`, `create_card`, `strtocard`.
3. Sorters: `sort_card_after`, `sort_card_by_rank`.
4. `CardDeck`: `create_shuffled_deck`, `is_card_in_deck`, `strip_card_from_deck`, `deal_from_deck`
   (needs the `lrand48`-compatible PRNG).
5. `CardCollection` + `CardHand` (insert/iterate/remove/reset).
6. `razz_simulation`: `strip_deck`, `complete_hand`, `simulate_razz_game`.

## Key cross-cutting facts

- `CardSuitRank` discriminants must match C enum order: `SpadeAce=0 .. ClubK=51`, `CardCount=52`,
  `InvalidCard=53`. `CardRank`: `Ace=0 .. K=12`, `RankCount=13`, `InvalidRank=14`.
  `CardSuit`: `Spade=0, Heart=1, Diamond=2, Club=3, SuitCount=4, InvalidSuit=5`.
  The Rust enums already declare them in this order, so `as usize`/`as u8` gives the C value.
- `CardSuitRank` derives `PartialOrd`; the test asserts `SpadeAce < SpadeK` and `HeartK < ClubK`
  (test.rs:58-59), which holds with declaration order.
- `CardRank` derives `PartialOrd`; test asserts `Ace < R3` (test.rs:60).
- `Card` has no `PartialEq`/`Clone` derive in the interface; `Option<Card>` is passed by reference
  everywhere, and `Card` is `Copy`-able in practice (single `u8`). Do not change the struct definition.
