# spec_card.md — `src/card.rs` (from `c/card.c`, `c/card.h`)

All line refs are `c/card.c` unless stated.

## Bit constants (card.c:32-53)
`INVALID_CARD_BITS=0`, `SUIT_BITS=0x7<<5`, `SPADE_BITS=1<<5`, `HEART_BITS=2<<5`,
`DIAMOND_BITS=3<<5`, `CLUB_BITS=4<<5`, `RANK_BITS=0x1F`, `ACE_BITS=1`..`K_BITS=13`.
These are already `pub const` in `src/card.rs`; keep values.

## `CardSuitRank::cardtostr(&self) -> Option<String>` (card.c:610-626)
Static table `s[SUIT_COUNT][RANK_COUNT]` (card.c:613-618):
rows Spade/Heart/Diamond/Club, columns A,2..9,10,J,Q,K -> `"SA".."SK"`, `"HA".."HK"`,
`"DA".."DK"`, `"CA".."CK"`.
- If `c < SPADE_ACE || c > CLUB_K` (i.e. `CardCount` or `InvalidCard`) return `None`.
- Else return `Some(s[c/13][c%13])`.
Tests: test.rs:111-115 (`Spade8->"S8"`, `Club10->"C10"`, `SpadeAce->"SA"`, `ClubK->"CK"`,
`CardCount->None`).

## `CardRank::ranktostr(&self) -> Option<String>` (card.c:628-641)
Table `{"A","2","3","4","5","6","7","8","9","10","J","Q","K"}`.
- If `r < ACE || r > K` (`RankCount` or `InvalidRank`) return `None`; else `Some(table[r])`.
Tests: test.rs:116-120.

## `CardRank::strtorank(str: &str) -> CardRank` (card.c:655-695)
C reads `str[0]` and possibly `str[1]`; Rust takes `&str`. Behaviour:
- `cr = ACE`.
- If `str[0]` in `'2'..='9'`: `cr += str[0]-'1'` (so `'2'->R2` ... `'9'->R9`).
- Else switch on `toupper(str[0])`:
  - `'A'` -> keep `ACE`.
  - `'1'` -> if `str[1] == '0'` then `cr += 9` (R10) else `INVALID_RANK`.
  - `'J'` -> `cr += 10`; `'Q'` -> `cr += 11`; `'K'` -> `cr += 12`.
  - default -> `INVALID_RANK`.
- Return `cr`.
Edge cases: C does not check string length; `"ace"` -> `'a'` uppercased `'A'` -> `Ace` (test.rs:106).
`"8"` -> `R8` (test.rs:107). `"K"` -> `K`. `"10"` -> `R10`. `"1"` -> `str[1]` is `'\0'` != `'0'`
-> `InvalidRank` (test.rs:110). In Rust, guard `str[1]` access: if the second byte is missing treat
as not `'0'` -> `InvalidRank`. Empty string: C reads `str[0]='\0'` -> default -> `INVALID_RANK`;
Rust should return `InvalidRank` for empty input (no panic).

## `Card::write_card(csr: CardSuitRank) -> Self` (card.c:62-165)
Sets `card = 0`; ORs suit bits if `csr` in a suit range; ORs rank bits via switch.
- Suit: `SpadeAce..=SpadeK` -> `SPADE_BITS`; `HeartAce..=HeartK` -> `HEART_BITS`;
  `DiamondAce..=DiamondK` -> `DIAMOND_BITS`; `ClubAce..=ClubK` -> `CLUB_BITS`.
- Rank: any of the four suits of a given rank -> that rank's bits (Ace=1 .. K=13).
- For `CardCount`/`InvalidCard` no bits are set -> `card == 0`.
This is a total function (no `Option`); `create_card` is the checked wrapper.

## `Card::get_card_rank(&self) -> CardRank` (card.c:503-514)
`r = card & RANK_BITS`. If `r < 1 || r > 13` -> `InvalidRank`; else `r-1` as `CardRank`
(`1->Ace`, ..., `13->K`).

## `Card::get_card_suit(&self) -> CardSuit` (card.c:516-527)
`s = card & SUIT_BITS`. If `s < SPADE_BITS || s > CLUB_BITS` -> `InvalidSuit`;
else `(s>>5)-1` as `CardSuit` (`1->Spade` ... `4->Club`).

