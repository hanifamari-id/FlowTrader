"""
FlowTrader — Binance Data Fetcher
Fetches klines, aggTrades from Binance Futures Testnet.
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Optional
import os

from data.normalizer import Candle, BigTrade


# ─── API Client ───

# Note: Binance testnet is deprecated/offline.
# Using mainnet with LOCAL PAPER TRADING (simulated fills).
# Real orders are NOT placed — all execution is simulated.
BINANCE_BASE = "https://fapi.binance.com"


class BinanceFetcher:
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.secret_key = secret_key or os.getenv("BINANCE_SECRET_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    # ─── Kline/Candlestick Data ───

    def get_klines(
        self,
        symbol: str,
        interval: str,  # "4h", "1h", "15m", etc.
        limit: int = 500,
        start_time: Optional[int] = None,  # Unix ms
        end_time: Optional[int] = None
    ) -> list[Candle]:
        """
        Fetch historical klines from Binance.

        Raw response: [
            [open_time, o, h, l, c, v, close_time, ...],
            ...
        ]
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        resp = self.session.get(
            f"{BINANCE_BASE}/fapi/v1/klines",
            params=params,
            timeout=30
        )
        resp.raise_for_status()
        raw = resp.json()

        candles = []
        for k in raw:
            candles.append(Candle(
                open_time=datetime.fromtimestamp(k[0] / 1000),
                close_time=datetime.fromtimestamp(k[6] / 1000),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                trades=int(k[8]) if len(k) > 8 else 0
            ))
        return candles

    def get_historical_klines(
        self,
        symbol: str,
        interval: str,
        days_back: int = 30
    ) -> list[Candle]:
        """Fetch as much historical data as possible (handles Binance 1000-row limit)."""
        all_candles = []
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days_back)).timestamp() * 1000)
        limit = 1000

        while True:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
                "limit": limit
            }
            resp = self.session.get(
                f"{BINANCE_BASE}/fapi/v1/klines",
                params=params,
                timeout=30
            )
            resp.raise_for_status()
            raw = resp.json()

            if not raw:
                break

            for k in raw:
                all_candles.append(Candle(
                    open_time=datetime.fromtimestamp(k[0] / 1000),
                    close_time=datetime.fromtimestamp(k[6] / 1000),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    trades=int(k[8]) if len(k) > 8 else 0
                ))

            # Move window forward
            last_open = raw[-1][0]
            if last_open >= end_time or len(raw) < limit:
                break

            start_time = last_open + 1
            time.sleep(0.2)  # Rate limit

        return all_candles

    # ─── Aggregate Trades ───

    def get_agg_trades(
        self,
        symbol: str,
        limit: int = 500,
        from_id: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> list[BigTrade]:
        """
        Fetch aggregate trades (large trades with single taker).

        Raw response: [
            {
                "a": agg_trade_id,
                "p": price,
                "q": quantity,
                "f": first_trade_id,
                "l": last_trade_id,
                "T": timestamp,
                "m": is_buyer_maker
            },
            ...
        ]
        """
        params = {"symbol": symbol, "limit": limit}
        if from_id:
            params["fromId"] = from_id
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        resp = self.session.get(
            f"{BINANCE_BASE}/fapi/v1/aggTrades",
            params=params,
            timeout=30
        )
        resp.raise_for_status()
        raw = resp.json()

        trades = []
        for t in raw:
            trades.append(BigTrade(
                timestamp=datetime.fromtimestamp(t["T"] / 1000),
                price=float(t["p"]),
                volume=int(float(t["q"])),
                side="BUY" if not t["m"] else "SELL",
                is_buyer_maker=t["m"]
            ))
        return trades

    def get_recent_agg_trades(
        self,
        symbol: str,
        minutes_back: int = 30
    ) -> list[BigTrade]:
        """Get aggTrades from the last N minutes."""
        since = int((datetime.now() - timedelta(minutes=minutes_back)).timestamp() * 1000)
        return self.get_agg_trades(symbol, start_time=since, limit=1000)

    # ─── Exchange Info ───

    def get_symbol_info(self, symbol: str) -> dict:
        """Get trading rules and symbol info."""
        resp = self.session.get(
            f"{BINANCE_BASE}/fapi/v1/exchangeInfo",
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        for s in data["symbols"]:
            if s["symbol"] == symbol:
                return s
        raise ValueError(f"Symbol {symbol} not found")


# ─── Singleton instance ───

_fetcher: Optional[BinanceFetcher] = None


def get_fetcher() -> BinanceFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = BinanceFetcher()
    return _fetcher


if __name__ == "__main__":
    # Quick test
    f = BinanceFetcher()
    print("Testing connection to Binance Testnet...")

    try:
        candles = f.get_klines("XAUUSDT", "1h", limit=10)
        print(f"✓ XAUUSDT 1h: {len(candles)} candles fetched")
        if candles:
            print(f"  Latest: {candles[-1].close_time} close={candles[-1].close}")
    except Exception as e:
        print(f"✗ Kline fetch failed: {e}")

    try:
        trades = f.get_agg_trades("XAUUSDT", limit=10)
        print(f"✓ XAUUSDT aggTrades: {len(trades)} trades fetched")
    except Exception as e:
        print(f"✗ AggTrade fetch failed: {e}")
