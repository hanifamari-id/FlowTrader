"""
FlowTrader — Master Engine
Orchestrates all layers: data fetch → VP → Order Flow → Big Trade → Signal.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from config.pairs import ACTIVE_PAIRS
from data.fetcher import BinanceFetcher
from data.storage import init_db, save_candle, get_candles, save_reflection
from engine.volume_profile import (
    build_volume_profile, get_daily_bias, identify_key_levels,
    find_best_entry_zones,
)
from engine.orderflow import (
    build_footprint_candles_from_trades, detect_best_pattern,
)
from engine.big_trade import filter_big_trades, big_trade_at_level_confluence
from engine.scoring import aggregate_signals
from execution.paper_trader import PaperTrader
from execution.trade_reflector import TradeReflector, ExitReason
from notifier.telegram import send_signal, send_trade_open, send_trade_close, send_reflection, send_status

log = logging.getLogger("flowtrader.engine")


class FlowTraderEngine:
    def __init__(self):
        self.fetcher = BinanceFetcher()
        self.paper_trader = PaperTrader()
        self.reflector = TradeReflector()
        self.last_signal_time: dict[str, datetime] = {}
        self.pending_signals: dict[str, dict] = {}  # pair → signal context

    async def run_pair_analysis(self, pair: str) -> Optional[dict]:
        """Full pipeline for one pair across all timeframes."""
        log.info(f"Analyzing {pair}...")

        timeframes = ["4h", "1h", "15m"]
        profiles: dict = {}
        current_prices: dict = {}

        for tf in timeframes:
            candles = self.fetcher.get_historical_klines(pair, tf, days_back=7)
            if len(candles) < 20:
                log.warning(f"{pair} {tf}: not enough candles ({len(candles)})")
                return None

            for c in candles:
                await save_candle(c, pair, tf)

            tick = 0.5
            profiles[tf] = build_volume_profile(candles, tick_size=tick)
            current_prices[tf] = candles[-1].close

        h4_profile = profiles["4h"]
        h1_profile = profiles["1h"]
        m15_profile = profiles["15m"]

        h4_bias = get_daily_bias(h4_profile, None, current_prices["4h"])
        h1_bias = get_daily_bias(h1_profile, h4_profile, current_prices["1h"])
        m15_bias = get_daily_bias(m15_profile, h1_profile, current_prices["15m"])

        log.info(f"{pair} — H4:{h4_bias.direction.value} H1:{h1_bias.direction.value} M15:{m15_bias.direction.value}")

        master_bias = h4_bias.direction
        if master_bias.value == "NEUTRAL":
            log.info(f"{pair}: Neutral bias, skipping")
            return None

        key_levels = identify_key_levels([h4_profile, h1_profile], lookback_days=2)
        entry_zones = find_best_entry_zones(
            key_levels, h4_bias, current_prices["15m"], max_distance_pct=1.5
        )

        if not entry_zones:
            log.info(f"{pair}: No entry zones within range")
            return None

        best_zone = entry_zones[0]

        # Fetch aggTrades for M15 order flow
        trades = self.fetcher.get_recent_agg_trades(pair, minutes_back=60)
        if len(trades) < 20:
            log.warning(f"{pair}: Not enough trades ({len(trades)})")
            return None

        footprints = build_footprint_candles_from_trades(trades, timeframe_minutes=15, tick_size=0.5)
        if len(footprints) < 3:
            log.warning(f"{pair}: Not enough footprint candles ({len(footprints)})")
            return None

        pattern_result = detect_best_pattern(
            footprints[-5:],
            entry_price=best_zone.price,
            key_level=best_zone.price,
            direction=master_bias,
        )

        pair_config = self._get_pair_config(pair)
        min_big_trade = pair_config.get("big_trade_min_lots", 10)
        big_clusters = filter_big_trades(trades, min_volume=min_big_trade)
        big_confluence = big_trade_at_level_confluence(big_clusters, best_zone)

        signal = aggregate_signals(
            bias=h4_bias,
            pattern_result=pattern_result,
            big_trade_confluence=big_confluence,
            entry_zone=best_zone,
            profile_vah=h1_profile.vah,
            profile_val=h1_profile.val,
            profile_poc=h1_profile.poc,
        )

        if signal:
            signal.pair = pair
            signal.timeframe = "M15"

            # Rate limit
            last = self.last_signal_time.get(pair)
            if last and (datetime.now() - last).total_seconds() < 1800:
                log.info(f"{pair}: Rate limited")
                return None

            self.last_signal_time[pair] = datetime.now()

            # Store signal context for later reflection
            self.pending_signals[pair] = {
                "signal": signal,
                "pattern": pattern_result,
                "bias": {"direction": h4_bias.direction.value, "strength": h4_bias.strength.value},
                "zone": best_zone,
                "entry_time": datetime.now(),
            }

            trade = self.paper_trader.open_trade(signal)
            send_signal(signal)
            send_trade_open(trade)

            log.info(f"{pair}: SIGNAL TRIGGERED — {signal.direction.value} @ {signal.entry_price:.2f}")
            return {"signal": signal, "trade": trade}

        return None

    def check_open_trades(self, current_prices: dict[str, float]):
        """Check all open trades against current prices. Generate reflection on close."""
        for trade in self.paper_trader.open_trades[:]:
            current_price = current_prices.get(trade.pair)
            if not current_price:
                continue

            prev_pnl = trade.current_pnl
            closed_trades = self.paper_trader.check_and_close(current_price)

            for closed in closed_trades:
                # Determine exit reason
                if closed.status == "CLOSED_SL":
                    exit_reason = ExitReason.SL_HIT
                elif closed.status == "CLOSED_TP2":
                    exit_reason = ExitReason.TP2_HIT
                else:
                    exit_reason = ExitReason.MANUAL_CLOSE

                # Get pending signal context
                ctx = self.pending_signals.pop(closed.pair, None)
                if ctx:
                    duration = (datetime.now() - ctx["entry_time"]).total_seconds() / 60
                    reflection = self.reflector.reflect(
                        trade=closed,
                        exit_price=current_price,
                        exit_reason=exit_reason,
                        entry_signal=ctx,
                        bias_context=ctx.get("bias", {}),
                        duration_minutes=duration,
                    )
                    reflection_text = self.reflector.format_reflection(reflection)
                    send_reflection(reflection_text)
                    asyncio.create_task(save_reflection(reflection))
                    log.info(f"{closed.pair}: Trade closed — {exit_reason.value}, P&L: {closed.current_pnl:.2f}")

    async def run_all(self):
        """Run analysis for all pairs + check open trades."""
        results = {}

        # Get current prices for trade monitoring
        current_prices = {}
        for pair in ACTIVE_PAIRS:
            try:
                candles = self.fetcher.get_klines(pair, "1h", limit=1)
                if candles:
                    current_prices[pair] = candles[-1].close
            except:
                pass

        # Check open trades first
        if self.paper_trader.open_trades:
            self.check_open_trades(current_prices)

        # Run fresh analysis
        for pair in ACTIVE_PAIRS:
            try:
                result = await self.run_pair_analysis(pair)
                results[pair] = result
            except Exception as e:
                log.error(f"{pair}: {e}")
                results[pair] = None

        return results

    def _get_pair_config(self, pair: str) -> dict:
        from config.pairs import PAIRS
        return PAIRS.get(pair, {})
