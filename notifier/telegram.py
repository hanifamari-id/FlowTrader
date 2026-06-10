"""
FlowTrader — Hermes Notifier
Sends signals via Hermes cron output (auto-delivered to Telegram).
Output format matches user-provided template.
"""

from datetime import datetime
from typing import Optional

from data.normalizer import TradingSignal, OpenTrade, Direction, Bias


# ─── Datetime helpers ────────────────────────────────────────────

def _now_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


def _date() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


# ─── Bias helpers ──────────────────────────────────────────────

def _bias_icon(d: Direction) -> str:
    return {"LONG": "🟢", "SHORT": "🔴", "NEUTRAL": "⚪"}.get(d.value, "⚪")


def _bias_str(d: Direction) -> str:
    return d.value


# ─── Score helpers ─────────────────────────────────────────────

def _score_label(score: float) -> str:
    pct = score * 100
    if pct >= 80:
        return f"{pct:.0f}% — ✅ HIGH CONFIDENCE"
    elif pct >= 60:
        return f"{pct:.0f}% — ⚠️ MEDIUM CONFIDENCE"
    else:
        return f"{pct:.0f}% — ❌ LOW CONFIDENCE"


# ─── Market overview ────────────────────────────────────────────

def _market_status(pair: str, bias: Direction) -> str:
    emoji = _bias_icon(bias)
    return f"{emoji} {pair} → {bias.value}"


# ═══════════════════════════════════════════════════════════════
#  NOTIFICATION TEMPLATES
# ═══════════════════════════════════════════════════════════════

def send_analysis(
    results: dict,
    system_message: str = "All systems nominal.",
) -> None:
    """
    📊 FLOWTRADER ANALYSIS — no signal / regular status update.
    Called every 15 min by cron job.
    """
    now = _now_utc()

    # Build per-pair status lines
    pair_lines: list[str] = []
    for pair, result in results.items():
        if result is None or result.get("signal") is None:
            # No signal — show bias if available
            bias_h4 = result.get("bias_h4", None) if result else None
            status_text = result.get("status", "no_data") if result else "no_data"
            status_map = {
                "neutral": "Neutral bias — no trade",
                "no_zone": "No entry zone in range",
                "no_trades": "Insufficient trade data",
                "no_footprint": "Building footprint...",
                "rate_limited": "Rate limited",
                "no_signal": "Analyzed — no entry",
                "no_data": "No data available",
            }
            status = status_map.get(status_text, status_text)
            if bias_h4:
                emoji = _bias_icon(bias_h4)
                pair_lines.append(f"{emoji} {pair} → {bias_h4.value} | {status}")
            else:
                pair_lines.append(f"⚪ {pair} | {status}")
        else:
            sig = result["signal"]
            emoji = _bias_icon(sig.direction)
            pair_lines.append(f"{emoji} {pair} → {sig.direction.value} | Signal: {sig.primary_pattern} ({sig.confidence:.0%})")

    # Ensure all 4 pairs are represented
    all_pairs = ["XAUUSDT", "QQQUSDT", "SPYUSDT", "CLUSDT"]
    existing = [p for p in all_pairs if any(p in line for line in pair_lines)]
    for pair in all_pairs:
        if not any(pair in line for line in pair_lines):
            pair_lines.append(f"⚪ {pair} | No data")

    text = f"""
📊 FLOWTRADER ANALYSIS

Time: {now}

{pair_lines[0]}
{pair_lines[1]}
{pair_lines[2]}
{pair_lines[3]}

Notes
• System running normally
• {system_message}
"""
    print(text.strip())


