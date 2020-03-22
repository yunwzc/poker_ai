from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from pluribus.poker.actions import Action
from pluribus.poker.card import Card
from pluribus.poker.engine import PokerEngine
from pluribus.poker.table import PokerTable

from player import ShortDeckPokerPlayer


class ShortDeckPokerState:
    """The state of a Short Deck Poker game at some given point in time.

    The class is immutable and new state can be instanciated from once an
    action is applied via the `ShortDeckPokerState.new_state` method.
    """

    def __init__(
        self,
        players: List[ShortDeckPokerPlayer],
        small_blind: int = 50,
        big_blind: int = 100,
    ):
        """Initialise state."""
        # Get a reference of the pot from the first player.
        self._table = PokerTable(players=players, pot=players[0].pot)
        # TODO(fedden): There are an awful lot of layers of abstraction here,
        #               this could be much neater, maybe refactor and clean
        #               things up a bit here in the future.
        # Shorten the deck.
        self._table.dealer.deck._cards = [
            card
            for card in self._table.dealer.deck._cards
            if card.rank_int not in {2, 3, 4, 5, 6, 7, 8, 9}
        ]
        self.small_blind = small_blind
        self.big_blind = big_blind
        self._poker_engine = PokerEngine(
            table=self._table, small_blind=small_blind, big_blind=big_blind
        )
        # Reset the pot, assign betting order to players (might need to remove
        # this), assign blinds to the players.
        self._poker_engine.round_setup()
        # Deal private cards to players.
        self._table.dealer.deal_private_cards(self._table.players)
        # Store the actions as they come in here.
        self._history: List[Action] = []
        self.player_i = 0
        self._betting_stage = "pre_flop"
        self._reset_betting_round_state()

    def apply_action(self, action_str: Optional[str], **kwargs) -> ShortDeckPokerState:
        """Create a new state after applying an action.

        Parameters
        ----------
        action_str : str or None
            The description of the action the current player is making. Can be
            any of {"fold, "call", "raise"}, the latter two only being possible
            if the agent hasn't folded already.
        **kwargs : dict of any
            The key word arguments fed to the players action method, such as
            `n_chips` if the action is rasing.

        Returns
        -------
        new_state : ShortDeckPokerState
            A poker state instance that represents the game in the next
            timestep, after the action has been applied.
        """
        # TODO(fedden): Split this method up it's getting big!
        # Deep copy the parts of state that are needed that must be immutable
        # from state to state.
        new_state = copy.deepcopy(self)
        if action_str is None:
            # Assert active player has folded already.
            assert (
                not new_state.current_player.is_active
            ), "Active player cannot do nothing!"
        elif action_str == "call":
            action = new_state.current_player.call(players=self._table.players)
        elif action_str == "fold":
            action = new_state.current_player.fold()
        elif action_str == "raise":
            if "n_chips" not in kwargs:
                raise ValueError("'n_chips' must be specified when action is raise")
            action = new_state.current_player.raise_to(**kwargs)
            new_state._n_raises += 1
        else:
            raise ValueError(
                f"Expected action to be derived from class Action, but found "
                f"type {type(action)}."
            )
        # Update the new state.
        new_state._history.append(action)
        # Player has made move, increment the player that is next.
        new_state.player_i += 1
        if new_state.player_i >= len(self._table.player):
            new_state.player_i = 0
            new_state._all_players_have_made_action = True
        finished_betting = not new_state._poker_engine.more_betting_needed
        if new_state._poker_engine.n_players_with_moves == 0:
            # No players left.
            new_state._betting_stage = "terminal"
        elif new_state._all_players_have_made_action and finished_betting:
            # We have done atleast one full round of betting, increment stage
            # of the game.
            new_state._increment_stage()
        # Now check if the game is terminal.
        if new_state._betting_stage in {"terminal", "show_down"}:
            # Distribute winnings.
            new_state._poker_engine.compute_winners()
        return new_state

    def _reset_betting_round_state(self):
        """Reset the state related to counting types of actions."""
        self._all_players_have_made_action = False
        self._n_raises = 0

    def _increment_stage(self):
        """Once betting has finished, increment the stage of the poker game."""
        # All players must bet.
        self._reset_betting_round_state()
        # Progress the stage of the game.
        if self._betting_stage == "pre_flop":
            # Progress from private cards to the flop.
            self._betting_stage = "flop"
            self._engine.table.dealer.deal_flop(self._table)
        elif self._betting_stage == "flop":
            # Progress from flop to turn.
            self._betting_stage = "turn"
            self._engine.table.dealer.deal_turn(self._table)
        elif self._betting_stage == "turn":
            # Progress from turn to river.
            self._betting_stage = "river"
            self._engine.table.dealer.deal_river(self._table)
        elif self._betting_stage == "river":
            # Progress to the showdown.
            self._betting_stage = "show_down"
        else:
            raise ValueError(f"Unknown betting_stage: {self._betting_stage}")

    @property
    def is_terminal(self) -> bool:
        """Returns whether this state is terminal or not.

        The state is terminal once all rounds of betting are complete and we
        are at the show down stage of the game or if all players have folded.
        """
        return self._betting_stage in {"show_down", "terminal"}

    @property
    def current_player(self) -> ShortDeckPokerPlayer:
        """Returns a reference to player that makes a move for this state."""
        return self._table.players[self.player_i]

    @property
    def legal_actions(self) -> List[Optional[Dict[str, Any]]]:
        """Return the actions that are legal for this game state."""
        actions: List[Optional[Dict[str, Any]]] = []
        if self.current_player.is_active:
            if self._betting_stage in {"pre_flop", "flop"}:
                bet_size = self.small_blind
            else:
                bet_size = self.big_blind
            actions += [
                dict(action_str="fold"),
                dict(action_str="call"),
            ]
            if self._n_raises < 3 or self._poker_engine.n_active_players == 2:
                # In limit hold'em we can only bet/raise if there have been
                # less than three raises in this round of betting, or if there
                # are two players playing.
                actions += [dict(action_str="raise", n_chips=bet_size)]
        else:
            actions += [None]
        return actions

    @property
    def h(self) -> List[Action]:
        """Returns the history."""
        return self._history

    @property
    def rs(self) -> List[List[Card]]:
        """Returns the players hands."""
        return [player.cards for player in self._table.players]