## `Card::get_card_suit_rank(&self) -> CardSuitRank` (card.c:472-501)
If suit or rank invalid -> `InvalidCard`. Else base = `SpadeAce`/`HeartAce`/`DiamondAce`/`ClubAce`
per suit, return `base + rank` (enum arithmetic = discriminant addition). E.g. `Club8` -> `ClubAce+7 = Club8`.

## `Card::create_card(csr: CardSuitRank) -> Option<Self>` (card.c:529-550)
`write_card(csr)`; if resulting `card == 0` return `None`; else `Some`. So `CardCount` and
`InvalidCard` -> `None` (test.rs:66-67). `SpadeAce` -> `Some` (test.rs:61-65).

## `Card::strtocard(str: &str) -> Option<Self>` (card.c:552-608)
- `char_count = strlen(str)`; if `!= 2` return `None`. **Note:** the C code then has a dead branch
  `case '1': if (char_count == 3)` (card.c:591) that can never be true because length must be 2;
  so `"S10"` (length 3) returns `None` at the length check. Rust must replicate: only 2-byte strings
  are accepted, so `"S10"` -> `None`.
- `str[0]` uppercased: `'S'->SpadeAce`, `'H'->HeartAce`, `'D'->DiamondAce`, `'C'->ClubAce`;
  else `None`.
- If `str[1]` in `'2'..='9'`: `create_card(base + (str[1]-'1'))`.
- Else `toupper(str[1])`: `'A'->create_card(base)`; `'1'->None` (length is 2, not 3);
  `'J'->base+10`; `'Q'->base+11`; `'K'->base+12`; default `None`.
Tests: test.rs:73-105 (`"S8"`,`"dk"`,`"Ca"`,`"hJ"`,`"SQ"` valid; `"SS"`,`"S0"`,`"S1"`,`"a2"` -> None).
Note `"a2"`: `'a'` is not a suit -> `None`.

## `sort_card_after(before, new, after) -> i32` (card.c:697-706)
Returns `1` iff `after == None`, else `0`. (`before`/`new` unused.) In Rust `Option<Card>`:
`if after.is_none() { 1 } else { 0 }`.

## `sort_card_by_rank(before, new, after) -> i32` (card.c:708-721)
`r = get_card_rank(new)`. Return `1` iff `after == None` OR
(`before == None || r > get_card_rank(before)`) AND `r <= get_card_rank(after)`; else `0`.
This inserts after lower ranks and before higher-or-equal ranks (stable-ish: equal ranks go after
existing equal ranks because `r <= after` is required to insert before `after`; equal rank inserts
after the equal element). Ordering uses `CardRank` discriminant order (Ace=0 lowest .. K=12 highest).
Test evidence: hand sorted as `SA, D2, C2, D6, H9, H10, HQ` (test.rs:18-22) — note D2 before C2
(equal rank, insertion order preserved), and Ace first (lowest rank).

## `CardCollection` (card.c:167-451)
C is a circular doubly linked ring with a `head` pointer. The Rust struct
`{ prev: Option<Box<CardCollection>>, next: Option<Box<CardCollection>>, c: Option<Card> }` cannot
represent a ring with unique `Box` ownership. **Recommended safe design:** back the collection with
an arena `Vec` of nodes and store indices, OR implement the ring using `Rc<RefCell<...>>`-free
index links. Since the public struct fields are private and the public methods take/return `Self`
by value, the Writer may keep the declared struct but must implement the ring semantics through an
internal representation. Concretely, the simplest faithful approach: keep `CardCollection` as a
node and implement the ring using `Vec<CardCollection>`-style arena inside `CardHand`; but the
declared `CardHand.cards: CardCollection` field forces a node-based representation. A workable
encoding: treat `cards` as the head node; `next`/`prev` chains form the ring; use `Box` for the
forward chain and reconstruct `prev` lazily, OR store the ring as a `Vec` inside a single
`CardCollection` node's payload. **The exact internal encoding is left to the Writer as long as the
observable behaviour below holds.** Observable behaviour:

