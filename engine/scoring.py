"""
FlowTrader — Signal Aggregator & Scoring Engine
Combines all 3 layers into final trading decision.
Based on: orderflow_strategy_full_logic.md Sections 5 & 6.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config.settings import (
    WEIGHT_PROFILE_BIAS, WEIGHT_ORDERFLOW_PATTERN, WEIGHT_BIG_TRADE,
    MIN_SCORE_TO_TRADE, MIN_SCORE_HIGH_CONFIDENCE,
    MIN_RR_RATIO, RISK_PER_TRADE_PCT,
)
from config.pairs import PAIRS
from data.normalizer import (
    Bias, Direction, BiasStrength, TradeDecision, TradingSignal,
    OpenTrade, LevelType, EntryZone,
)
from engine.volume_profile import get_daily_bias, build_volume_profile
from engine.big_trade import big_trade_at_level_confluence, LevelConfluence


# ─── Pattern Score Mapping ───

PATTERN_SCORES = {
    "FAILED_AUCTION": 0.95,
    "ABSORPTION": 0.85,
    "INITIATIVE": 0.90,
    "EXHAUSTION": 0.70,
    "BOOK_SWEEP": 0.75,
}


# ─── Trade Levels Calculator ───

def calculate_trade_levels(
    entry_price: float,
    direction: Direction,
    profile_val: float,
    profile_vah: float,
    profile_poc: float,
    tick_size: float = 0.01,
) -> dict:
    """
    Calculate SL, TP1, TP2 based on entry price and profile levels.
    """
    buffer = tick_size * 2  # 2-tick buffer for SL

    if direction == Direction.LONG:
        sl = entry_price - buffer * 3
        tp1 = profile_vah
        tp2 = tp1 + (profile_vah - profile_val) * 0.5
        tp3 = profile_vah + (profile_vah - profile_val) * 0.8
    else:
        sl = entry_price + buffer * 3
        tp1 = profile_val
        tp2 = tp1 - (profile_vah - profile_val) * 0.5
        tp3 = profile_val - (profile_vah - profile_val) * 0.8

    risk = abs(entry_price - sl)
    rr_tp1 = abs(tp1 - entry_price) / risk if risk > 0 else 0

    return {
        "entry": entry_price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": risk,
        "rr_tp1": rr_tp1,
    }


# ─── Signal Aggregator ───

def aggregate_signals(
    bias: Bias,
    pattern_result: Optional[dict],
    big_trade_confluence: Optional[LevelConfluence],
    entry_zone: EntryZone,
    profile_vah: float,
    profile_val: float,
    profile_poc: float,
) -> Optional[TradingSignal]:
    """
    Combine all 3 layers into final trading decision with score.
    Returns None if score < MIN_SCORE_TO_TRADE.
    """
    if pattern_result is None:
        return None

    total_score = 0.0
    breakdown = {}

    # Layer 1: Profile Bias (30%)
    if bias.direction == pattern_result["direction"]:
        l1 = 1.0 if bias.strength == BiasStrength.STRONG else 0.6
    else:
        l1 = 0.0  # Bias contradicts pattern = no trade
    breakdown["L1_profile_bias"] = l1 * WEIGHT_PROFILE_BIAS
    total_score += breakdown["L1_profile_bias"]

    # Layer 2: Order Flow Pattern (40%)
    pattern_name = pattern_result.get("pattern", "").value if hasattr(pattern_result.get("pattern", ""), "value") else str(pattern_result.get("pattern", ""))
    pattern_score = PATTERN_SCORES.get(pattern_name, 0.5)
    l2 = pattern_score * pattern_result.get("confidence", 0.5)
    breakdown["L2_orderflow"] = l2 * WEIGHT_ORDERFLOW_PATTERN
    total_score += breakdown["L2_orderflow"]

    # Layer 3: Big Trade Filter (30%)
    if big_trade_confluence:
        if big_trade_confluence.is_absorbing:
            l3 = min(big_trade_confluence.cluster_count / 3.0, 1.0)
        else:
            l3 = 0.3  # Present but not absorbing
    else:
        l3 = 0.0  # No big trade confirmation
    breakdown["L3_big_trade"] = l3 * WEIGHT_BIG_TRADE
    total_score += breakdown["L3_big_trade"]

    # Decision
    if total_score >= MIN_SCORE_HIGH_CONFIDENCE:
        decision = TradeDecision.ENTRY_FULL
        size_mult = 1.0
    elif total_score >= MIN_SCORE_TO_TRADE:
        decision = TradeDecision.ENTRY_HALF
        size_mult = 0.5
    else:
        return None  # Score too low

    # Trade levels
    levels = calculate_trade_levels(
        entry_zone.price,
        pattern_result["direction"],
        profile_val,
        profile_vah,
        profile_poc,
    )

    # R:R check
    if levels["rr_tp1"] < MIN_RR_RATIO:
        return None

    return TradingSignal(
        pair="XAUUSDT",  # Will be overridden per pair
        direction=pattern_result["direction"],
        timeframe="M15",
        entry_price=levels["entry"],
        stop_loss=levels["stop_loss"],
        tp1=levels["tp1"],
        tp2=levels["tp2"],
        tp3=levels["tp3"],
        rr_ratio=levels["rr_tp1"],
        total_score=total_score,
        score_breakdown=breakdown,
        primary_pattern=pattern_name,
        confidence=pattern_result.get("confidence", 0.5),
        timestamp=datetime.now(),
        key_level_type=entry_zone.level_type.value,
        trade_decision=decision,
    )


# ─── Multi-Timeframe Alignment Check ───

def check_multi_tf_alignment(
    h4_bias: Bias,
    h1_bias: Bias,
    m15_bias: Bias,
) -> dict:
    """
    Verify H4 → H1 → M15 alignment.
    All 3 should agree for high-confidence signal.
    """
    biases = [h4_bias.direction, h1_bias.direction, m15_bias.direction]

    all_long = all(d == Direction.LONG for d in biases)
    all_short = all(d == Direction.SHORT for d in biases)

    alignment_score = 1.0 if (all_long or all_short) else 0.5

    return {
        "aligned": all_long or all_short,
        "direction": h4_bias.direction,  # Master direction from H4
        "alignment_score": alignment_score,
        "h4_agrees": h4_bias.direction == h1_bias.direction == m15_bias.direction,
    }


# ─── Position Size Calculator ───

def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = RISK_PER_TRADE_PCT,
    pair: str = "XAUUSDT",
) -> float:
    """
    Calculate position size in contracts based on risk % of account.
    """
    risk_amount = account_balance * risk_pct
    risk_per_contract = abs(entry_price - stop_loss)

    if risk_per_contract == 0:
        return 0.0

    # Get contract size from pair config (default 1 for crypto)
    pair_config = PAIRS.get(pair, {})
    min_qty = pair_config.get("min_qty", 0.001)
    max_position_pct = pair_config.get("max_position_pct", 0.01)

    size = risk_amount / risk_per_contract

    # Apply max position limit
    max_size = account_balance * max_position_pct / entry_price
    size = min(size, max_size)

    # Round to min qty
    size = round(size / min_qty) * min_qty

    return max(size, 0.0)