def send_signal(
    signal: TradingSignal,
    bias_h4: Direction,
    bias_h1: Direction,
    bias_m15: Direction,
) -> None:
    """
    🚨 FLOWTRADER SIGNAL — entry signal triggered.
    """
    now = _now_utc()
    direction_text = signal.direction.value
    direction_icon = _bias_icon(signal.direction)
    score_pct = signal.total_score * 100
    confidence = _score_label(signal.total_score)

    # Parse score breakdown
    l1 = signal.score_breakdown.get("L1_profile_bias", 0.0)
    l2 = signal.score_breakdown.get("L2_orderflow", 0.0)
    l3 = signal.score_breakdown.get("L3_big_trade", 0.0)

    # Risk/Reward
    risk = abs(signal.entry_price - signal.stop_loss)
    reward = abs(signal.tp1 - signal.entry_price)
    rr = reward / risk if risk > 0 else 0

    # Signal checks
    checks = [
        f"✅ Bias aligned: {bias_h4.value}",
        f"✅ Pattern: {signal.primary_pattern} ({signal.confidence:.0%})",
        f"✅ Score: {score_pct:.0f}/100 ({l1:.2f} L1 / {l2:.2f} L2 / {l3:.2f} L3)",
        f"✅ RR: {rr:.1f}:1 | Risk: ${risk:.2f}",
    ]

    text = f"""
🚨 FLOWTRADER SIGNAL

Time: {now}

{direction_icon} {signal.pair}

Market Bias
• H4: {bias_h4.value}
• H1: {bias_h1.value}
• M15: {bias_m15.value}

Orderflow Confirmation
{chr(10).join(checks)}

🎯 TRADE SETUP

Direction: {direction_text}
Entry: {signal.entry_price:.2f}
Stop Loss: {signal.stop_loss:.2f}
TP1: {signal.tp1:.2f}
TP2: {signal.tp2:.2f}
TP3: {signal.tp3:.2f}
Risk: {risk:.2f}
Reward: {reward:.2f}

📊 SIGNAL SCORE

Trend Alignment: {l1:.2f}
Orderflow Quality: {l2:.2f}
Liquidity Context: {l3:.2f}

Confidence Score
{confidence}

Trade Reason
{signal.primary_pattern} detected at {signal.key_level_type} level.
Entry confirmed at {signal.timeframe} timeframe.

🟢 ENTRY TRIGGERED
"""
    print(text.strip())


def send_trade_open(
    trade: OpenTrade,
    bias_h4: Direction,
    bias_h1: Direction,
    bias_m15: Direction,
) -> None:
    """
    🟢 POSITION OPENED — paper trade entered.
    """
    direction_icon = _bias_icon(trade.direction)
    pnl_str = f"+{trade.current_pnl:.2f}" if trade.current_pnl >= 0 else f"{trade.current_pnl:.2f}"

    text = f"""
🟢 POSITION OPENED

{trade.pair}

Direction: {trade.direction.value}
Entry: {trade.entry_price:.2f}
Current PnL: {pnl_str}
Stop Loss: {trade.stop_loss:.2f}
TP1: {trade.tp1:.2f}

Management Rules
• Move SL to Breakeven after TP1
• Close 50% at TP1
• Trail remaining position
• Follow M15 structure

🟢 TRADE ACTIVE
"""
    print(text.strip())


def send_tp1_hit(trade: OpenTrade) -> None:
    """
    🎯 TP1 HIT — first target reached, 50% closed.
    """
    direction_icon = _bias_icon(trade.direction)
    result = f"+{trade.current_pnl:.2f}" if trade.current_pnl >= 0 else f"{trade.current_pnl:.2f}"

    text = f"""
🎯 TP1 HIT

{trade.pair}

Direction: {trade.direction.value}
Entry: {trade.entry_price:.2f}
TP1: {trade.tp1:.2f}
Result: {result}

Position Management
• 50% Position Closed
• SL moved to Breakeven
• Remaining position targeting TP2

🟢 TRADE PROTECTED
"""
    print(text.strip())


def send_tp2_hit(trade: OpenTrade) -> None:
    """
    🎯 TP2 HIT — second target reached.
    """
    direction_icon = _bias_icon(trade.direction)
    result = f"+{trade.current_pnl:.2f}" if trade.current_pnl >= 0 else f"{trade.current_pnl:.2f}"

    text = f"""
🎯 TP2 HIT

{trade.pair}

Direction: {trade.direction.value}
Entry: {trade.entry_price:.2f}
TP2: {trade.tp2:.2f}
Result: {result}

Position Management
• Additional partial close executed
• Trailing stop active
• Remaining position targeting TP3

🟢 RUNNING WINNER
"""
    print(text.strip())


