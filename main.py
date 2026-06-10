"""
FlowTrader — Main Entry Point
Run with: python main.py
Options:
  python main.py              — Run scheduled trading engine
  python main.py --reflect    — View trade reflection history
  python main.py --status     — View current balance and open trades
"""

import asyncio
import argparse
import logging
import sys

from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from dotenv import load_dotenv

from data.storage import init_db, get_reflections, get_current_balance
from engine.engine import FlowTraderEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("flowtrader")


async def run_analysis(engine: FlowTraderEngine):
    log.info(f"=== RUNNING ANALYSIS {datetime.now().strftime('%H:%M:%S')} ===")
    try:
        results = await engine.run_all()
        active = sum(1 for v in results.values() if v is not None)
        log.info(f"Analysis complete — {active} signals triggered")
    except Exception as e:
        log.error(f"Analysis failed: {e}")


async def cmd_reflect(pair: str = None):
    """View reflection history."""
    await init_db()
    reflections = await get_reflections(pair=pair, limit=20)

    if not reflections:
        print("No reflections yet — no trades have closed.")
        return

    print(f"\n📝 TRADE REFLECTIONS — {len(reflections)} trades")
    print("=" * 70)

    for r in reflections:
        icon = "✅" if r["pnl"] >= 0 else "❌"
        print(f"\n{icon} {r['pair']} {r['direction']} | {r['exit_reason']}")
        print(f"   Entry: {r['entry']:.4f} → Exit: {r['exit']:.4f}")
        pnl_str = f"+{r['pnl']:.2f}" if r["pnl"] >= 0 else f"{r['pnl']:.2f}"
        print(f"   P&L: {pnl_str} USDT | Score: {r['total_score']:.2f}")
        print(f"   Pattern: {r['pattern']} | Duration: {r['duration_min']:.0f} min")
        if r["lessons"]:
            for l in r["lessons"]:
                print(f"   • {l}")

    # Summary stats
    total = len(reflections)
    wins = sum(1 for r in reflections if r["pnl"] > 0)
    total_pnl = sum(r["pnl"] for r in reflections)
    avg_score = sum(r["total_score"] for r in reflections) / max(total, 1)

    print(f"\n{'=' * 70}")
    print(f"Summary: {wins}/{total} wins ({wins/max(total,1):.0%}) | Net P&L: {total_pnl:+.2f} USDT | Avg Score: {avg_score:.2f}")


async def cmd_status():
    """View current account status."""
    from execution.paper_trader import PaperTrader

    pt = PaperTrader()
    status = pt.get_status()

    print(f"\n📊 FLOWTRADER STATUS")
    print(f"   Balance: ${status['balance']:,.2f}")
    print(f"   Equity:  ${status['equity']:,.2f}")
    print(f"   Open Trades: {status['open_trades']}")
    print(f"   Total Trades: {status['total_trades']}")
    print(f"   Win Rate: {status['winrate']:.0%}")
    if pt.open_trades:
        print(f"\n   Open Positions:")
        for t in pt.open_trades:
            icon = "🟢" if t.direction.value == "LONG" else "🔴"
            print(f"   {icon} {t.pair} {t.direction.value} — Entry: {t.entry_price:.4f} PnL: {t.current_pnl:+.2f}")


async def main():
    load_dotenv()
    await init_db()

    parser = argparse.ArgumentParser(description="FlowTrader")
    parser.add_argument("--reflect", action="store_true", help="View trade reflection history")
    parser.add_argument("--status", action="store_true", help="View current account status")
    parser.add_argument("--pair", type=str, default=None, help="Filter by pair (e.g. XAUUSDT)")
    args = parser.parse_args()

    if args.reflect:
        await cmd_reflect(pair=args.pair)
        return

    if args.status:
        await cmd_status()
        return

    # Default: run scheduled engine
    log.info("FlowTrader initialized")
    engine = FlowTraderEngine()

    await run_analysis(engine)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_analysis,
        IntervalTrigger(minutes=15),
        args=[engine],
        id="flowtrader_analysis",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started — running every 15 minutes")

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
