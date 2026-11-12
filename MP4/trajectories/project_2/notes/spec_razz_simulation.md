# Spec: `src/razz_simulation.rs` (from `c/razz_simulation.c`, `c/razz_simulation.h`)

Items live inside `pub mod razz_simulation { ... }`, which does
`use super::*;` with `use crate::card::card::{Card, CardDeck, CardHand, CardRank};` at the top of the
file. Keep every signature.

## Constants

`RAZZ_CARD_IN_HAND_COUNT = 7` (C `#define`). Each player is dealt 7 cards.

## `DecidedCards`

```rust
pub struct DecidedCards {
    pub my_card_count: u8,
    pub my_cards: [Option<Card>; 3],
    pub opponent_card_count: u8,
    pub opponent_cards: [Option<Card>; 7],
}
```
Mirrors C `struct decided_cards` (`const card *` → `Option<Card>`). Only the first
`my_card_count` / `opponent_card_count` entries are meaningful.

## `pub type RankListener<T> = fn(&mut T, CardRank);`

C `typedef void (*rank_listener)(void *arg, enum card_rank r)`. `void *arg` → generic `&mut T`.

## `strip_deck(deck: &mut CardDeck, decided_cards: &DecidedCards)`

C:
```
for (i = 0; i < decided_cards->my_card_count; i++)
  strip_card_from_deck(get_card_suit_rank(decided_cards->my_cards[i]), deck);
for (i = 0; i < decided_cards->opponent_card_count; i++)
  strip_card_from_deck(get_card_suit_rank(decided_cards->opponent_cards[i]), deck);
```
Rust: iterate `0..my_card_count as usize` over `my_cards`, then `0..opponent_card_count as usize`
over `opponent_cards`, calling `deck.strip_card_from_deck(card.get_card_suit_rank())`.
`strip_card_from_deck` is a no-op for already-stripped cards, so duplicates are harmless here.
Precondition (from the C doc comment): the decided cards contain no duplicates.

## `complete_hand(my_hand: &mut CardHand, decided_cards: &DecidedCards, deck: &mut CardDeck)`

C:
```
end = decided_cards->my_card_count;
for (i = 0; i < end; i++) insert_into_hand(my_hand, decided_cards->my_cards[i]);
end = RAZZ_CARD_IN_HAND_COUNT - end;
for (i = 0; i < end; i++) insert_into_hand(my_hand, deal_from_deck(deck));
```
Rust: insert the first `my_card_count` decided cards, then deal `7 - my_card_count` cards from the
deck and insert each. `insert_into_hand` takes `&Option<Card>`; `deal_from_deck` returns
`Option<Card>`, so pass `&deck.deal_from_deck()`.
Note: the hand is created with `max = 7` and `sorter = sort_card_by_rank`, so it stays sorted by rank.

## `simulate_razz_game<T>(decided_cards, game_count, arg, listener) -> i32`

C:
```
my_hand = create_hand(RAZZ_CARD_IN_HAND_COUNT, sort_card_by_rank);
if (my_hand == NULL) { fprintf(stderr, ...); return 1; }
for (i = 0; i < game_count; i++) {
  deck = create_shuffled_deck();
  if (deck == NULL) { ...; return 1; }
  strip_deck(deck, decided_cards);
  complete_hand(my_hand, decided_cards, deck);
  listener(arg, get_razz_rank(my_hand));
  reset_hand(my_hand);
  destroy_deck(&deck);
}
destroy_hand(&my_hand);
return 0;
```
Rust: `create_hand` always returns `Some`, so the first error path is unreachable; still return `0`
on success. Loop `0..game_count`, each iteration: fresh shuffled deck, `strip_deck`, `complete_hand`,
`listener(arg, get_razz_rank(my_hand))`, `reset_hand`. Return `0`.

## `get_razz_rank(hand) -> CardRank` (C static, not in the Rust interface)

C:
```
iterate_hand(hand, duplicated_rank_remover);   /* remove duplicate ranks, keeping the first */
cards_count = count_cards_in_hand(hand);
if (cards_count < 5) return INVALID_RANK;      /* too many pairs */
iterate_hand(hand, length_trimmer);            /* keep only the first 5 cards */
r = get_max_rank_of_hand(hand);
return r;
```
- `duplicated_rank_remover(len, pos, c)`: uses a **function-local `static prev_rank`**. On `pos == 0`
  it stores `prev_rank = get_card_rank(c)` and returns `CONTINUE`. Otherwise, if
  `prev_rank == curr_rank` return `REMOVE_AND_CONTINUE`; else `prev_rank = curr_rank; return CONTINUE`.
  Because the hand is sorted by rank, this removes all but the first card of each rank.
  **Rust:** the `static` must become state owned by the iteration (e.g. a `Cell<CardRank>` captured by
  a closure, or a hand-written loop). Do not use a global.
- `length_trimmer(len, pos, c)`: `if (pos >= 5) return REMOVE_AND_CONTINUE; return CONTINUE;` — keeps
  the first 5 cards.
- `get_max_rank_of_hand` on the trimmed hand returns the largest rank among the 5 kept cards, i.e. the
  **worst** (highest) rank of the best 5-card low hand. Since the hand is sorted ascending by rank,
  this is the rank of the 5th card.
- Return value range: `R5..=K` (per the C doc comment) or `INVALID_RANK` when the hand has fewer than
  5 distinct ranks. `razz.c` buckets results into `rank_count[K - R5 + 1]`, i.e. indices
  `R5..=K`, and prints `ranktostr(R5 + i)` with `rank_count[i] / game_count`.

Since `get_razz_rank` is not part of the Rust interface, implement it as a private helper inside
`simulate_razz_game` (or a private `fn` in the module).

## Notes / unclear

- The C `#ifndef NDEBUG` blocks print the hand and the rank; they are debug-only and must not be
  reproduced (no stdout output from the Rust version).
- The exact PRNG used by `create_shuffled_deck`/`deal_from_deck` is the highest-risk unknown; see
  `spec_card.md` §PRNG. `simulate_razz_game` inherits it.
- `razz.c`'s `process_args` (CLI parsing, suit assignment `csr = cs * RANK_COUNT + rank`, duplicate
  detection) is not part of the Rust interface and is not graded.
