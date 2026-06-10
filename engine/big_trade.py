"""
FlowTrader — Big Trade Filter (Layer 3)
Filters large trades, clusters them by time, evaluates reward vs absorption.
Based on: orderflow_strategy_full_logic.md Section 4.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from config.settings import BIG_TRADE_CLUSTER_GAP
from data.normalizer import BigTrade, BigTradeCluster, Direction, EntryZone


@dataclass
class LevelConfluence:
    level_price: float
    cluster_count: int
    total_big_volume: int
    dominant_side: Direction
    is_absorbing: bool
    confluence_score: float


def filter_big_trades(
    trades: list[BigTrade],
    min_volume: int = 10,
    cluster_window_sec: int = BIG_TRADE_CLUSTER_GAP,
) -> list[BigTradeCluster]:
    """
    Filter only large trades and cluster those near in time.
    Purpose: follow institutional footprint, ignore retail noise.
    """
    # Filter by volume
    big_trades = [t for t in trades if t.volume >= min_volume]

    if not big_trades:
        return []

    # Sort by time
    big_trades = sorted(big_trades, key=lambda t: t.timestamp)

    # Cluster by time proximity
    clusters: list[BigTradeCluster] = []
    current = BigTradeCluster()
    current.add(big_trades[0])

    for trade in big_trades[1:]:
        delta = (trade.timestamp - current.last_timestamp).total_seconds()
        if delta <= cluster_window_sec:
            current.add(trade)
        else:
            clusters.append(current)
            current = BigTradeCluster()
            current.add(trade)

    clusters.append(current)

    # Finalize clusters
    for cluster in clusters:
        cluster.dominant_side = (
            Direction.LONG if cluster.net_buy_volume > cluster.net_sell_volume
            else Direction.SHORT
        )
        total_vol = sum(t.volume for t in cluster.trades)
        cluster.weighted_avg_price = (
            sum(t.price * t.volume for t in cluster.trades) / total_vol
            if total_vol > 0 else 0
        )

    return clusters


def evaluate_big_trade_result(
    cluster: BigTradeCluster,
    subsequent_candles_close: list[float],
) -> str:
    """
    Evaluate whether big trade got 'reward':
    - BUY → price went up after = INITIATIVE
    - BUY → price didn't go up = ABSORBED by sellers
    """
    if not subsequent_candles_close or not cluster.trades:
        return "UNKNOWN"

    entry_price = cluster.weighted_avg_price
    last_close = subsequent_candles_close[-1]

    if cluster.dominant_side == Direction.LONG:
        move = last_close - entry_price
    else:
        move = entry_price - last_close

    return "REWARD" if move > 0 else "ABSORBED"


def big_trade_at_level_confluence(
    clusters: list[BigTradeCluster],
    entry_zone: EntryZone,
    tolerance_ticks: int = 3,
) -> Optional[LevelConfluence]:
    """
    Check if big trades cluster at or near our entry zone.
    Multiple big trades at one level = level very important to institutions.
    """
    tick = 0.01
    tolerance = tolerance_ticks * tick

    relevant = [
        c for c in clusters
        if abs(c.weighted_avg_price - entry_zone.price) <= tolerance
    ]

    if not relevant:
        return None

    total_vol = sum(c.total_volume for c in relevant)
    buy_vol = sum(c.net_buy_volume for c in relevant)
    sell_vol = sum(c.net_sell_volume for c in relevant)

    dominant = Direction.LONG if buy_vol > sell_vol else Direction.SHORT
    is_absorbing = dominant != entry_zone.direction

    score = len(relevant) * (total_vol / 100)

    return LevelConfluence(
        level_price=entry_zone.price,
        cluster_count=len(relevant),
        total_big_volume=total_vol,
        dominant_side=dominant,
        is_absorbing=is_absorbing,
        confluence_score=min(score, 1.0),
    )


def get_big_trade_summary(clusters: list[BigTradeCluster]) -> dict:
    """Summary of recent big trade activity."""
    if not clusters:
        return {"count": 0, "buy_vol": 0, "sell_vol": 0, "dominant": "NONE"}

    total_buy = sum(c.net_buy_volume for c in clusters)
    total_sell = sum(c.net_sell_volume for c in clusters)
    dominant = "BUY" if total_buy > total_sell else "SELL"

    return {
        "count": len(clusters),
        "buy_vol": total_buy,
        "sell_vol": total_sell,
        "dominant": dominant,
        "total_volume": total_buy + total_sell,
    }
