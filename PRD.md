# FlowTrader — Order Flow Trading Agent

> **For agentic workers:** Use subagent-driven-development or execute task-by-task inline.

**Goal:** Build a trading agent that generates order flow-based trade signals on Binance Futures (XAUUSDT, QQQUSDT, SPYUSDT, WTIUSDT) with paper trading capability. Multi-timeframe: H4 (bias) → H1 (zone) → M15 (entry).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        FLOWTRADER SYSTEM                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐        │
│  │   H4 TF     │    │   H1 TF      │    │   M15 TF     │        │
│  │  Daily Bias │    │ Entry Zones  │    │  Entry Timing│        │
│  │ Volume Prof │    │ Key Levels   │    │  Order Flow  │        │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘        │
│         │                   │                    │               │
│         └───────────────────┼────────────────────┘               │
│                             ▼                                    │
│                   ┌──────────────────┐                          │
│                   │   SIGNAL ENGINE   │                          │
│                   │  (Pattern Detect) │                          │
│                   └────────┬─────────┘                          │
│                            │                                     │
│                   ┌────────▼─────────┐                          │
│                   │  SCORING AGGREGATOR │                        │
│                   │  Score ≥ 0.80     │                          │
│                   └────────┬─────────┘                          │
│                            │                                     │
│         ┌──────────────────┼──────────────────┐                │
│         ▼                  ▼                  ▼                 │
│  ┌────────────┐    ┌──────────────┐    ┌────────────┐           │
│  │  PAPER     │    │  TELEGRAM    │    │  DASHBOARD │           │
│  │  TRADER    │    │  NOTIFIER    │    │   (local)  │           │
│  └────────────┘    └──────────────┘    └────────────┘           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

DATA FLOW:
Binance Futures Testnet
    → REST API (klines, aggTrades) → Data Fetcher (scheduled)
    → WebSocket (real-time trades) → Big Trade Filter
    → Engine: Volume Profile → Order Flow → Big Trade → Signal
    → Output: Signal → Paper Trade + Telegram Alert
```

---

## Tech Stack

| Component | Library |
|-----------|---------|
| Language | Python 3.10+ |
| Data Fetch | `python-binance` (REST), `websockets` (real-time) |
| Data Storage | `pandas` + `sqlite` |
| Calculation | `numpy`, `pandas` |
| Config | `python-dotenv` |
| Scheduling | `APScheduler` |
| Notifications | Telegram Bot API (native `requests`) |
| Process Manager | `systemd` service |

---

## Project Structure

```
/home/ubuntu/projects/flowtrader/
├── config/
│   ├── __init__.py
│   ├── settings.py          # All configurable parameters
│   └── pairs.py             # Trading pair configs
├── data/
│   ├── __init__.py
│   ├── fetcher.py           # Binance REST API fetcher
│   ├── websocket.py         # Real-time trade stream
│   ├── storage.py            # SQLite persistence
│   └── normalizer.py         # Normalize raw data → Tick, Candle
├── engine/
│   ├── __init__.py
│   ├── volume_profile.py     # Layer 1: Volume Profile Engine
│   ├── orderflow.py          # Layer 2: Pattern Detection
│   ├── big_trade.py          # Layer 3: Big Trade Filter
│   ├── scoring.py            # Signal Aggregator & Scoring
│   └── engine.py             # Master pipeline orchestrator
├── execution/
│   ├── __init__.py
│   ├── paper_trader.py       # Paper trading logic
│   ├── risk_manager.py        # Position sizing, SL/TP calc
│   └── order_tracker.py       # Track open positions
├── notifier/
│   ├── __init__.py
│   └── telegram.py           # Telegram signal alerts
├── dashboard/
│   ├── __init__.py
│   └── viewer.py             # Local signal/status viewer
├── main.py                   # Entry point
├── requirements.txt
├── .env.example
└── README.md
```

---

## Configuration

### Trading Pairs & Parameters

```python
# pairs.py
PAIRS = {
    "XAUUSDT": {
        "tick_size": 0.01,          # Gold price precision
        "min_qty": 0.001,           # Min contract size
        "BIG_TRADE_MIN_LOTS": 10,   # Adjusted for gold
        "session": "24h",            # Gold trades 24h
        "timeframes": ["4h", "1h", "15m"]
    },
    "QQQUSDT": {
        "tick_size": 0.01,
        "min_qty": 0.01,
        "BIG_TRADE_MIN_LOTS": 50,
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"]
    },
    "SPYUSDT": {
        "tick_size": 0.01,
        "min_qty": 0.01,
        "BIG_TRADE_MIN_LOTS": 50,
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"]
    },
    "WTIUSDT": {
        "tick_size": 0.01,
        "min_qty": 0.01,
        "BIG_TRADE_MIN_LOTS": 50,
        "session": "24h",
        "timeframes": ["4h", "1h", "15m"]
    }
}
```

### Core Strategy Parameters

```python
# settings.py — dari document strategy
VALUE_AREA_PCT         = 0.68
STRONG_DELTA_THRESHOLD = 0.65
INITIATIVE_DELTA_MIN   = 0.60
BIG_TRADE_MIN_LOTS     = 50          # default, override per pair
BIG_TRADE_CLUSTER_GAP  = 3           # seconds
ABSORPTION_EFFORT_MIN  = 3
EXHAUSTION_VOL_DROP    = 0.40
SWEEP_RESULT_RATIO     = 3.0
SWEEP_EFFORT_MAX       = 0.30

