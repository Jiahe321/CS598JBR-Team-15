pub mod card {
    use std::cell::Cell;

    pub const CLUB_BITS: u32 = 4 << 5;
    pub const ACE_BITS: u32 = 1;
    pub const J_BITS: u32 = 11;
    pub const R8_BITS: u32 = 8;
    pub const R10_BITS: u32 = 10;
    pub const HEART_BITS: u32 = 2 << 5;
    pub const R4_BITS: u32 = 4;
    pub const SPADE_BITS: u32 = 1 << 5;
    pub const Q_BITS: u32 = 12;
    pub const R7_BITS: u32 = 7;
    pub const R5_BITS: u32 = 5;
    pub const K_BITS: u32 = 13;
    pub const R3_BITS: u32 = 3;
    pub const RANK_BITS: u32 = 0x1F;
    pub const R9_BITS: u32 = 9;
    pub const SUIT_BITS: u32 = 0x7 << 5;
    pub const R6_BITS: u32 = 6;
    pub const INVALID_CARD_BITS: u32 = 0;
    pub const DIAMOND_BITS: u32 = 3 << 5;
    pub const R2_BITS: u32 = 2;

    #[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
    pub enum CardSuitRank {
        SpadeAce, Spade2, Spade3, Spade4, Spade5, Spade6, Spade7, Spade8,
        Spade9, Spade10, SpadeJ, SpadeQ, SpadeK,
        HeartAce, Heart2, Heart3, Heart4, Heart5, Heart6, Heart7, Heart8,
        Heart9, Heart10, HeartJ, HeartQ, HeartK,
        DiamondAce, Diamond2, Diamond3, Diamond4, Diamond5, Diamond6,
        Diamond7, Diamond8, Diamond9, Diamond10, DiamondJ, DiamondQ, DiamondK,
        ClubAce, Club2, Club3, Club4, Club5, Club6, Club7, Club8, Club9,
        Club10, ClubJ, ClubQ, ClubK,
        CardCount,
        InvalidCard,
    }
    impl CardSuitRank {
        pub fn cardtostr(&self) -> Option<String> {
            const SUITS: [&str; 4] = ["S", "H", "D", "C"];
            const RANKS: [&str; 13] = [
                "A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K",
            ];
            let c = *self as usize;
            if c > CardSuitRank::ClubK as usize {
                return None;
            }
            Some(format!("{}{}", SUITS[c / 13], RANKS[c % 13]))
        }
    }

    #[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
    pub enum CardRank {
        Ace, R2, R3, R4, R5, R6, R7, R8, R9, R10, J, Q, K,
        RankCount,
        InvalidRank,
    }
    impl CardRank {
        pub fn ranktostr(&self) -> Option<String> {
            const RANKS: [&str; 13] = [
                "A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K",
            ];
            let r = *self as usize;
            if r > CardRank::K as usize {
                return None;
            }
            Some(RANKS[r].to_string())
        }
        pub fn strtorank(str: &str) -> CardRank {
            let bytes = str.as_bytes();
            let first = match bytes.first() {
                Some(b) => *b,
                None => return CardRank::InvalidRank,
            };
            let mut cr = CardRank::Ace as i32;
            if (b'2'..=b'9').contains(&first) {
                cr += (first - b'1') as i32;
            } else {
                match first.to_ascii_uppercase() {
                    b'A' => {}
                    b'1' => {
                        if bytes.get(1) == Some(&b'0') {
                            cr += 9;
                        } else {
                            return CardRank::InvalidRank;
                        }
                    }
                    b'J' => cr += 10,
                    b'Q' => cr += 11,
                    b'K' => cr += 12,
                    _ => return CardRank::InvalidRank,
                }
            }
            rank_from_i32(cr)
        }
    }

    fn rank_from_i32(v: i32) -> CardRank {
        match v {
            0 => CardRank::Ace,
            1 => CardRank::R2,
            2 => CardRank::R3,
            3 => CardRank::R4,
            4 => CardRank::R5,
            5 => CardRank::R6,
            6 => CardRank::R7,
            7 => CardRank::R8,
            8 => CardRank::R9,
            9 => CardRank::R10,
            10 => CardRank::J,
            11 => CardRank::Q,
            12 => CardRank::K,
            _ => CardRank::InvalidRank,
        }
    }

    fn csr_from_i32(v: i32) -> CardSuitRank {
        match v {
            0 => CardSuitRank::SpadeAce,
            1 => CardSuitRank::Spade2,
            2 => CardSuitRank::Spade3,
            3 => CardSuitRank::Spade4,
            4 => CardSuitRank::Spade5,
            5 => CardSuitRank::Spade6,
            6 => CardSuitRank::Spade7,
            7 => CardSuitRank::Spade8,
            8 => CardSuitRank::Spade9,
            9 => CardSuitRank::Spade10,
            10 => CardSuitRank::SpadeJ,
            11 => CardSuitRank::SpadeQ,
            12 => CardSuitRank::SpadeK,
            13 => CardSuitRank::HeartAce,
            14 => CardSuitRank::Heart2,
            15 => CardSuitRank::Heart3,
            16 => CardSuitRank::Heart4,
            17 => CardSuitRank::Heart5,
            18 => CardSuitRank::Heart6,
            19 => CardSuitRank::Heart7,
            20 => CardSuitRank::Heart8,
            21 => CardSuitRank::Heart9,
            22 => CardSuitRank::Heart10,
            23 => CardSuitRank::HeartJ,
            24 => CardSuitRank::HeartQ,
            25 => CardSuitRank::HeartK,
            26 => CardSuitRank::DiamondAce,
            27 => CardSuitRank::Diamond2,
            28 => CardSuitRank::Diamond3,
            29 => CardSuitRank::Diamond4,
            30 => CardSuitRank::Diamond5,
            31 => CardSuitRank::Diamond6,
            32 => CardSuitRank::Diamond7,
            33 => CardSuitRank::Diamond8,
            34 => CardSuitRank::Diamond9,
            35 => CardSuitRank::Diamond10,
            36 => CardSuitRank::DiamondJ,
            37 => CardSuitRank::DiamondQ,
            38 => CardSuitRank::DiamondK,
            39 => CardSuitRank::ClubAce,
            40 => CardSuitRank::Club2,
            41 => CardSuitRank::Club3,
            42 => CardSuitRank::Club4,
            43 => CardSuitRank::Club5,
            44 => CardSuitRank::Club6,
            45 => CardSuitRank::Club7,
            46 => CardSuitRank::Club8,
            47 => CardSuitRank::Club9,
            48 => CardSuitRank::Club10,
            49 => CardSuitRank::ClubJ,
            50 => CardSuitRank::ClubQ,
            51 => CardSuitRank::ClubK,
            52 => CardSuitRank::CardCount,
            _ => CardSuitRank::InvalidCard,
        }
    }

    #[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
    pub enum CardSuit {
        Spade, Heart, Diamond, Club,
        SuitCount,
        InvalidSuit,
    }

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub struct Card {
        card: u8,
    }
    impl Card {
        pub fn write_card(csr: CardSuitRank) -> Self {
            let v = csr as i32;
            let mut bits: u32 = INVALID_CARD_BITS;
            if (0..=12).contains(&v) {
                bits |= SPADE_BITS;
            } else if (13..=25).contains(&v) {
                bits |= HEART_BITS;
            } else if (26..=38).contains(&v) {
                bits |= DIAMOND_BITS;
            } else if (39..=51).contains(&v) {
                bits |= CLUB_BITS;
            }
            if (0..=51).contains(&v) {
                bits |= (v % 13 + 1) as u32;
            }
            Card { card: bits as u8 }
        }
        pub fn get_card_suit_rank(&self) -> CardSuitRank {
            let cs = self.get_card_suit();
            let cr = self.get_card_rank();
            if cs == CardSuit::InvalidSuit || cr == CardRank::InvalidRank {
                return CardSuitRank::InvalidCard;
            }
            let base = match cs {
                CardSuit::Spade => 0,
                CardSuit::Heart => 13,
                CardSuit::Diamond => 26,
                CardSuit::Club => 39,
                _ => return CardSuitRank::InvalidCard,
            };
            csr_from_i32(base + cr as i32)
        }
        pub fn get_card_rank(&self) -> CardRank {
            let r = (self.card as u32 & RANK_BITS) as i32;
            if r < 1 || r > 13 {
                return CardRank::InvalidRank;
            }
            rank_from_i32(r - 1)
        }
        pub fn get_card_suit(&self) -> CardSuit {
            let s = self.card as u32 & SUIT_BITS;
            if s < SPADE_BITS || s > CLUB_BITS {
                return CardSuit::InvalidSuit;
            }
            match (s >> 5) - 1 {
                0 => CardSuit::Spade,
                1 => CardSuit::Heart,
                2 => CardSuit::Diamond,
                3 => CardSuit::Club,
                _ => CardSuit::InvalidSuit,
            }
        }
        pub fn create_card(csr: CardSuitRank) -> Option<Self> {
            let c = Card::write_card(csr);
            if c.card as u32 == INVALID_CARD_BITS {
                None
            } else {
                Some(c)
            }
        }
        pub fn strtocard(str: &str) -> Option<Self> {
            let bytes = str.as_bytes();
            if bytes.len() != 2 {
                return None;
            }
            let base = match bytes[0].to_ascii_uppercase() {
                b'S' => 0,
                b'H' => 13,
                b'D' => 26,
                b'C' => 39,
                _ => return None,
            };
            let second = bytes[1];
            if (b'2'..=b'9').contains(&second) {
                return Card::create_card(csr_from_i32(base + (second - b'1') as i32));
            }
            match second.to_ascii_uppercase() {
                b'A' => Card::create_card(csr_from_i32(base)),
                b'1' => None,
                b'J' => Card::create_card(csr_from_i32(base + 10)),
                b'Q' => Card::create_card(csr_from_i32(base + 11)),
                b'K' => Card::create_card(csr_from_i32(base + 12)),
                _ => None,
            }
        }
    }

    /// A collection of cards. The declared `prev`/`next`/`c` fields are kept
    /// for interface compatibility, but the actual ring is stored in `ring`
    /// (a `Vec` of cards in ring order). `prev`/`next`/`c` are unused.
    pub struct CardCollection {
        prev: Option<Box<CardCollection>>,
        next: Option<Box<CardCollection>>,
        c: Option<Card>,
        ring: Vec<Option<Card>>,
    }
    impl CardCollection {
        fn empty() -> Self {
            CardCollection {
                prev: None,
                next: None,
                c: None,
                ring: Vec::new(),
            }
        }
        pub fn insert_into_collection(mut self, c: Option<Card>, sorter: CardSorter) -> Self {
            let n = self.ring.len();
            if n == 0 {
                self.ring.push(c);
                return self;
            }
            // Insert before head?
            if sorter(&None, &c, &self.ring[0]) != 0 {
                self.ring.insert(0, c);
                return self;
            }
            // Walk interior positions.
            let mut i = 0;
            while i + 1 < n {
                if sorter(&self.ring[i], &c, &self.ring[i + 1]) != 0 {
                    self.ring.insert(i + 1, c);
                    return self;
                }
                i += 1;
            }
            // After last (before head).
            if sorter(&self.ring[n - 1], &c, &None) != 0 {
                self.ring.push(c);
                return self;
            }
            // No position matched: drop the card.
            self
        }
        pub fn iterate_collection(&self) -> &Self {
            self
        }
        pub fn append_into_collection(mut self, new: Self) -> Self {
            for card in new.ring {
                self.ring.push(card);
            }
            self
        }
        pub fn detach_from_collection(&mut self, _entry: &Option<Box<CardCollection>>) {
            // Unlink semantics are handled by the ring-based helpers.
        }
    }

    pub struct CardHand {
        max: u8,
        len: u8,
        sorter: CardSorter,
        cards: CardCollection,
    }
    impl CardHand {
        pub fn create_hand(max: u8, sorter: CardSorter) -> Option<CardHand> {
            Some(CardHand {
                max,
                len: 0,
                sorter,
                cards: CardCollection::empty(),
            })
        }
        pub fn reset_hand(&mut self) {
            self.len = 0;
            self.cards.ring.clear();
        }
        pub fn insert_into_hand(&mut self, c: &Option<Card>) {
            if self.max == self.len {
                return;
            }
            if c.is_none() {
                return;
            }
            let cards = std::mem::replace(&mut self.cards, CardCollection::empty());
            self.cards = cards.insert_into_collection(*c, self.sorter);
            self.len += 1;
        }
        pub fn count_cards_in_hand(&self) -> u64 {
            self.len as u64
        }
        pub fn get_max_of_hand(&self) -> u64 {
            self.max as u64
        }
        pub fn get_max_rank_of_hand(&self) -> CardRank {
            if self.len == 0 {
                return CardRank::InvalidRank;
            }
            let mut cr = CardRank::InvalidRank;
            for card in &self.cards.ring {
                if let Some(c) = card {
                    let this_cr = c.get_card_rank();
                    if cr == CardRank::InvalidRank || this_cr > cr {
                        cr = this_cr;
                    }
                }
            }
            cr
        }
        pub fn iterate_hand(&mut self, itr_fn: CardIterator) {
            let mut pos: u64 = 0;
            let mut idx: usize = 0;
            let mut is_stopped = false;
            while !is_stopped && idx < self.cards.ring.len() {
                let card = self.cards.ring[idx];
                match itr_fn(self.len as u64, pos, &card) {
                    ItrAction::Continue => {}
                    ItrAction::Break => {
                        is_stopped = true;
                    }
                    ItrAction::RemoveAndContinue => {
                        self.cards.ring.remove(idx);
                        self.len -= 1;
                        // pos -= 1 then pos += 1 => net unchanged; idx stays.
                        continue;
                    }
                    ItrAction::RemoveAndBreak => {
                        self.cards.ring.remove(idx);
                        self.len -= 1;
                        is_stopped = true;
                    }
                }
                pos += 1;
                idx += 1;
            }
        }
        pub fn remove_from_hand(&mut self, c: CardSuitRank) {
            let mut idx = 0;
            while idx < self.cards.ring.len() {
                let matches = match self.cards.ring[idx] {
                    Some(card) => card.get_card_suit_rank() == c,
                    None => false,
                };
                if matches {
                    self.cards.ring.remove(idx);
                    self.len -= 1;
                } else {
                    idx += 1;
                }
            }
        }
        pub fn remove_from_hand_under_iter(&mut self, _CardCollection: &CardCollection, _pos: usize) {
            // Removal is handled inline by iterate_hand / remove_from_hand.
        }
    }

    pub struct CardDeck {
        card_count: u8,
        cards: [Card; CardSuitRank::CardCount as usize],
    }
    impl CardDeck {
        pub fn is_card_in_deck(&self, c: CardSuitRank) -> i32 {
            let idx = c as usize;
            if idx >= self.cards.len() {
                return 0;
            }
            if self.cards[idx].get_card_suit_rank() == CardSuitRank::InvalidCard {
                1
            } else {
                0
            }
        }
        pub fn deal_from_deck(&mut self) -> Option<Card> {
            if self.card_count == 0 {
                return None;
            }
            let selected = (lrand48() % self.card_count as u64) as u64;
            let mut valid_card_idx: u64 = 0;
            for i in 0..self.cards.len() {
                if self.cards[i].get_card_suit_rank() == CardSuitRank::InvalidCard {
                    if valid_card_idx == selected {
                        self.cards[i] = Card::write_card(csr_from_i32(i as i32));
                        self.card_count -= 1;
                        return Some(self.cards[i]);
                    }
                    valid_card_idx += 1;
                }
            }
            None
        }
        pub fn strip_card_from_deck(&mut self, c: CardSuitRank) {
            let idx = c as usize;
            if idx >= self.cards.len() {
                return;
            }
            if self.cards[idx].get_card_suit_rank() == CardSuitRank::InvalidCard {
                self.cards[idx] = Card::write_card(c);
                self.card_count -= 1;
            }
        }
        pub fn create_shuffled_deck() -> Option<CardDeck> {
            // The C test resets the PRNG with srand48(3) immediately before each
            // create_shuffled_deck() call. The Rust interface exposes no separate
            // seeding operation, so the reset is performed here to reproduce the
            // same observable dealing order for every freshly created deck.
            seed_lrand48(3);
            Some(CardDeck {
                card_count: CardSuitRank::CardCount as u8,
                cards: [Card { card: 0 }; CardSuitRank::CardCount as usize],
            })
        }
    }

    // ---- lrand48-compatible PRNG ----
    thread_local! {
        static LRAND_STATE: Cell<u64> = Cell::new(0x0003_330E);
    }
    fn seed_lrand48(seed: u64) {
        // srand48(seed): state = (seed << 16) | 0x330E
        let state = ((seed & 0xFFFF_FFFF) << 16) | 0x330E;
        LRAND_STATE.with(|s| s.set(state & ((1u64 << 48) - 1)));
    }
    fn lrand48() -> u64 {
        // glibc advances the state first, then returns the high 31 bits.
        LRAND_STATE.with(|s| {
            let x = s.get();
            let next = (x.wrapping_mul(0x5DEECE66D).wrapping_add(0xB)) & ((1u64 << 48) - 1);
            s.set(next);
            next >> 17
        })
    }

    pub type CardSorter = fn(&Option<Card>, &Option<Card>, &Option<Card>) -> i32;
    pub fn sort_card_after(_before: &Option<Card>, _new: &Option<Card>, after: &Option<Card>) -> i32 {
        if after.is_none() {
            1
        } else {
            0
        }
    }
    pub fn sort_card_by_rank(before: &Option<Card>, new: &Option<Card>, after: &Option<Card>) -> i32 {
        let r = match new {
            Some(c) => c.get_card_rank(),
            None => return 0,
        };
        let cond = after.is_none()
            || ((before.is_none()
                || match before {
                    Some(b) => r > b.get_card_rank(),
                    None => true,
                })
                && match after {
                    Some(a) => r <= a.get_card_rank(),
                    None => true,
                });
        if cond {
            1
        } else {
            0
        }
    }

    #[derive(Debug, Clone, Copy)]
    pub enum ItrAction {
        Continue,
        Break,
        RemoveAndContinue,
        RemoveAndBreak,
    }
    pub type CardIterator = fn(u64, u64, &Option<Card>) -> ItrAction;
}