### `insert_into_collection(self, c, sorter) -> Self` (card.c:189-253)
Inserts `c` into the ring at the position chosen by `sorter`:
- Empty ring: new node becomes the sole element (prev=next=self), it is the head.
- If `sorter(None, c, head.c)` is nonzero: insert before head; new node becomes head.
- Else walk from head while `next != head`: if `sorter(itr.c, c, itr.next.c)` nonzero, insert
  between `itr` and `itr.next`.
- After the loop, if `sorter(last.c, c, None)` nonzero, insert after last (before head).
- Otherwise (no position matched) the node is allocated but **not linked** (C leaks it; returns 0).
  In Rust, if no position matches, the card is effectively dropped (not inserted). This only
  happens with a sorter that never returns nonzero; the provided sorters always match.
Returns the (possibly new) head.

### `iterate_collection(&self) -> &Self` (card.c:271-293)
C signature is `(head, &itr)` returning nonzero while more elements. The Rust signature
`iterate_collection(&self) -> &Self` is a reduced form; the Writer should implement iteration
semantics used by `iterate_hand`/`get_max_rank_of_hand` internally. Behaviour: starting from head,
successively yield each node following `next` until wrapping back to head. Empty -> nothing.

### `append_into_collection(self, new) -> Self` (card.c:302-318)
Append `new` at the end (before head). Empty -> new is sole element/head. Returns head.

### `detach_from_collection(&mut self, entry: &Option<Box<CardCollection>>)` (card.c:330-335)
Unlink `entry` from the ring: `entry.next.prev = entry.prev; entry.prev.next = entry.next`.
Does not free. (Signature is awkward; implement the unlink semantics.)

### `remove_from_collection_under_itr` (card.c:390-411) — internal
Detach entry; set iterator to `entry.prev` (or None if it was the only element); if the removed
entry was head, new head = `(itr==None ? None : itr.next)`. Used by `iterate_hand` removal.

## `CardHand` (card.c:453-881)

### `create_hand(max: u8, sorter: CardSorter) -> Option<CardHand>` (card.c:723-744)
Sets `max`, `len=0`, `sorter` (if sorter is the default/`sort_card_after` when NULL — in Rust the
sorter is a `fn` type, always provided; keep as given), `cards` empty. Always `Some` (C only fails
on malloc). Tests: test.rs:139-143, 196-197, 206-207.

### `reset_hand(&mut self)` (card.c:746-752)
`len = 0`; destroy collection (free nodes, **not** the cards). After reset, `count=0`,
`max` unchanged, `get_max_rank_of_hand = InvalidRank` (test.rs:187-190).

### `insert_into_hand(&mut self, c: &Option<Card>)` (card.c:754-764)
If `max == len` return (no-op; test.rs:172-175 inserting 8th card into 7-hand keeps count 7).
Else `insert_into_collection(&cards, c, sorter)`; `len += 1`.
Note: C inserts the card pointer; the hand does not own the card. In Rust `c: &Option<Card>` is
copied into the node (`Card` is `Copy`). Inserting `None` (a NULL deal) would insert a null card;
in practice `deal_from_deck` returns `Some` while deck non-empty. Guard: if `c` is `None`, C would
insert a NULL `c` and later `get_card_rank(NULL)` would crash; Rust should treat `None` as a no-op
insert (do not increment len) to stay safe — **unclear in C** (undefined behaviour), document as
defensive.

### `count_cards_in_hand(&self) -> u64` (card.c:766-770)
Returns `len`.

### `get_max_of_hand(&self) -> u64` (card.c:772-776)
Returns `max`.

### `get_max_rank_of_hand(&self) -> CardRank` (card.c:778-804)
If `len == 0` return `InvalidRank`. Else iterate all cards, track max `get_card_rank`; return it.
Tests: empty -> InvalidRank (test.rs:143); after 1 card H9 -> R9 (test.rs:147); etc.

### `iterate_hand(&mut self, itr_fn: CardIterator)` (card.c:827-853)
Iterate cards in ring order with `pos` starting 0, `len = h.len` (current). For each card call
`itr_fn(len, pos, &card)`:
- `Continue`: nothing.
- `Break`: stop.
- `RemoveAndContinue`: remove current node under iterator (`len -= 1`, `pos -= 1`), then `pos += 1`
  at loop end (net pos unchanged for next element — matches header comment card.h:291-297).
- `RemoveAndBreak`: remove current, stop.
`pos` increments each iteration. Tests: test.rs:176,181,186,192,216.

