"""
Trading pairs configuration for FlowTrader.
Each pair has instrument-specific parameters.
"""

PAIRS = {
    "XAUUSDT": {
        "symbol": "XAUUSDT",
        "tick_size": 0.01,
        "min_qty": 0.001,
        "big_trade_min_lots": 10,     # Gold is less liquid in crypto, lower threshold
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"],
        "max_position_pct": 0.02,     # 2% max position for gold (high volatility)
    },
    "QQQUSDT": {
        "symbol": "QQQUSDT",
        "tick_size": 0.01,
        "min_qty": 0.01,
        "big_trade_min_lots": 50,
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"],
        "max_position_pct": 0.01,     # 1% max position
    },
    "SPYUSDT": {
        "symbol": "SPYUSDT",
        "tick_size": 0.01,
        "min_qty": 0.01,
        "big_trade_min_lots": 50,
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"],
        "max_position_pct": 0.01,
    },
    "CLUSDT": {
        "symbol": "CLUSDT",
        "tick_size": 0.01,
        "min_qty": 0.01,
        "big_trade_min_lots": 50,
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"],
        "max_position_pct": 0.01,
    },
}

# Master list of active pairs
ACTIVE_PAIRS = ["XAUUSDT", "QQQUSDT", "SPYUSDT", "CLUSDT"]

# Timeframe priority for multi-TF analysis
TF_PRIORITY = {
    "4h": 1,   # Daily bias
    "1h": 2,   # Entry zone
    "15m": 3,  # Entry timing
}
