# Failure Analysis: `test_card_operations` (src/bin/test.rs:131)

## Summary

Two distinct problems:

1. **TRANSLATION_BUG** in `CardDeck::deal_from_deck` (and `is_card_in_deck`) — the deck
   representation is inverted relative to C, so dealing removes the card instead of keeping it.
2. **INTERFACE WARNING** — `append_into_collection` and `insert_into_collection` have changed
   `pub` signatures. These are `pub fn` on `CardCollection` in `src/card.rs`; the harness expects
   the original signatures. This is a **TRANSLATION_BUG** (signature drift), not a spec gap.

---

## 1. `test_card_operations` failure at line 131

### Observed vs expected

- Line 129–133:
  ```rust
  for _ in 1..=50 {
      c = d.as_mut().unwrap().deal_from_deck();
      assert!(c.is_some());                                   // line 131
      assert!(d.as_ref().unwrap().is_card_in_deck(c...get_card_suit_rank()) == 0); // line 132
  }
  c = d.as_mut().unwrap().deal_from_deck();
  assert!(c.is_none());                                       // line 135
  ```
- The deck starts with 52 cards. Lines 125/127 strip `HeartK` and `Heart9`, leaving **50** cards.
- The loop deals 50 times, each time asserting `c.is_some()` (line 131) and that the dealt card is
  **no longer in the deck** (line 132). After the loop, one more deal must return `None` (line 135).
- Observed: `assertion failed: c.is_some()` at line 131 — i.e. `deal_from_deck` returned `None`
  before 50 successful deals.

### Root cause (C behaviour)

C `deal_from_deck` (c/card.c:889–922):

```c
selected_card_idx = lrand48 () % d->card_count;
valid_card_idx = 0;
for (i = 0; i < CARD_COUNT; i++) {
    c = &d->cards[i];
    if (get_card_suit_rank (c) == INVALID_CARD) {   // slot is EMPTY
        if (valid_card_idx == selected_card_idx) {
            write_card (i, c);                       // fill the slot with card i
            d->card_count--;
            break;
        }
        valid_card_idx++;
    }
}
return c;
```

Key facts about the C deck representation:

- `create_shuffled_deck` (c/card.c:936–952) `memset`s the deck to **0** and sets
  `card_count = CARD_COUNT`. `INVALID_CARD_BITS == 0` (c/card.c:32). So **every slot starts
  INVALID/empty**; the deck is a set of *empty slots*, not a set of cards.
- `is_card_in_deck(c, d)` (c/card.c:883–887) returns
  `get_card_suit_rank(&d->cards[c]) == INVALID_CARD` — i.e. it returns **1 (true) when the slot is
  EMPTY**, 0 when the slot is filled. (The name is misleading; it reports "slot c is still empty".)
- `strip_card_from_deck(c, d)` (c/card.c:924–934): if slot `c` is empty, `write_card(c, card)`
  **fills** it and decrements `card_count`. So "stripping" *fills* a slot (removes it from the
  available pool).
- `deal_from_deck` picks the `selected_card_idx`-th **empty** slot, **fills** it with card `i`
  (`write_card(i, c)`), decrements `card_count`, and returns that card. The dealt card's slot is now
  **filled**, so `is_card_in_deck(dealt)` returns 0 — matching line 132.

So in C: empty slot = available; filled slot = dealt/stripped. `card_count` = number of empty slots.

### What the Rust translation does (wrong)

`src/card.rs`:

- `create_shuffled_deck` (543–552) fills **every** slot with a real card and sets
  `card_count = 52`. This is the **opposite** representation: filled = available.
- `is_card_in_deck` (499–507) returns 1 when a slot **contains** the card (filled = present).
- `strip_card_from_deck` (529–541) sets the slot to `INVALID_CARD_BITS` (empties it).
- `deal_from_deck` (509–527) scans for slots that are `INVALID_CARD_BITS` (empty) and treats those
  as the available pool. But after `create_shuffled_deck` **no slot is empty**, so the scan finds
  nothing and returns `None` immediately — hence `c.is_some()` fails at line 131 on the very first
  iteration.

