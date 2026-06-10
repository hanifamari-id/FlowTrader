"""
FlowTrader — Core Data Structures
Normalizes raw Binance data → internal types.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


# ─── Enums ───

class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class BiasStrength(Enum):
    WEAK = "WEAK"
    STRONG = "STRONG"


class ProfileShape(Enum):
    P_SHAPE = "P_SHAPE"           # Bullish — POC > 60% range
    B_SHAPE = "B_SHAPE"           # Bearish — POC < 40% range
    D_SHAPE = "D_SHAPE"           # Neutral — POC 40-60% range
    DOUBLE_DISTRIBUTION = "DD"    # Two distributions


class LevelType(Enum):
    POC = "POC"           # Point of Control — highest volume
    VAH = "VAH"           # Value Area High
    VAL = "VAL"           # Value Area Low
    HVN = "HVN"           # High Volume Node
    LVN = "LVN"           # Low Volume Node
    NEUTRAL = "NEUTRAL"


class PatternType(Enum):
    ABSORPTION = "ABSORPTION"
    INITIATIVE = "INITIATIVE"
    EXHAUSTION = "EXHAUSTION"
    BOOK_SWEEP = "BOOK_SWEEP"
    FAILED_AUCTION = "FAILED_AUCTION"


class TradeDecision(Enum):
    NO_TRADE = "NO_TRADE"
    ENTRY_HALF = "ENTRY_HALF"
    ENTRY_FULL = "ENTRY_FULL"


# ─── Data Classes ───

@dataclass
class Tick:
    """Single trade tick."""
    timestamp: datetime
    price: float
    volume: int
    is_buyer_maker: bool  # True = taker sold (aggressive sell) = bid side
                          # False = taker bought (aggressive buy) = ask side


@dataclass
class Candle:
    """Standard OHLCV candle."""
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int


@dataclass
class FootprintLevel:
    """Single price level in a footprint candle."""
    price: float
    bid_volume: int    # Aggressive sell volume at this level
    ask_volume: int    # Aggressive buy volume at this level

    @property
    def delta(self) -> int:
        return self.ask_volume - self.bid_volume

    @property
    def total_volume(self) -> int:
        return self.bid_volume + self.ask_volume


@dataclass
class FootprintCandle:
    """Candle with per-level volume breakdown."""
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    levels: dict[float, FootprintLevel] = field(default_factory=dict)

    # Computed
    total_delta: int = 0
    buying_imbalance: bool = False
    selling_imbalance: bool = False

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class OrderBookLevel:
    """Single level in order book."""
    price: float
    quantity: float


@dataclass
class OrderBook:
    """Snapshot of order book."""
    timestamp: datetime
    bids: list[OrderBookLevel]  # Sorted desc
    asks: list[OrderBookLevel]  # Sorted asc
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0


@dataclass
class VolumeProfileLevel:
    """Volume at a single price level."""
    price: float
    volume: int
    level_type: LevelType = LevelType.NEUTRAL


@dataclass
class ValueArea:
    high: float
    low: float
    volume: int


@dataclass
class VolumeProfile:
    """Volume profile for a session."""
    levels: dict[float, LevelType]  # price → type
    poc: float
    vah: float
    val: float
    total_volume: int
    shape: ProfileShape


@dataclass
class Bias:
    direction: Direction
    strength: BiasStrength
    key_level: float = 0.0


@dataclass
class KeyLevel:
    price: float
    level_type: LevelType
    strength: int = 1  # How many days confirmed


@dataclass
class EntryZone:
    price: float
    direction: Direction
    level_type: LevelType
    strength: int
    confluence_score: float


@dataclass
class BigTrade:
    timestamp: datetime
    price: float
    volume: int
    side: Literal["BUY", "SELL"]
    is_buyer_maker: bool


@dataclass
class BigTradeCluster:
    """Cluster of big trades within time window."""
    trades: list[BigTrade] = field(default_factory=list)
    dominant_side: Direction = Direction.NEUTRAL
    weighted_avg_price: float = 0.0
    net_buy_volume: int = 0
    net_sell_volume: int = 0

    @property
    def total_volume(self) -> int:
        return self.net_buy_volume + self.net_sell_volume

    @property
    def last_timestamp(self) -> datetime:
        return self.trades[-1].timestamp if self.trades else datetime.min()

    def add(self, trade: BigTrade):
        self.trades.append(trade)
        if trade.side == "BUY":
            self.net_buy_volume += trade.volume
        else:
            self.net_sell_volume += trade.volume


@dataclass
class TradingSignal:
    """Final trading signal output."""
    pair: str
    direction: Direction
    timeframe: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    rr_ratio: float
    total_score: float
    score_breakdown: dict
    primary_pattern: str
    confidence: float
    timestamp: datetime
    key_level_type: str
    trade_decision: TradeDecision = TradeDecision.NO_TRADE


@dataclass
class OpenTrade:
    """Active paper trade."""
    id: str
    pair: str
    direction: Direction
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    position_size: float
    open_time: datetime
    current_pnl: float = 0.0
    status: str = "OPEN"
    tp1_hit: bool = False
    trailing_sl: float = 0.0
