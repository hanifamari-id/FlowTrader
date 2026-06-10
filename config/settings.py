"""
FlowTrader — Strategy Parameters
From: orderflow_strategy_full_logic.md
"""

# ─── Volume Profile ───
VALUE_AREA_PCT = 0.68          # 68% volume = value area
POC_MIN_TRANSACTIONS = 5       # Min trades for valid POC
LVN_THRESHOLD_PCT = 0.10      # < 10% of POC volume = LVN
HVN_THRESHOLD_PCT = 0.75       # > 75% of POC volume = HVN

# ─── Delta ───
STRONG_DELTA_THRESHOLD = 0.65  # Delta imbalance ratio > 65% = strong directional
DELTA_DIVERGENCE_PCT = 0.30   # Delta drops > 30% while price moves = exhaustion

# ─── Big Trade ───
BIG_TRADE_MIN_LOTS = 50       # Default min contracts (override per pair)
BIG_TRADE_CLUSTER_GAP = 3     # Seconds — trades within window = one cluster

# ─── Absorption ───
ABSORPTION_EFFORT_MIN = 3     # Min candles before calling absorption
ABSORPTION_DELTA_RATIO = 0.70 # Opposite delta > 70% = absorption confirmed

# ─── Exhaustion ───
EXHAUSTION_VOL_DROP = 0.40    # Volume drops 40% from average = dry-up
EXHAUSTION_CANDLE_MIN = 3     # Min declining volume candles

# ─── Initiative Auction ───
INITIATIVE_DELTA_MIN = 0.60   # Same-direction delta > 60% of total volume
INITIATIVE_IMBALANCE_ROWS = 3 # Min imbalance rows consecutively

# ─── Book Sweep ───
SWEEP_RESULT_RATIO = 3.0      # Candle range > 3x average = high result
SWEEP_EFFORT_MAX = 0.30       # Volume < 30% average = low effort (sweep condition)

# ─── Scoring Weights ───
WEIGHT_PROFILE_BIAS = 0.30
WEIGHT_ORDERFLOW_PATTERN = 0.40
WEIGHT_BIG_TRADE = 0.30

MIN_SCORE_TO_TRADE = 0.60     # Minimum to enter
MIN_SCORE_HIGH_CONFIDENCE = 0.80  # Full size entry

# ─── Trade Management ───
PAPER_ACCOUNT_BALANCE = 1000.0  # USDT
RISK_PER_TRADE_PCT = 0.01       # 1% risk per trade
MIN_RR_RATIO = 1.5              # Minimum risk:reward

# ─── Binance ───
BINANCE_TESTNET = True
BINANCE_BASE_URL = "https://testnet.binance.vision/api"
BINANCE_WS_URL = "wss://testnet.binance.vision/ws"

# ─── Data ───
HISTORICAL_KLINES_LIMIT = 500  # Max per request
LOOKBACK_DAYS = 5              # Days for volume profile history
