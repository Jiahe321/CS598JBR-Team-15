# spec_razz_simulation.md — `src/razz_simulation.rs` (from `c/razz_simulation.c`, `c/razz_simulation.h`)

`RAZZ_CARD_IN_HAND_COUNT = 7` (razz_simulation.c:24).

## `DecidedCards` (razz_simulation.h:33-39)
`my_card_count: u8`, `my_cards: [Option<Card>;3]`, `opponent_card_count: u8`,
`opponent_cards: [Option<Card>;7]`. These are the cards removed from the deck before dealing
(they are "known"/decided and not re-dealt).

## `strip_deck(deck: &mut CardDeck, decided_cards: &DecidedCards)` (razz_simulation.c:156-174)
For `i in 0..my_card_count`: `strip_card_from_deck(get_card_suit_rank(my_cards[i]), deck)`.
For `i in 0..opponent_card_count`: `strip_card_from_deck(get_card_suit_rank(opponent_cards[i]), deck)`.
Precondition: decided cards contain no duplicates (caller guarantees). `strip_card_from_deck` is
idempotent (no-op if already stripped).

## `complete_hand(my_hand: &mut CardHand, decided_cards: &DecidedCards, deck: &mut CardDeck)` (razz_simulation.c:34-51)
- For `i in 0..my_card_count`: `insert_into_hand(my_hand, &my_cards[i])`.
- Then deal `7 - my_card_count` cards: for each, `insert_into_hand(my_hand, &deal_from_deck(deck))`.
So the hand ends with exactly 7 cards (assuming deck has enough). Insertion uses the hand's sorter
(`sort_card_by_rank`), so the hand is rank-sorted.

## `simulate_razz_game<T>(decided_cards, game_count, arg, listener) -> i32` (razz_simulation.c:176-215)
1. `my_hand = create_hand(7, sort_card_by_rank)`; if None -> return 1 (error).
2. For `i in 0..game_count`:
   - `deck = create_shuffled_deck()`; if None -> return 1.
   - `strip_deck(deck, decided_cards)`.
   - `complete_hand(my_hand, decided_cards, deck)`.
   - `listener(arg, get_razz_rank(my_hand))` — invoke the rank listener with the Razz rank.
   - `reset_hand(my_hand)`; destroy deck.
3. Destroy hand; return 0.

`RankListener<T> = fn(&mut T, CardRank)`; `arg: &mut T` is passed to the listener each game.

### `get_razz_rank(hand) -> CardRank` (razz_simulation.c:104-147) — internal, drives listener value
1. `iterate_hand(hand, duplicated_rank_remover)` — removes duplicate ranks (keeps first of each
   equal-rank run; hand is rank-sorted so equal ranks are adjacent).
2. `cards_count = count_cards_in_hand(hand)`. If `< 5` -> return `InvalidRank` (too many pairs).
3. `iterate_hand(hand, length_trimmer)` — removes cards at `pos >= 5` (keeps first 5).
4. `r = get_max_rank_of_hand(hand)`; return `r`.
So the Razz rank is the highest rank among the 5 lowest distinct ranks; `InvalidRank` if fewer than
5 distinct ranks.

### `duplicated_rank_remover` (razz_simulation.c:54-74)
Uses `static prev_rank`. At `pos == 0`: set `prev_rank = curr_rank`, `Continue`. Else if
`prev_rank == curr_rank` -> `RemoveAndContinue`; else `prev_rank = curr_rank`, `Continue`.
Because it is a `static`, state persists across calls; but `pos==0` resets it each iteration, so
per-call behaviour is deterministic. In Rust, model `prev_rank` as a local captured in a closure or
a `thread_local`/`Cell`; since `CardIterator` is a plain `fn` type, use a `thread_local!` static or
restructure `get_razz_rank` to do the dedup inline (recommended: inline loop, no static needed).

### `length_trimmer` (razz_simulation.c:77-86)
`pos >= 5` -> `RemoveAndContinue`; else `Continue`.

### `card_printer` (razz_simulation.c:89-94)
Debug-only (`#ifndef NDEBUG`); prints card strings. Not needed for correctness; may be omitted.

## Notes / gaps
- `razz.c` (`main`, `process_args`, `listener`) is CLI-only and has no Rust interface counterpart;
  not required. `process_args` builds `DecidedCards` by picking the first available suit for each
  specified rank (razz.c:63-89) — informational only.
- The Rust `simulate_razz_game` is generic over `T`; the C `void *arg` maps to `&mut T`.
- The listener in `razz.c` (razz.c:142-157) counts ranks R5..K; not part of the Rust interface.
- Randomness: `simulate_razz_game` relies on `deal_from_deck`'s `lrand48` state (see spec_card.md
  PRNG section). No seeding API exists in the Rust interface; the PRNG must be pre-seeded to the
  `srand48(3)` state to match the graded distribution test.