def send_tp3_hit(trade: OpenTrade) -> None:
    """
    🏆 TP3 HIT — full target achieved, trade completed.
    """
    direction_icon = _bias_icon(trade.direction)
    result = f"+{trade.current_pnl:.2f}" if trade.current_pnl >= 0 else f"{trade.current_pnl:.2f}"

    text = f"""
🏆 TP3 HIT — FULL TARGET

{trade.pair}

Direction: {trade.direction.value}
Entry: {trade.entry_price:.2f}
Exit: {trade.tp3:.2f}
Final Result: {result}

🏆 FULL TARGET ACHIEVED
"""
    print(text.strip())


def send_sl_hit(trade: OpenTrade, reflection_text: str = "") -> None:
    """
    ❌ STOP LOSS HIT — trade closed at loss.
    """
    direction_icon = _bias_icon(trade.direction)
    result = f"{trade.current_pnl:.2f}"

    text = f"""
❌ STOP LOSS HIT

{trade.pair}

Direction: {trade.direction.value}
Entry: {trade.entry_price:.2f}
Stop Loss: {trade.stop_loss:.2f}
Result: {result}

"""
    if reflection_text:
        text += f"Trade Review\n{reflection_text}\n"

    text += "🔴 TRADE CLOSED"
    print(text.strip())


def send_daily_report(
    date: str,
    signals: int,
    trades: int,
    winners: int,
    losers: int,
    winrate: float,
    net_r: float,
    pair_results: dict,
) -> None:
    """
    📈 DAILY REPORT — end-of-day performance summary.
    """
    wr_str = f"{winrate:.0%}"
    net_r_str = f"+{net_r:.2f}R" if net_r >= 0 else f"{net_r:.2f}R"

    xau = pair_results.get("XAUUSDT", {"trades": 0, "result": "—"})
    qqq = pair_results.get("QQQUSDT", {"trades": 0, "result": "—"})
    spy = pair_results.get("SPYUSDT", {"trades": 0, "result": "—"})
    cl = pair_results.get("CLUSDT", {"trades": 0, "result": "—"})

    text = f"""
📈 DAILY REPORT

Date: {date}

Performance
• Signals Generated: {signals}
• Trades Taken: {trades}
• Winners: {winners}
• Losers: {losers}
• Win Rate: {wr_str}
• Net R Multiple: {net_r_str}

Instrument Breakdown
• XAUUSDT: {xau['trades']} trades | {xau['result']}
• QQQUSDT: {qqq['trades']} trades | {qqq['result']}
• SPYUSDT: {spy['trades']} trades | {spy['result']}
• CLUSDT: {cl['trades']} trades | {cl['result']}

Generated by FlowTrader Engine
"""
    print(text.strip())


def send_status(
    balance: float,
    equity: float,
    open_trades: int,
    winrate: float,
) -> None:
    """
    📊 System status (on-demand).
    """
    text = f"""
📊 FlowTrader Status

Balance: ${balance:,.2f}
Equity: ${equity:,.2f}
Open Trades: {open_trades}
Win Rate: {winrate:.0%}
"""
    print(text.strip())


# ─── Legacy alias ───────────────────────────────────────────────

def send_trade_close(trade: OpenTrade) -> None:
    """Legacy — routes to appropriate TP/SL notification based on status."""
    if "SL" in trade.status or trade.status == "CLOSED_SL":
        send_sl_hit(trade)
    elif trade.status == "CLOSED_TP2" or trade.tp2_hit:
        send_tp2_hit(trade)
    elif trade.tp1_hit:
        send_tp1_hit(trade)
    else:
        send_sl_hit(trade)


def send_reflection(text: str) -> None:
    """After-Action Review output."""
    print(f"\n📝 TRADE REFLECTION\n{text}\n")
