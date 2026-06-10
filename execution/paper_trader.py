"""
FlowTrader — Paper Trader
Simulates trade execution, tracks P&L, manages open positions.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config.settings import PAPER_ACCOUNT_BALANCE, RISK_PER_TRADE_PCT
from data.normalizer import (
    TradingSignal, OpenTrade, Direction, TradeDecision,
)
from data.storage import save_paper_trade, close_paper_trade, get_open_trades, save_balance


class PaperTrader:
    def __init__(self, initial_balance: float = PAPER_ACCOUNT_BALANCE):
        self.balance = initial_balance
        self.equity = initial_balance
        self.open_trades: list[OpenTrade] = []
        self.trade_history: list[OpenTrade] = []

    def open_trade(self, signal: TradingSignal) -> OpenTrade:
        """Open a new paper trade from signal."""
        if signal.trade_decision == TradeDecision.NO_TRADE:
            raise ValueError("Cannot open trade with NO_TRADE decision")

        risk_amount = self.balance * RISK_PER_TRADE_PCT
        risk_per_unit = abs(signal.entry_price - signal.stop_loss)
        position_size = risk_amount / risk_per_unit if risk_per_unit > 0 else 0

        trade = OpenTrade(
            id=str(uuid.uuid4())[:8],
            pair=signal.pair,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            position_size=position_size,
            open_time=datetime.now(),
            current_pnl=0.0,
            status="OPEN",
            tp1_hit=False,
        )

        self.open_trades.append(trade)
        return trade

    def check_and_close(self, current_price: float) -> list[OpenTrade]:
        """Check all open trades against current price, close if SL/TP hit."""
        closed = []

        for trade in self.open_trades[:]:
            pnl = self._calc_pnl(trade, current_price)

            # SL hit
            if trade.direction == Direction.LONG and current_price <= trade.stop_loss:
                trade.status = "CLOSED_SL"
                trade.current_pnl = -self.balance * 0.01
                closed.append(trade)
            elif trade.direction == Direction.SHORT and current_price >= trade.stop_loss:
                trade.status = "CLOSED_SL"
                trade.current_pnl = -self.balance * 0.01
                closed.append(trade)
            # TP1 hit
            elif trade.direction == Direction.LONG and current_price >= trade.tp1 and not trade.tp1_hit:
                trade.tp1_hit = True
                trade.stop_loss = trade.entry_price
                trade.current_pnl = self._calc_pnl(trade, current_price)
            elif trade.direction == Direction.SHORT and current_price <= trade.tp1 and not trade.tp1_hit:
                trade.tp1_hit = True
                trade.stop_loss = trade.entry_price
                trade.current_pnl = self._calc_pnl(trade, current_price)
            # TP2 hit
            elif trade.direction == Direction.LONG and current_price >= trade.tp2:
                trade.status = "CLOSED_TP2"
                trade.current_pnl = self._calc_pnl(trade, current_price)
                closed.append(trade)
            elif trade.direction == Direction.SHORT and current_price <= trade.tp2:
                trade.status = "CLOSED_TP2"
                trade.current_pnl = self._calc_pnl(trade, current_price)
                closed.append(trade)
            else:
                trade.current_pnl = self._calc_pnl(trade, current_price)

        for trade in closed:
            self.open_trades.remove(trade)
            self.balance += trade.current_pnl
            self.trade_history.append(trade)

        return closed

    def _calc_pnl(self, trade: OpenTrade, current_price: float) -> float:
        if trade.direction == Direction.LONG:
            return (current_price - trade.entry_price) * trade.position_size
        else:
            return (trade.entry_price - current_price) * trade.position_size

    def get_status(self) -> dict:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "open_trades": len(self.open_trades),
            "total_trades": len(self.trade_history),
            "winrate": self._winrate(),
        }

    def _winrate(self) -> float:
        closed = [t for t in self.trade_history if "CLOSED" in t.status]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.current_pnl > 0)
        return round(wins / len(closed), 2)
