"""
FlowTrader — Trade Reflection / After-Action Review
Captures and analyzes the outcome of each trade execution.
Triggers after a trade closes for learning & analysis.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum

from data.normalizer import OpenTrade, Direction


class ExitReason(Enum):
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    SL_HIT = "SL_HIT"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    TIMEOUT = "TIMEOUT"


@dataclass
class TradeReflection:
    """After-action review for a closed trade."""
    id: str
    pair: str
    direction: Direction
    entry_price: float
    exit_price: float
    stop_loss: float
    tp1: float
    tp2: float

    # Entry quality
    entry_score: float          # 0-1, how good was entry price relative to signal
    entry_slippage_pct: float   # slippage from signal price to actual

    # Trade outcome
    pnl: float
    pnl_pct: float              # P&L as % of balance at entry
    exit_reason: ExitReason
    duration_minutes: float

    # Pattern info at entry
    primary_pattern: str
    pattern_confidence: float

    # Context
    bias_direction: str
    entry_time: datetime
    exit_time: datetime

    # Score breakdown at entry
    score_L1: float
    score_L2: float
    score_L3: float
    total_score: float

    # Lessons / flags
    lessons: list[str] = field(default_factory=list)
    was_rate_limited: bool = False


class TradeReflector:
    """
    Generates reflection after each trade closes.
    Analyzes what went right/wrong and logs lessons.
    """

    def reflect(
        self,
        trade: OpenTrade,
        exit_price: float,
        exit_reason: ExitReason,
        entry_signal: dict,          # The signal dict from engine
        bias_context: dict,          # Bias info at entry time
        duration_minutes: float,
    ) -> TradeReflection:
        """Generate a full after-action review for a closed trade."""

        # P&L calculation
        if trade.direction == Direction.LONG:
            pnl = (exit_price - trade.entry_price) * trade.position_size
        else:
            pnl = (trade.entry_price - exit_price) * trade.position_size

        # Entry slippage
        signal_price = entry_signal.get("signal", {}).get("entry_price", trade.entry_price)
        slippage_pct = abs(exit_price - signal_price) / signal_price if signal_price else 0

        # Entry score
        entry_score = self._score_entry(trade, entry_signal, bias_context)

        # Generate lessons
        lessons = self._generate_lessons(
            trade, exit_price, exit_reason, entry_score, pnl,
            entry_signal, bias_context
        )

        # Score breakdown from signal
        sb = entry_signal.get("signal", {}).get("score_breakdown", {})

        reflection = TradeReflection(
            id=str(uuid.uuid4())[:8],
            pair=trade.pair,
            direction=trade.direction,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            stop_loss=trade.stop_loss,
            tp1=trade.tp1,
            tp2=trade.tp2,
            entry_score=entry_score,
            entry_slippage_pct=slippage_pct,
            pnl=pnl,
            pnl_pct=(pnl / 1000) * 100,  # relative to $1000
            exit_reason=exit_reason,
            duration_minutes=duration_minutes,
            primary_pattern=entry_signal.get("pattern", {}).get("pattern", "UNKNOWN"),
            pattern_confidence=entry_signal.get("pattern", {}).get("confidence", 0.0),
            bias_direction=bias_context.get("direction", "NEUTRAL"),
            entry_time=trade.open_time,
            exit_time=datetime.now(),
            score_L1=sb.get("L1_profile_bias", 0.0),
            score_L2=sb.get("L2_orderflow", 0.0),
            score_L3=sb.get("L3_big_trade", 0.0),
            total_score=entry_signal.get("signal", {}).get("total_score", 0.0),
            lessons=lessons,
        )

        return reflection

    def _score_entry(
        self,
        trade: OpenTrade,
        entry_signal: dict,
        bias_context: dict,
    ) -> float:
        """Score 0-1 how well the entry was executed."""
        score = 0.5

        # Good entry: within 0.2% of signal price
        signal_price = entry_signal.get("signal", {}).get("entry_price", trade.entry_price)
        diff = abs(trade.entry_price - signal_price) / signal_price if signal_price else 1.0
        if diff < 0.001:
            score += 0.2
        elif diff < 0.005:
            score += 0.1

        # Pattern confidence bonus
        conf = entry_signal.get("pattern", {}).get("confidence", 0.5)
        score += conf * 0.2

        # Score alignment bonus
        total = entry_signal.get("signal", {}).get("total_score", 0.5)
        score += total * 0.1

        return min(score, 1.0)

    def _generate_lessons(
        self,
        trade: OpenTrade,
        exit_price: float,
        exit_reason: ExitReason,
        entry_score: float,
        pnl: float,
        entry_signal: dict,
        bias_context: dict,
    ) -> list[str]:
        """Auto-generate lessons from trade outcome."""
        lessons = []

        # Entry quality
        if entry_score < 0.5:
            lessons.append("Entry quality poor — consider waiting for better order flow")
        elif entry_score > 0.8:
            lessons.append("Excellent entry — good patience at zone")

        # P&L feedback
        if pnl > 0:
            lessons.append(f"Profitable trade ({pnl:.2f} USDT)")
        else:
            lessons.append(f"Loss ({pnl:.2f} USDT)")

        # Exit reason
        if exit_reason == ExitReason.SL_HIT:
            lessons.append("SL hit — check if stop was too tight for timeframe volatility")
        elif exit_reason == ExitReason.TP2_HIT:
            lessons.append("Full target hit — strong trend continuation")
        elif exit_reason == ExitReason.TP1_HIT:
            lessons.append("TP1 hit — partial exit, check if TP2 was realistic")

        # Score feedback
        total = entry_signal.get("signal", {}).get("total_score", 0.0)
        if total < 0.65 and pnl > 0:
            lessons.append("Won with low score — lucky or signal missed context")
        elif total >= 0.80 and pnl < 0:
            lessons.append("High confidence signal lost — abnormal market condition")

        # Bias alignment
        bias_dir = bias_context.get("direction", "NEUTRAL")
        if trade.direction.value != bias_dir:
            lessons.append(f"Trade against master bias ({bias_dir}) — higher risk")

        # Pattern feedback
        pattern = entry_signal.get("pattern", {}).get("pattern", "UNKNOWN")
        if pattern == "ABSORPTION" and pnl > 0:
            lessons.append("Absorption pattern paid off — watch for these")
        elif pattern == "FAILED_AUCTION" and pnl < 0:
            lessons.append("Failed auction failed — check if level was correct")

        # Duration
        if trade.direction == Direction.LONG and exit_price < trade.entry_price:
            lessons.append("Long but price dropped — macro headwind?")

        if not lessons:
            lessons.append("Standard execution — no major lessons")

        return lessons

    def format_reflection(self, r: TradeReflection) -> str:
        """Format reflection as readable string for Telegram/log."""
        icon = "✅" if r.pnl >= 0 else "❌"
        direction = "LONG" if r.direction == Direction.LONG else "SHORT"

        pnl_str = f"+{r.pnl:.2f}" if r.pnl >= 0 else f"{r.pnl:.2f}"
        lessons_text = "\n  • ".join(r.lessons) if r.lessons else "None"

        text = f"""
📝 <b>TRADE REFLECTION</b> — {r.pair}

{icon} {direction} | {r.exit_reason.value}
💰 P&L: {pnl_str} USDT ({r.pnl_pct:.1f}%)
⏱ Duration: {r.duration_minutes:.0f} min

<b>Entry Quality</b>
  Score: {r.entry_score:.0%}
  Slippage: {r.entry_slippage_pct:.3f}%

<b>Signal Score</b>
  Total: {r.total_score:.2f}
  L1 (Profile): {r.score_L1:.2f}
  L2 (Order Flow): {r.score_L2:.2f}
  L3 (Big Trade): {r.score_L3:.2f}

<b>Pattern</b>
  {r.primary_pattern} (conf: {r.pattern_confidence:.0%})

<b>Lessons</b>
  • {lessons_text}
        """.strip()

        return text
