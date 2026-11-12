# spec_card.md — focused refresh: card sort / deck deal ordering

## Evidence gathered (from src/bin/test.rs, graded test `test_card_operations`)

### 1. `CardSuitRank` ordering (Ord) — MUST match C enum order
The test asserts:
- `CardSuitRank::SpadeAce < CardSuitRank::SpadeK`
- `CardSuitRank::HeartK < CardSuitRank::ClubK`
- `CardRank::Ace < CardRank::R3`

So the derived `Ord` on `CardSuitRank` must follow the C enum declaration order in `c/card.h`
(rank-major, then suit within rank, with Ace first). The failing assertions
`left: ClubAce right: SpadeAce` at test lines 23/31/39 mean the sort comparator is producing
ClubAce where SpadeAce is expected — i.e. the comparator used by `sort_card_by_rank` is not
consistent with the enum's `Ord`. **Fix: the sort callback must compare with the same ordering as
`CardSuitRank`'s derived `Ord` (i.e. `a.get_card_suit_rank().cmp(&b.get_card_suit_rank())`), not a
hand-rolled rank/suit comparison.**

### 2. `sort_card_by_rank` expected results (test lines 17–52)
Given a hand built from the seed-3 dealing order, after sorting by rank the hand must read:
- test_sort_card_by_rank_1: `[SpadeAce, Diamond2, Club2, Diamond6, Heart9, Heart10, HeartQ]`
- test_sort_card_by_rank_2: `[SpadeAce, Diamond2, Club2, Heart9, Heart10, HeartQ]`
- test_sort_card_by_rank_3: `[SpadeAce, Diamond2, Club2, Heart9, Heart10]`
- test_sort_card_by_rank_4: `[Heart9, Heart10]`

Note `Diamond2 < Club2` and `Diamond6` sorts after `Club2` but before `Heart9`. This is exactly the
C enum order (rank-major, suit order within rank as declared). The current Rust output
`left: Diamond2 right: Heart9` at line 46 shows the comparator is ordering by suit first or using a
wrong suit precedence. **The comparator must be a pure `CardSuitRank` ordering.**

### 3. `test_empty_hand` (line 49–52)
Asserts the hand is empty when iterated. This is used to verify that after removals the hand has no
cards; if `remove_from_hand` leaves stale entries the iteration will call this and fail. Ensure
`remove_from_hand` actually removes and `count_cards_in_hand` reflects it.

### 4. Deck dealing order (test lines 204–217, and SEED3_DEALING_ORDER)
`CardDeck::create_shuffled_deck()` must produce the exact `SEED3_DEALING_ORDER` sequence shown at
the top of test.rs (52 cards, first dealt = `Heart9`, then `SpadeAce`, `Heart10`, `Club2`, ...).
The failing assertions at lines 147/151/155/... (`left: J right: R9`, `left: R8 right: R10`, etc.)
show the deck is dealing cards in the wrong order — the shuffle RNG or the deal index is off.
**The shuffle must reproduce the C `card.c` shuffle exactly (same RNG algorithm, same seed, same
swap loop), and `deal_from_deck` must pop from the front of the shuffled array in order.**

### 5. `get_max_rank_of_hand` (lines 199–215)
Must return the maximum `CardRank` currently in the hand (not suit-rank). After dealing
`Heart9` then `SpadeAce`... the max rank stays `R9` until a higher rank arrives (`R10`). This
depends on correct dealing order (item 4) and correct rank extraction.

## Action items for the Writer
1. Make `sort_card_by_rank` compare by `CardSuitRank` `Ord` only (no custom suit precedence).
2. Verify `CardSuitRank` enum variant declaration order matches `c/card.h` exactly.
3. Re-derive the shuffle in `create_shuffled_deck` from `c/card.c` (RNG + swap loop) so it yields
   `SEED3_DEALING_ORDER`.
4. Ensure `deal_from_deck` returns cards in array order and `insert_into_hand` respects the sorter.

## Unclear / not re-read this pass
- Exact RNG constants in `c/card.c` shuffle (read limit hit) — Writer must read `c/card.c`
  `create_shuffled_deck` / shuffle helper directly.
- Exact `CardSuitRank` enum order in `c/card.h` — Writer must confirm against the header.