The Rust code mixed the two conventions: `create_shuffled_deck` uses "filled = available" while
`deal_from_deck` uses "empty = available". They are inconsistent, so dealing always fails.

### Classification

**TRANSLATION_BUG** — suspect functions `CardDeck::create_shuffled_deck`, `deal_from_deck`,
`is_card_in_deck`, `strip_card_from_deck` in `src/card.rs`. The deck's empty/filled convention was
inverted relative to C.

### Suggested fix (Writer)

Make the Rust deck match C exactly:

- `create_shuffled_deck`: initialise **all** slots to `INVALID_CARD_BITS` (empty), `card_count = 52`.
  (Do not pre-fill cards.)
- `is_card_in_deck(c)`: return 1 iff slot `c` is `INVALID_CARD_BITS` (empty), else 0 — i.e. mirror
  `get_card_suit_rank(&cards[c]) == INVALID_CARD`.
- `strip_card_from_deck(c)`: if slot `c` is empty, **fill** it with `Card::write_card(c)` and
  decrement `card_count`; otherwise do nothing.
- `deal_from_deck`: if `card_count == 0` return `None`; pick `selected = next_random() % card_count`;
  scan slots `i` in order; for each **empty** slot, if its running empty-index equals `selected`,
  **fill** it with `Card::write_card(suit_rank_from_index(i))`, decrement `card_count`, and return
  that card. (This mirrors C's `write_card(i, c)` — the dealt card is written into the slot, so it
  is no longer empty and `is_card_in_deck` returns 0 for it, satisfying line 132.)

Note: the PRNG must reproduce `lrand48` for the graded `SEED3_DEALING_ORDER` expectations; that is a
separate concern from this failure but the same function. Verify the deal order against the oracle
after fixing the representation.

---

## 2. Missing/changed `pub` signatures

Harness reports:

```
pub fn append_into_collection(self, Self) -> Self
pub fn insert_into_collection(self, Option<Card>, CardSorter) -> Self
```

Current Rust (`src/card.rs`):

- `pub fn insert_into_collection(mut self, c: Option<Card>, sorter: CardSorter) -> Self` (247)
- `pub fn append_into_collection(mut self, mut new: Self) -> Self` (288)

The parameter types are `Option<Card>` and `Self`, which is what the warning lists, but the warning
still fires — the harness compares the **exact** original signature. The likely mismatch is the
`mut` on the receiver/parameter or the exact spelling. The original interface (per the warning) is:

```rust
pub fn append_into_collection(self, Self) -> Self
pub fn insert_into_collection(self, Option<Card>, CardSorter) -> Self
```

### Classification

**TRANSLATION_BUG** (signature drift). The bodies may keep internal `mut` bindings, but the `pub`
signature must read exactly `fn append_into_collection(self, new: Self) -> Self` and
`fn insert_into_collection(self, c: Option<Card>, sorter: CardSorter) -> Self` — i.e. **no `mut`
keyword in the parameter list**. `mut self` / `mut new` in the signature is what the harness flags.

### Suggested fix (Writer)

Change the signatures to drop `mut` from the parameters and rebind inside the body:

```rust
pub fn insert_into_collection(self, c: Option<Card>, sorter: CardSorter) -> Self {
    let mut this = self;
    // ... existing body using `this` ...
}

pub fn append_into_collection(self, new: Self) -> Self {
    let mut this = self;
    let mut new = new;
    // ... existing body ...
}
```

Keep the return type `Self` and parameter types unchanged. Do not alter the behaviour.

---

## Priority

1. Fix the deck representation (`create_shuffled_deck` / `deal_from_deck` / `is_card_in_deck` /
   `strip_card_from_deck`) — this unblocks `test_card_operations` line 131.
2. Fix the two `pub` signatures (drop `mut` in the parameter lists) — clears the interface warning.
3. Re-verify the deal order against the C oracle (`lrand48` sequence) for `SEED3_DEALING_ORDER`.
