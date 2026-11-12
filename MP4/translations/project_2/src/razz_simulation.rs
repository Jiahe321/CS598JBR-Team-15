use crate::card::card::{Card, CardDeck, CardHand, CardRank};
pub mod razz_simulation {
    use super::*;
    use crate::card::card::{sort_card_by_rank, ItrAction};
    use std::cell::RefCell;

    pub const RAZZ_CARD_IN_HAND_COUNT: u8 = 7;

    pub struct DecidedCards {
        pub my_card_count: u8,
        pub my_cards: [Option<Card>; 3],
        pub opponent_card_count: u8,
        pub opponent_cards: [Option<Card>; 7],
    }

    pub type RankListener<T> = fn(&mut T, CardRank);

    thread_local! {
        static RANK_BUFFER: RefCell<Vec<CardRank>> = const { RefCell::new(Vec::new()) };
    }

    fn collect_rank(_len: u64, _pos: u64, c: &Option<Card>) -> ItrAction {
        if let Some(card) = c {
            RANK_BUFFER.with(|buf| buf.borrow_mut().push(card.get_card_rank()));
        }
        ItrAction::Continue
    }

    pub fn simulate_razz_game<T>(decided_cards: &DecidedCards, game_count: u64, arg: &mut T, listener: RankListener<T>) -> i32 {
        let mut my_hand = match CardHand::create_hand(RAZZ_CARD_IN_HAND_COUNT, sort_card_by_rank) {
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
            listener(arg, get_razz_rank(&mut my_hand));
            my_hand.reset_hand();
        }
        0
    }

    fn get_razz_rank(hand: &mut CardHand) -> CardRank {
        RANK_BUFFER.with(|buf| buf.borrow_mut().clear());
        hand.iterate_hand(collect_rank);
        let mut ranks = RANK_BUFFER.with(|buf| buf.borrow().clone());
        // Sort descending by numeric rank value so the best (lowest) razz
        // ranks come last.
        ranks.sort_unstable_by(|a, b| (*b as i32).cmp(&(*a as i32)));
        // Deduplicate keeping the highest occurrence of each rank.
        ranks.dedup();
        if ranks.len() < 5 {
            return CardRank::InvalidRank;
        }
        // The razz hand is the five lowest distinct ranks; the highest of those
        // is the hand's rank.
        ranks[4]
    }

    pub fn strip_deck(deck: &mut CardDeck, decided_cards: &DecidedCards) {
        for i in 0..decided_cards.my_card_count as usize {
            if let Some(card) = decided_cards.my_cards[i] {
                deck.strip_card_from_deck(card.get_card_suit_rank());
            }
        }
        for i in 0..decided_cards.opponent_card_count as usize {
            if let Some(card) = decided_cards.opponent_cards[i] {
                deck.strip_card_from_deck(card.get_card_suit_rank());
            }
        }
    }

    pub fn complete_hand(my_hand: &mut CardHand, decided_cards: &DecidedCards, deck: &mut CardDeck) {
        let end = decided_cards.my_card_count as usize;
        for i in 0..end {
            my_hand.insert_into_hand(&decided_cards.my_cards[i]);
        }
        let remaining = RAZZ_CARD_IN_HAND_COUNT as usize - end;
        for _ in 0..remaining {
            let card = deck.deal_from_deck();
            my_hand.insert_into_hand(&card);
        }
    }
}