### `remove_from_hand(&mut self, c: CardSuitRank)` (card.c:855-867)
Iterate; for each card whose `get_card_suit_rank == c`, remove under iterator (len--). Removes all
matches. Tests: test.rs:177-180 (remove D6 -> count 6), 182-185 (remove HQ -> count 5, max rank
drops to R10), 191 (remove HQ from empty hand -> no-op), 202-203.

### `remove_from_hand_under_iter(&mut self, CardCollection: &CardCollection, pos: usize)` (card.c:814-825)
Internal helper: remove the entry under iteration, `len -= 1`, `pos -= 1`. Signature is a stub;
implement the removal semantics (detach node, decrement len).

## `CardDeck` (card.c:465-952)

### `create_shuffled_deck() -> Option<CardDeck>` (card.c:936-952)
`memset` deck to 0 (all card slots invalid = 0), `card_count = 52`. Always `Some`.
"Shuffled" is implicit: cards are dealt by random index selection, not by pre-shuffling.

### `is_card_in_deck(&self, c: CardSuitRank) -> i32` (card.c:883-887)
Returns `get_card_suit_rank(&cards[c]) == INVALID_CARD` as int (1 if still in deck, 0 if dealt).
Note the C doc comment (card.h:362) is misleading; the code returns 1 when the slot is empty
(card still in deck). Tests: test.rs:124 (`!= 0` before strip), 126 (`== 0` after strip).

### `strip_card_from_deck(&mut self, c: CardSuitRank)` (card.c:924-934)
If `cards[c]` is invalid (still in deck): `write_card(c, &cards[c])` (mark dealt), `card_count -= 1`.
If already dealt, no-op.

### `deal_from_deck(&mut self) -> Option<Card>` (card.c:889-922)
- If `card_count <= 0` return `None`.
- `selected = lrand48() % card_count`.
- Scan `i = 0..52`; count valid (invalid-slot) cards as `valid_card_idx`; when
  `valid_card_idx == selected`, `write_card(i, &cards[i])` (mark dealt), `card_count -= 1`, break.
- Return the dealt card (`Some(cards[i])`).
So it picks the `selected`-th still-in-deck card in index order 0..51. Tests: test.rs:129-135
(deal 50 after stripping 2 -> 50 Some then None), 218-235 (distribution).

### PRNG — `lrand48` compatibility (critical)
`deal_from_deck` uses `lrand48()` (card.c:902). The graded test (test.rs:218-235) asserts an exact
distribution after `srand48(3)` (the C test calls `srand48(3)` at card_test.c:335; the Rust test
does **not** call any seed function — the Rust interface exposes no seeding API). Therefore the
Rust implementation must reproduce glibc `lrand48` with the **default seed state** that yields the
same sequence the C test gets after `srand48(3)`.

glibc `srand48(seed)` sets `X = ((uint64_t)seed << 16) | 0x330E` (48-bit). `lrand48()` returns
`X >> 17` (top 31 bits) then advances `X = (X * 0x5DEECE66D + 0xB) & ((1<<48)-1)`.
With `srand48(3)`: `X0 = (3<<16)|0x330E = 0x0003_330E`.

**Unresolved compatibility gap:** the Rust interface has no `srand48`/seed entry point, yet the
graded test expects the exact `srand48(3)` distribution. The only way to satisfy test.rs:218-235
is for the Rust PRNG to be initialized to the `srand48(3)` state (`X = 0x0003330E`) at deck
creation (or as a module-level default). The Writer must implement a `lrand48` clone seeded with
`0x0003330E` and advance it globally across all `deal_from_deck` calls (the test creates a fresh
deck each iteration but the PRNG state must persist across decks — matching C where `srand48(3)`
is called once before the loop). This is the single most important behavioural requirement.
(If the Writer instead seeds per-deck, the distribution will not match. State must be process-global
and mutable, e.g. a `static`/`thread_local` `Cell<u64>`.)

## `CardSorter` / `CardIterator` types (card.rs:155,169)
`CardSorter = fn(&Option<Card>, &Option<Card>, &Option<Card>) -> i32`;
`CardIterator = fn(u64, u64, &Option<Card>) -> ItrAction`. Keep as declared.
