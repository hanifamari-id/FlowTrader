# FlowTrader

Order flow trading signal generator + paper trading.

**Pairs:** XAUUSDT, QQQUSDT, SPYUSDT, CLUSDT
**Network:** Binance Futures (mainnet, public API — no API key needed)
**Paper balance:** $1000 USDT

## Setup

```bash
cd /home/ubuntu/projects/flowtrader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source venv/bin/activate
python main.py              # Run engine (auto every 15 min)
python main.py --reflect    # View trade reflection history
python main.py --status     # View open trades + balance
```

## Output

Signals printed to stdout, delivered to Telegram via Hermes cron job.

## Project Structure

```
flowtrader/
├── config/           # Strategy params & pair configs
├── data/             # Binance fetcher, SQLite storage
├── engine/           # Volume profile, order flow, big trade, scoring
├── execution/        # Paper trader, trade reflector
├── notifier/         # Hermes stdout notifier
└── main.py           # Entry point (scheduler every 15 min)
```
