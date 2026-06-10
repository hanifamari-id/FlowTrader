"""
FlowTrader — Order Flow Pattern Detection (Layer 2)
Detects: Absorption, Initiative Auction, Exhaustion, Book Sweep, Failed Auction.
Based on: orderflow_strategy_full_logic.md Section 3.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from config.settings import (
    ABSORPTION_EFFORT_MIN, ABSORPTION_DELTA_RATIO,
    EXHAUSTION_VOL_DROP, EXHAUSTION_CANDLE_MIN,
    INITIATIVE_DELTA_MIN, INITIATIVE_IMBALANCE_ROWS,
    SWEEP_RESULT_RATIO, SWEEP_EFFORT_MAX,
)
from data.normalizer import (
    BigTrade, FootprintLevel, FootprintCandle, Direction,
    PatternType, OrderBook,
)


# ─── Footprint Construction from Trades ───

def build_footprint_from_trades(
    trades: list[BigTrade],
    candle_open_time: datetime,
    candle_close_time: datetime,
    tick_size: float = 0.01,
) -> FootprintCandle:
    """
    Reconstruct footprint candle from aggTrades.
    Groups trades by price level and computes bid/ask volume per level.
    """
    levels: dict[float, FootprintLevel] = {}

    for trade in trades:
        if trade.timestamp < candle_open_time or trade.timestamp > candle_close_time:
            continue

        price_rounded = round(trade.price / tick_size) * tick_size

        if price_rounded not in levels:
            levels[price_rounded] = FootprintLevel(
                price=price_rounded,
                bid_volume=0,
                ask_volume=0,
            )

        if trade.is_buyer_maker:
            # Aggressive sell → counted as bid_volume (hit the bid)
            levels[price_rounded].bid_volume += trade.volume
        else:
            # Aggressive buy → counted as ask_volume (lifted the ask)
            levels[price_rounded].ask_volume += trade.volume

    # Build footprint candle
    all_prices = sorted(levels.keys())
    if not all_prices:
        return FootprintCandle(
            open_time=candle_open_time,
            close_time=candle_close_time,
            open=0, high=0, low=0, close=0, volume=0, levels={},
        )

    high = max(all_prices)
    low = min(all_prices)

    # Determine open/close from time-ordered trades
    sorted_trades = sorted(trades, key=lambda t: t.timestamp)
    open_price = sorted_trades[0].price if sorted_trades else low
    close_price = sorted_trades[-1].price if sorted_trades else high

    total_delta = sum(l.delta for l in levels.values())
    total_volume = sum(l.total_volume for l in levels.values())

    buying_imbalance = sum(l.ask_volume for l in levels.values()) > sum(l.bid_volume for l in levels.values()) * 1.5
    selling_imbalance = sum(l.bid_volume for l in levels.values()) > sum(l.ask_volume for l in levels.values()) * 1.5

    return FootprintCandle(
        open_time=candle_open_time,
        close_time=candle_close_time,
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        volume=float(total_volume),
        levels=levels,
        total_delta=total_delta,
        buying_imbalance=buying_imbalance,
        selling_imbalance=selling_imbalance,
    )


def build_footprint_candles_from_trades(
    trades: list[BigTrade],
    timeframe_minutes: int = 15,
    tick_size: float = 0.01,
) -> list[FootprintCandle]:
    """Divide trades into timeframe buckets and build footprint for each."""
    if not trades:
        return []

    trades = sorted(trades, key=lambda t: t.timestamp)
    footprints: list[FootprintCandle] = []

    window_start = trades[0].timestamp.replace(second=0, microsecond=0)
    if timeframe_minutes >= 60:
        window_start = window_start.replace(minute=0)
    else:
        window_start = window_start.replace(minute=(window_start.minute // timeframe_minutes) * timeframe_minutes)

    window_end = window_start + timedelta(minutes=timeframe_minutes)
    window_trades: list[BigTrade] = []

    for trade in trades:
        if trade.timestamp < window_end:
            window_trades.append(trade)
        else:
            if window_trades:
                fp = build_footprint_from_trades(window_trades, window_start, window_end, tick_size)
                footprints.append(fp)
            window_start = window_end
            window_end = window_start + timedelta(minutes=timeframe_minutes)
            window_trades = [trade]

    if window_trades:
        fp = build_footprint_from_trades(window_trades, window_start, window_end, tick_size)
        footprints.append(fp)

    return footprints


# ─── Effort vs Result ───

def calculate_effort_result(candle: FootprintCandle, avg_volume: float, avg_range: float) -> dict:
    """
    Effort = volume (how much participants entered)
    Result = range (how far price moved)
    """
    effort_score = candle.volume / avg_volume if avg_volume > 0 else 0
    result_score = candle.range / avg_range if avg_range > 0 else 0

    delta_dir = Direction.LONG if candle.total_delta > 0 else Direction.SHORT
    candle_dir = Direction.LONG if candle.close > candle.open else Direction.SHORT
    is_coherent = delta_dir == candle_dir

    return {
        "effort_score": effort_score,
        "result_score": result_score,
        "delta_direction": delta_dir,
        "candle_direction": candle_dir,
        "is_coherent": is_coherent,
    }


# ─── Absorption Detection ───

def detect_absorption(
    candles: list[FootprintCandle],
    entry_price: float,
    effort_min: int = ABSORPTION_EFFORT_MIN,
    delta_ratio: float = ABSORPTION_DELTA_RATIO,
) -> Optional[dict]:
    """
    Absorption: aggressive orders one way but close opposite way.
    Sellers aggressive but close green = buyers absorbed sellers → LONG signal.
    """
    if len(candles) < effort_min:
        return None

    recent = candles[-effort_min:]

    total_sell_effort = sum(c.volume for c in recent if c.total_delta < 0)
    total_buy_effort = sum(c.volume for c in recent if c.total_delta > 0)

    last = candles[-1]
    last_close_dir = Direction.LONG if last.close > last.open else Direction.SHORT

    # LONG Absorption: sellers aggressive but buyers won (close green)
    if total_sell_effort > total_buy_effort * delta_ratio:
        if last_close_dir == Direction.LONG:
            proximity = abs(last.close - entry_price) / entry_price
            if proximity < 0.01:  # Within 1% of entry level
                return {
                    "pattern": PatternType.ABSORPTION,
                    "direction": Direction.LONG,
                    "signal_price": last.close,
                    "absorbed_side": Direction.SHORT,
                    "effort_count": effort_min,
                    "total_absorbed": total_sell_effort,
                    "confidence": 0.85,
                }

    # SHORT Absorption: buyers aggressive but sellers won (close red)
    if total_buy_effort > total_sell_effort * delta_ratio:
        if last_close_dir == Direction.SHORT:
            proximity = abs(last.close - entry_price) / entry_price
            if proximity < 0.01:
                return {
                    "pattern": PatternType.ABSORPTION,
                    "direction": Direction.SHORT,
                    "signal_price": last.close,
                    "absorbed_side": Direction.LONG,
                    "effort_count": effort_min,
                    "total_absorbed": total_buy_effort,
                    "confidence": 0.85,
                }

    return None


# ─── Initiative Auction Detection ───

def detect_initiative_auction(
    candles: list[FootprintCandle],
    lookback: int = 5,
) -> Optional[dict]:
    """
    Initiative Auction: delta, close, volume all aligned in same direction.
    Momentum/continuation signal, not reversal.
    """
    if len(candles) < lookback:
        return None

    recent = candles[-lookback:]
    last = candles[-1]

    total_buy_vol = sum(max(c.total_delta, 0) for c in recent)
    total_sell_vol = sum(abs(min(c.total_delta, 0)) for c in recent)
    total_vol = total_buy_vol + total_sell_vol

    if total_vol == 0:
        return None

    buy_ratio = total_buy_vol / total_vol
    sell_ratio = total_sell_vol / total_vol

    avg_vol = sum(c.volume for c in recent) / len(recent)
    imbalance_rows = _count_imbalance_rows(last, threshold=3.0)

    # Bullish Initiative
    if (buy_ratio >= INITIATIVE_DELTA_MIN
            and last.close > last.open
            and last.volume >= avg_vol * 0.8
            and imbalance_rows >= INITIATIVE_IMBALANCE_ROWS):
        return {
            "pattern": PatternType.INITIATIVE,
            "direction": Direction.LONG,
            "signal_price": last.close,
            "delta_ratio": buy_ratio,
            "imbalance_rows": imbalance_rows,
            "volume_ratio": last.volume / avg_vol if avg_vol > 0 else 0,
            "confidence": 0.90,
        }

    # Bearish Initiative
    if (sell_ratio >= INITIATIVE_DELTA_MIN
            and last.close < last.open
            and last.volume >= avg_vol * 0.8
            and imbalance_rows >= INITIATIVE_IMBALANCE_ROWS):
        return {
            "pattern": PatternType.INITIATIVE,
            "direction": Direction.SHORT,
            "signal_price": last.close,
            "delta_ratio": sell_ratio,
            "imbalance_rows": imbalance_rows,
            "volume_ratio": last.volume / avg_vol if avg_vol > 0 else 0,
            "confidence": 0.90,
        }

    return None


def _count_imbalance_rows(candle: FootprintCandle, threshold: float = 3.0) -> int:
    """Count price levels where one side dominates."""
    count = 0
    for level in candle.levels.values():
        if level.bid_volume == 0 or level.ask_volume == 0:
            count += 1
        elif level.ask_volume / level.bid_volume >= threshold:
            count += 1
        elif level.bid_volume / level.ask_volume >= threshold:
            count += 1
    return count


# ─── Exhaustion Detection ───

def detect_exhaustion(
    candles: list[FootprintCandle],
    lookback: int = 5,
) -> Optional[dict]:
    """
    Exhaustion: price trending one way but VOLUME DECLINING (divergence).
    Plus contrarian imbalance at the tip.
    """
    if len(candles) < lookback:
        return None

    recent = candles[-lookback:]
    volumes = [c.volume for c in recent]
    closes = [c.close for c in recent]
    deltas = [c.total_delta for c in recent]

    price_trend = Direction.LONG if closes[-1] > closes[0] else Direction.SHORT

    # Declining volume check
    volume_declining = all(volumes[i] > volumes[i + 1] for i in range(len(volumes) - 2))

    # Delta divergence
    mid_idx = max(0, lookback // 2)
    if price_trend == Direction.LONG:
        delta_diverging = deltas[-1] < deltas[mid_idx] * (1 - 0.3)
    else:
        delta_diverging = deltas[-1] > deltas[mid_idx] * (1 + 0.3)

    # Volume drop threshold
    avg_early = sum(volumes[:mid_idx]) / max(mid_idx, 1)
    vol_drop = 1 - (volumes[-1] / avg_early) if avg_early > 0 else 0

    # Contrarian imbalance at tip
    contrarian = _detect_contrarian_imbalance(recent[-1], price_trend)

    if volume_declining and delta_diverging and vol_drop >= EXHAUSTION_VOL_DROP and contrarian:
        reversal = Direction.SHORT if price_trend == Direction.LONG else Direction.LONG
        return {
            "pattern": PatternType.EXHAUSTION,
            "direction": reversal,
            "signal_price": recent[-1].close,
            "candle_count": lookback,
            "volume_drop_pct": vol_drop * 100,
            "has_contrarian": contrarian,
            "confidence": 0.70,
        }

    return None


def _detect_contrarian_imbalance(candle: FootprintCandle, trend: Direction) -> bool:
    """Check if contrarian orders appear at the tip."""
    sorted_levels = sorted(candle.levels.items())
    if not sorted_levels:
        return False

    if trend == Direction.LONG:
        top_20pct = sorted_levels[int(len(sorted_levels) * 0.8):]
        for _, level in top_20pct:
            if level.bid_volume > level.ask_volume * 2:
                return True
    else:
        bottom_20pct = sorted_levels[:int(len(sorted_levels) * 0.2)]
        for _, level in bottom_20pct:
            if level.ask_volume > level.bid_volume * 2:
                return True
    return False


# ─── Book Sweep Detection ───

def detect_book_sweep(
    candle: FootprintCandle,
    avg_volume: float,
    avg_range: float,
) -> Optional[dict]:
    """
    Book Sweep: low effort but high result (wide range).
    Market opens up wide in one direction with little resistance.
    """
    if candle.volume == 0 or avg_volume == 0 or avg_range == 0:
        return None

    effort_ratio = candle.volume / avg_volume
    result_ratio = candle.range / avg_range

    if effort_ratio > SWEEP_EFFORT_MAX:
        return None
    if result_ratio < SWEEP_RESULT_RATIO:
        return None

    direction = Direction.LONG if candle.close > candle.open else Direction.SHORT
    return {
        "pattern": PatternType.BOOK_SWEEP,
        "direction": direction,
        "signal_price": candle.close,
        "effort_ratio": effort_ratio,
        "result_ratio": result_ratio,
        "confidence": 0.75,
    }


# ─── Failed Auction Detection ───

def detect_failed_auction(
    candles: list[FootprintCandle],
    key_level: float,
    direction: Direction,
    tolerance_ticks: int = 2,
) -> Optional[dict]:
    """
    Failed Auction (Fakeout): price breaks level but reverses back.
    High probability reversal setup.
    """
    if len(candles) < 2:
        return None

    last = candles[-1]
    tick = 0.01

    if direction == Direction.LONG:
        # Bull trap: breaks above but closes below
        if (last.high > key_level + tolerance_ticks * tick
                and last.close < key_level
                and last.total_delta < 0):
            return {
                "pattern": PatternType.FAILED_AUCTION,
                "direction": Direction.SHORT,
                "signal_price": last.close,
                "failed_level": key_level,
                "breach_magnitude": last.high - key_level,
                "trap_type": "BULL_TRAP",
                "confidence": 0.95,
            }
    else:
        # Bear trap: breaks below but closes above
        if (last.low < key_level - tolerance_ticks * tick
                and last.close > key_level
                and last.total_delta > 0):
            return {
                "pattern": PatternType.FAILED_AUCTION,
                "direction": Direction.LONG,
                "signal_price": last.close,
                "failed_level": key_level,
                "breach_magnitude": key_level - last.low,
                "trap_type": "BEAR_TRAP",
                "confidence": 0.95,
            }

    return None


# ─── Pattern Priority Router ───

def detect_best_pattern(
    candles: list[FootprintCandle],
    entry_price: float,
    key_level: float,
    direction: Direction,
) -> Optional[dict]:
    """
    Run all pattern detectors in priority order.
    Priority: Failed Auction > Absorption > Exhaustion > Initiative > Book Sweep
    """
    if len(candles) < 2:
        return None

    # 1. Failed Auction (highest confidence)
    failed = detect_failed_auction(candles, key_level, direction)
    if failed:
        return failed

    # 2. Absorption
    absorption = detect_absorption(candles, entry_price)
    if absorption:
        return absorption

    # 3. Exhaustion
    exhaustion = detect_exhaustion(candles)
    if exhaustion and exhaustion["direction"] == direction:
        return exhaustion

    # 4. Initiative
    initiative = detect_initiative_auction(candles)
    if initiative and initiative["direction"] == direction:
        return initiative

    # 5. Book Sweep
    if len(candles) >= 5:
        avg_vol = sum(c.volume for c in candles[-5:]) / 5
        avg_range = sum(c.range for c in candles[-5:]) / 5
        sweep = detect_book_sweep(candles[-1], avg_vol, avg_range)
        if sweep and sweep["direction"] == direction:
            return sweep

    return None
