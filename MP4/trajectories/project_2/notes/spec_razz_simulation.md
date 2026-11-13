# Spec: `razz_simulation` module (c/razz_simulation.c, c/razz_simulation.h -> src/razz_simulation.rs)

## Constants
`RAZZ_CARD_IN_HAND_COUNT = 7` (razz_simulation.c:24).

## `DecidedCards` (razz_simulation.h:33-39)
Rust: `{ my_card_count: u8, my_cards: [Option<Card>;3], opponent_card_count: u8, opponent_cards: [Option<Card>;7] }`. Matches C layout (3 my cards, 7 opponent cards).

## `strip_deck(deck, decided_cards)` (razz_simulation.c:156-174)
For `i in 0..my_card_count`: `strip_card_from_deck(get_card_suit_rank(my_cards[i]), deck)`. Then for `i in 0..opponent_card_count`: same for `opponent_cards[i]`. Precondition: no duplicates among decided cards (caller ensures). Rust: iterate `my_cards[..my_card_count]` and `opponent_cards[..opponent_card_count]`, calling `deck.strip_card_from_deck(csr)` where `csr = card.get_card_suit_rank()`.

## `complete_hand(my_hand, decided_cards, deck)` (razz_simulation.c:34-51)
For `i in 0..my_card_count`: `insert_into_hand(my_hand, my_cards[i])`. Then `end = 7 - my_card_count`; for `i in 0..end`: `insert_into_hand(my_hand, deal_from_deck(deck))`. Rust: insert decided cards (as `&Option<Card>`), then deal `7 - my_card_count` cards from deck and insert each. Note: `insert_into_hand` no-ops if hand full (max=7), so if `my_card_count` > 7 it would overflow — but max is 3.

## `simulate_razz_game(decided_cards, game_count, arg, listener) -> i32` (razz_simulation.c:176-215)
1. `my_hand = create_hand(7, sort_card_by_rank)`; if None -> return 1 (print error).
2. For `i in 0..game_count`:
   - `deck = create_shuffled_deck()`; if None -> return 1.
   - `strip_deck(deck, decided_cards)`.
   - `complete_hand(my_hand, decided_cards, deck)`.
   - `listener(arg, get_razz_rank(my_hand))`.
   - `reset_hand(my_hand)`; destroy deck.
3. Destroy hand; return 0.

Rust: `simulate_razz_game<T>(decided_cards, game_count, arg: &mut T, listener: RankListener<T>) -> i32`. Same loop; `listener(arg, rank)`. Return 0 on success, 1 on hand/deck creation failure (creation never fails in Rust, so effectively always 0).

## `get_razz_rank(hand) -> CardRank` (razz_simulation.c:104-147) — internal, must be reproduced
1. (debug print — omit in Rust.)
2. `iterate_hand(hand, duplicated_rank_remover)` — removes consecutive duplicate ranks. `duplicated_rank_remover` (razz_simulation.c:54-74): tracks `prev_rank`; at `pos==0` set `prev_rank=curr`, Continue; if `prev_rank==curr` -> `RemoveAndContinue`; else `prev_rank=curr`, Continue. Because hand is sorted ascending by rank, this removes all but the first of each equal-rank run. **Rust**: since `CardIterator` is a plain `fn` (no captured state), reimplement directly: walk the hand's ordered cards, keep first of each rank run, remove the rest (or build a filtered list). Equivalent: dedupe consecutive equal ranks in the sorted hand.
3. `cards_count = count_cards_in_hand(hand)`. If `< 5` -> return `InvalidRank` (too many pairs).
4. `iterate_hand(hand, length_trimmer)` — `length_trimmer` (razz_simulation.c:76-86): if `pos >= 5` -> `RemoveAndContinue`, else Continue. Keeps first 5 cards.
5. `r = get_max_rank_of_hand(hand)`; return `r`.

Net effect: sort hand by rank ascending, dedupe equal ranks, if fewer than 5 distinct ranks -> InvalidRank, else take the 5 lowest distinct ranks and return the highest of them (the 5th-lowest distinct rank). This is the Razz hand rank (R5..K or InvalidRank).

## `listener` (razz.c:142-157) — CLI only, not in Rust interface
Counts ranks in `[R5, K]`; ignores InvalidRank and out-of-range. Not required in Rust (the graded test supplies its own listener). Recorded for completeness.

## `process_args` (razz.c:24-140) — CLI only, not in Rust interface
Parses game count and ranks, assigns suits greedily (Spade first, then Heart, Diamond, Club) to avoid duplicates, strips from a temp deck. Not required in Rust.

## Tests
The graded test `src/bin/test.rs` exercises only the `card` module (no razz_simulation calls). `razz_simulation` functions must still compile and behave per above for any additional tests. No protected test asserts razz output values, so exact PRNG only matters for `card` distribution test.
