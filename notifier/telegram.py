"""
FlowTrader — Hermes Notifier
Sends signals via Hermes cron output (auto-delivered to Telegram).
Output format: [SIGNAL], [TRADE_OPEN], [TRADE_CLOSE], [REFLECTION], [STATUS]
"""

import json
from datetime import datetime

from data.normalizer import TradingSignal, OpenTrade, Direction


def _format_signal(signal: TradingSignal) -> str:
    direction_icon = "🟢" if signal.direction == Direction.LONG else "🔴"
    direction_text = "LONG" if signal.direction == Direction.LONG else "SHORT"
    score_pct = signal.total_score * 100
    rr = signal.rr_ratio

    text = f"""
{direction_icon} <b>{direction_text} SIGNAL</b> — {signal.pair}

⏱ Timeframe: {signal.timeframe}
📍 Entry: {signal.entry_price:.2f}
🛡 SL: {signal.stop_loss:.2f}
🎯 TP1: {signal.tp1:.2f}
🎯 TP2: {signal.tp2:.2f}
📊 R:R = {rr:.1f}:1

🔍 Pattern: {signal.primary_pattern} (conf: {signal.confidence:.0%})
📈 Score: {score_pct:.0f}/100
  ├─ L1 Profile: {signal.score_breakdown.get("L1_profile_bias", 0):.2f}
  ├─ L2 Order Flow: {signal.score_breakdown.get("L2_orderflow", 0):.2f}
  └─ L3 Big Trade: {signal.score_breakdown.get("L3_big_trade", 0):.2f}

💰 Level: {signal.key_level_type}
⏰ {signal.timestamp.strftime("%H:%M:%S")}
    """.strip()
    return f"[SIGNAL]\n{text}"


def _format_trade_open(trade: OpenTrade) -> str:
    direction_icon = "🟢" if trade.direction == Direction.LONG else "🔴"
    text = f"""
{direction_icon} <b>TRADE OPEN</b> — {trade.pair}
ID: {trade.id}
Direction: {trade.direction.value}
Entry: {trade.entry_price:.2f}
SL: {trade.stop_loss:.2f}
TP1: {trade.tp1:.2f} | TP2: {trade.tp2:.2f}
Size: {trade.position_size:.4f}
    """.strip()
    return f"[TRADE_OPEN]\n{text}"


def _format_trade_close(trade: OpenTrade) -> str:
    icon = "✅" if "TP" in trade.status else "❌"
    pnl = trade.current_pnl
    pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
    text = f"""
{icon} <b>TRADE CLOSED</b> — {trade.pair}
ID: {trade.id}
Status: {trade.status}
P&L: {pnl_str} USDT
Entry: {trade.entry_price:.2f}
Close time: {datetime.now().strftime("%H:%M:%S")}
    """.strip()
    return f"[TRADE_CLOSE]\n{text}"


def _format_reflection(text: str) -> str:
    return f"[REFLECTION]\n{text}"


def _format_status(balance: float, equity: float, open_trades: int, winrate: float) -> str:
    text = f"""
📊 <b>FlowTrader Status</b>
Balance: ${balance:,.2f}
Equity: ${equity:,.2f}
Open Trades: {open_trades}
Win Rate: {winrate:.0%}
    """.strip()
    return f"[STATUS]\n{text}"


def send_signal(signal: TradingSignal) -> None:
    print(_format_signal(signal))


def send_trade_open(trade: OpenTrade) -> None:
    print(_format_trade_open(trade))


def send_trade_close(trade: OpenTrade) -> None:
    print(_format_trade_close(trade))


def send_reflection(text: str) -> None:
    print(_format_reflection(text))


def send_status(balance: float, equity: float, open_trades: int, winrate: float) -> None:
    print(_format_status(balance, equity, open_trades, winrate))