# Scoring weights
WEIGHT_PROFILE_BIAS      = 0.30
WEIGHT_ORDERFLOW_PATTERN = 0.40
WEIGHT_BIG_TRADE         = 0.30
MIN_SCORE_TO_TRADE       = 0.60
MIN_SCORE_HIGH_CONFIDENCE= 0.80

# Paper trading
PAPER_ACCOUNT_BALANCE = 1000.0      # USDT
RISK_PER_TRADE_PCT    = 0.01         # 1% = $10 per trade
MIN_RR_RATIO          = 1.5
```

---

## Data Architecture

### Binance Futures Endpoints (Testnet)

```
Base URL: https://testnet.binance.vision/api

Historical klines:
  GET /fapi/v1/klines?symbol=XAUUSDT&interval=4h&limit=500

AggTrades (for big trade detection):
  GET /fapi/v1/aggTrades?symbol=XAUUSDT&limit=500

WebSocket streams:
  wss://testnet.binance.vision/ws/<symbol>@aggTrade
  wss://testnet.binance.vision/ws/<symbol>@kline_<interval>
```

### Data Normalization

```python
# From raw Binance kline dict → FootprintCandle-like structure
# Raw kline: [open_time, o, h, l, c, v, close_time, ...]
# Normalized to internal Candle dataclass
```

### Footprint Reconstruction from Trades

```python
# Since Binance doesn't provide full order book footprint,
# reconstruct per-candle delta from trade stream:
#
# aggTrade: {price, quantity, is_buyer_maker}
# is_buyer_maker = True → aggressive SELL (taker is seller)
# is_buyer_maker = False → aggressive BUY (taker is buyer)
#
# Build footprint candles by:
# 1. Collecting aggTrades within each M15 candle timeframe
# 2. Grouping by price level (tick_size precision)
# 3. Computing bid_volume (aggressive sells) vs ask_volume (aggressive buys)
```

---

## Signal Output Format

```python
@dataclass
class TradingSignal:
    pair: str
    direction: Literal["LONG", "SHORT"]
    timeframe: str                    # Which TF triggered the signal
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    rr_ratio: float
    total_score: float                # 0.0 - 1.0
    score_breakdown: dict             # L1, L2, L3 scores
    primary_pattern: str              # "FAILED_AUCTION", "ABSORPTION", etc
    confidence: float                 # 0.0 - 1.0
    timestamp: datetime
    key_level_type: str               # "VAL", "LVN", "VAH", etc
```

---

## Telegram Signal Format

```
🟢 LONG SIGNAL — XAUUSDT

⏱ Timeframe: M15 (H1 confirmation ✓, H4 bias ✓)
📍 Entry: $2,451.50
🛡 SL: $2,448.00 (-$3.50, 1.0%)
🎯 TP1: $2,458.00 (+$6.50, 1.9%)
🎯 TP2: $2,465.00 (+$13.50, 3.9%)
📊 R:R = 2.0:1

🔍 Pattern: ABSORPTION (conf: 85%)
📈 Score: 0.82/1.0
  ├─ L1 Profile Bias: 0.30 (P-Shape, POC shifting)
  ├─ L2 Order Flow:   0.34 (Absorption at LVN)
  └─ L3 Big Trade:    0.18 (2 clusters absorbing)

💰 Paper Trade: OPEN
💵 Balance: $1,010.50
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (Foundation)
- Project setup, dependencies, config
- Binance testnet connection
- Data fetcher (REST klines)
- SQLite storage layer
- Basic data structures (Tick, Candle, Profile)

### Phase 2: Volume Profile Engine (Layer 1)
- Build volume profile from klines
- POC, VAH, VAL calculation
- Profile shape classification (P/b/D)
- Daily bias determination
- Key level identification

### Phase 3: Order Flow Patterns (Layer 2)
- Footprint reconstruction from aggTrades
- Delta calculation per candle
- Pattern detectors: Absorption, Initiative, Exhaustion, Book Sweep, Failed Auction
- Pattern priority and confidence scoring

### Phase 4: Big Trade Filter (Layer 3)
- Trade stream aggregation
- Big trade detection (volume threshold)
- Trade clustering (time-based)
- Big trade at level confluence

### Phase 5: Signal Aggregator
- Multi-timeframe alignment (H4→H1→M15)
- Scoring system (L1 30%, L2 40%, L3 30%)
- Signal generation and filtering
- R:R validation

### Phase 6: Paper Trading & Notifications
- Paper trader (simulated fills, P&L tracking)
- Telegram bot for signal alerts
- Position management (SL/TP trail)
- Balance tracking

### Phase 7: Scheduling & Automation
- APScheduler for periodic tasks
- WebSocket real-time trade monitor
- Auto-run pipeline on schedule

---

## Execution Options

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per phase/task, review between phases

**2. Inline Execution** — Execute tasks in this session, batch with checkpoints for review

Which approach?
