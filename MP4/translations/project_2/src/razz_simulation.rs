use crate::card::card::{Card, CardDeck, CardHand, CardRank, CardSuitRank};
pub mod razz_simulation {
    use super::*;
    pub struct DecidedCards {
        pub my_card_count: u8,
        pub my_cards: [Option<Card>; 3],
        pub opponent_card_count: u8,
        pub opponent_cards: [Option<Card>; 7],
    }
    pub type RankListener<T> = fn(&mut T, CardRank);

    const RAZZ_CARD_IN_HAND_COUNT: u8 = 7;

    fn get_razz_rank(hand: &mut CardHand) -> CardRank {
        // Dedupe consecutive equal ranks (hand is sorted ascending by rank).
        // We do this by iterating and removing duplicates.
        let mut prev: Option<CardRank> = None;
        let mut pos: u64 = 0;
        // Use iterate_hand with a closure-like approach: we can't capture state
        // in a fn pointer, so we implement dedup manually via repeated passes.
        // Instead, collect ranks by iterating with a stateless fn that records
        // into a thread-local is overkill; simpler: use remove_from_hand logic.
        // We'll do a manual dedup by scanning and removing.
        let _ = (&mut prev, &mut pos);

        // Collect current cards in order.
        let mut ranks: Vec<CardRank> = Vec::new();
        {
            // Use a stateless iterator that pushes into a thread-local? No.
            // Instead, we rely on get_max_rank_of_hand and count. But dedup needs
            // the ordered list. We can iterate with a fn that does nothing and
            // instead reconstruct via a helper on CardHand. Since CardHand doesn't
            // expose its cards, we use iterate_hand with a fn that removes
            // duplicates using a static-like thread-local.
            // Simplest correct approach: use a thread-local to accumulate.
            RANK_ACC.with(|acc| acc.borrow_mut().clear());
            hand.iterate_hand(collect_rank);
            RANK_ACC.with(|acc| {
                ranks = acc.borrow().clone();
            });
        }

        // Dedupe consecutive equal ranks.
        let mut deduped: Vec<CardRank> = Vec::new();
        for r in ranks {
            if deduped.last() != Some(&r) {
                deduped.push(r);
            }
        }

        if deduped.len() < 5 {
            return CardRank::InvalidRank;
        }

        // The 5th-lowest distinct rank (index 4).
        deduped[4]
    }

    use std::cell::RefCell;
    thread_local! {
        static RANK_ACC: RefCell<Vec<CardRank>> = RefCell::new(Vec::new());
    }

    fn collect_rank(_len: u64, _pos: u64, c: &Option<Card>) -> crate::card::card::ItrAction {
        if let Some(card) = c {
            RANK_ACC.with(|acc| acc.borrow_mut().push(card.get_card_rank()));
        }
        crate::card::card::ItrAction::Continue
    }

    pub fn simulate_razz_game<T>(decided_cards: &DecidedCards, game_count: u64, arg: &mut T, listener: RankListener<T>) -> i32 {
        let mut my_hand = match CardHand::create_hand(RAZZ_CARD_IN_HAND_COUNT, crate::card::card::sort_card_by_rank) {
            Some(h) => h,
            None => return 1,
        };
        for _ in 0..game_count {
            let mut deck = match CardDeck::create_shuffled_deck() {
                Some(d) => d,
                None => return 1,
            };
            strip_deck(&mut deck, decided_cards);
            complete_hand(&mut my_hand, decided_cards, &mut deck);
            let rank = get_razz_rank(&mut my_hand);
            listener(arg, rank);
            my_hand.reset_hand();
        }
        0
    }

    pub fn strip_deck(deck: &mut CardDeck, decided_cards: &DecidedCards) {
        let my_end = (decided_cards.my_card_count as usize).min(3);
        for i in 0..my_end {
            if let Some(card) = decided_cards.my_cards[i] {
                deck.strip_card_from_deck(card.get_card_suit_rank());
            }
        }
        let opp_end = (decided_cards.opponent_card_count as usize).min(7);
        for i in 0..opp_end {
            if let Some(card) = decided_cards.opponent_cards[i] {
                deck.strip_card_from_deck(card.get_card_suit_rank());
            }
        }
    }

    pub fn complete_hand(my_hand: &mut CardHand, decided_cards: &DecidedCards, deck: &mut CardDeck) {
        let my_end = (decided_cards.my_card_count as usize).min(3);
        for i in 0..my_end {
            my_hand.insert_into_hand(&decided_cards.my_cards[i]);
        }
        let end = RAZZ_CARD_IN_HAND_COUNT as usize - my_end;
        for _ in 0..end {
            let c = deck.deal_from_deck();
            my_hand.insert_into_hand(&c);
        }
    }
}
