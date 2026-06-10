"""
FlowTrader — SQLite Storage Layer
Persists candles, trades, profiles, and paper trade state.
"""

import aiosqlite
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from data.normalizer import Candle, BigTrade, VolumeProfile, ProfileShape, LevelType


DB_PATH = Path(__file__).parent.parent / "flowtrader.db"


# ─── Schema Migration ───

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    pair        TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    open_time   INTEGER NOT NULL,  -- Unix ms
    close_time  INTEGER NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    trades      INTEGER,
    PRIMARY KEY (pair, timeframe, open_time)
);

CREATE TABLE IF NOT EXISTS agg_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair        TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,
    price       REAL,
    volume      INTEGER,
    is_buyer_maker INTEGER,
    UNIQUE(pair, timestamp, id)
);

CREATE TABLE IF NOT EXISTS volume_profiles (
    pair        TEXT NOT NULL,
    date        TEXT NOT NULL,  -- YYYY-MM-DD
    timeframe   TEXT NOT NULL,
    poc         REAL,
    vah         REAL,
    val         REAL,
    shape       TEXT,
    total_volume INTEGER,
    levels_json TEXT,  -- JSON {price: level_type}
    PRIMARY KEY (pair, date, timeframe)
);

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pair        TEXT NOT NULL,
    direction   TEXT NOT NULL,
    entry_price REAL,
    stop_loss   REAL,
    tp1         REAL,
    tp2         REAL,
    rr_ratio    REAL,
    total_score REAL,
    score_json  TEXT,
    pattern     TEXT,
    confidence  REAL,
    key_level_type TEXT,
    timestamp   INTEGER NOT NULL,
    status      TEXT DEFAULT 'PENDING'
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id          TEXT PRIMARY KEY,
    pair        TEXT NOT NULL,
    direction   TEXT NOT NULL,
    entry_price REAL,
    stop_loss   REAL,
    tp1         REAL,
    tp2         REAL,
    position_size REAL,
    open_time   INTEGER NOT NULL,
    close_time  INTEGER,
    pnl         REAL,
    status      TEXT DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS balance_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   INTEGER NOT NULL,
    balance     REAL NOT NULL,
    equity      REAL
);

CREATE INDEX IF NOT EXISTS idx_candles_pair_tf ON candles(pair, timeframe);
CREATE INDEX IF NOT EXISTS idx_agg_trades_pair ON agg_trades(pair, timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_pair ON signals(pair, timestamp);

CREATE TABLE IF NOT EXISTS trade_reflections (
    id          TEXT PRIMARY KEY,
    pair        TEXT NOT NULL,
    direction   TEXT NOT NULL,
    entry_price REAL,
    exit_price  REAL,
    stop_loss   REAL,
    tp1         REAL,
    tp2         REAL,
    entry_score REAL,
    slippage_pct REAL,
    pnl         REAL,
    pnl_pct     REAL,
    exit_reason TEXT,
    duration_min REAL,
    primary_pattern TEXT,
    pattern_confidence REAL,
    bias_direction TEXT,
    entry_time  INTEGER,
    exit_time   INTEGER,
    score_L1    REAL,
    score_L2    REAL,
    score_L3    REAL,
    total_score REAL,
    lessons     TEXT
);


"""


async def init_db():
    """Initialize database and run migrations."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


def _dt_to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000)


# ─── Candle Operations ───

async def save_candle(candle: Candle, pair: str, timeframe: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO candles
            (pair, timeframe, open_time, close_time, open, high, low, close, volume, trades)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pair, timeframe,
            _dt_to_ms(candle.open_time),
            _dt_to_ms(candle.close_time),
            candle.open, candle.high, candle.low, candle.close,
            candle.volume, candle.trades
        ))
        await db.commit()


async def get_candles(
    pair: str,
    timeframe: str,
    since: Optional[datetime] = None,
    limit: int = 500
) -> list[Candle]:
    async with aiosqlite.connect(DB_PATH) as db:
        if since:
            rows = await db.execute_fetchall("""
                SELECT open_time, close_time, open, high, low, close, volume, trades
                FROM candles
                WHERE pair = ? AND timeframe = ? AND open_time >= ?
                ORDER BY open_time ASC
                LIMIT ?
            """, (pair, timeframe, _dt_to_ms(since), limit))
        else:
            rows = await db.execute_fetchall("""
                SELECT open_time, close_time, open, high, low, close, volume, trades
                FROM candles
                WHERE pair = ? AND timeframe = ?
                ORDER BY open_time DESC
                LIMIT ?
            """, (pair, timeframe, limit))
            rows = list(reversed(rows))

        return [
            Candle(
                open_time=_ms_to_dt(r[0]),
                close_time=_ms_to_dt(r[1]),
                open=r[2], high=r[3], low=r[4], close=r[5],
                volume=r[6], trades=r[7]
            )
            for r in rows
        ]


# ─── AggTrade Operations ───

async def save_agg_trades(trades: list[BigTrade], pair: str):
    async with aiosqlite.connect(DB_PATH) as db:
        for trade in trades:
            await db.execute("""
                INSERT OR IGNORE INTO agg_trades
                (pair, timestamp, price, volume, is_buyer_maker)
                VALUES (?, ?, ?, ?, ?)
            """, (
                pair,
                _dt_to_ms(trade.timestamp),
                trade.price,
                trade.volume,
                int(trade.is_buyer_maker)
            ))
        await db.commit()


async def get_agg_trades_since(
    pair: str,
    since: datetime,
    limit: int = 1000
) -> list[BigTrade]:
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("""
            SELECT timestamp, price, volume, is_buyer_maker
            FROM agg_trades
            WHERE pair = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (pair, _dt_to_ms(since), limit))

        return [
            BigTrade(
                timestamp=_ms_to_dt(r[0]),
                price=r[1],
                volume=r[2],
                side="BUY" if not bool(r[3]) else "SELL",
                is_buyer_maker=bool(r[3])
            )
            for r in rows
        ]


# ─── Volume Profile Operations ───

async def save_volume_profile(profile: VolumeProfile, pair: str, date: str, timeframe: str):
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO volume_profiles
            (pair, date, timeframe, poc, vah, val, shape, total_volume, levels_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pair, date, timeframe,
            profile.poc, profile.vah, profile.val,
            profile.shape.value,
            profile.total_volume,
            json.dumps({str(k): v.value for k, v in profile.levels.items()})
        ))
        await db.commit()


async def get_latest_profile(pair: str, timeframe: str, days: int = 5) -> list[VolumeProfile]:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("""
            SELECT date, poc, vah, val, shape, total_volume, levels_json
            FROM volume_profiles
            WHERE pair = ? AND timeframe = ?
            ORDER BY date DESC
            LIMIT ?
        """, (pair, timeframe, days))

        profiles = []
        for r in reversed(rows):
            levels_raw = json.loads(r[6])
            levels = {float(k): LevelType(v) for k, v in levels_raw.items()}
            profiles.append(VolumeProfile(
                levels=levels,
                poc=r[1], vah=r[2], val=r[3],
                shape=ProfileShape(r[4]),
                total_volume=r[5]
            ))
        return profiles


# ─── Signal Operations ───

async def save_signal(signal) -> int:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO signals
            (pair, direction, entry_price, stop_loss, tp1, tp2, rr_ratio,
             total_score, score_json, pattern, confidence, key_level_type, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.pair, signal.direction.value if hasattr(signal.direction, 'value') else signal.direction,
            signal.entry_price, signal.stop_loss, signal.tp1, signal.tp2,
            signal.rr_ratio, signal.total_score,
            json.dumps(signal.score_breakdown),
            signal.primary_pattern, signal.confidence,
            signal.key_level_type,
            _dt_to_ms(signal.timestamp)
        ))
        await db.commit()
        return cursor.lastrowid


async def update_signal_status(signal_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE signals SET status = ? WHERE id = ?",
            (status, signal_id)
        )
        await db.commit()


# ─── Paper Trade Operations ───

async def save_paper_trade(trade):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO paper_trades
            (id, pair, direction, entry_price, stop_loss, tp1, tp2,
             position_size, open_time, close_time, pnl, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.id, trade.pair, trade.direction.value,
            trade.entry_price, trade.stop_loss, trade.tp1, trade.tp2,
            trade.position_size,
            _dt_to_ms(trade.open_time),
            _dt_to_ms(trade.close_time) if trade.close_time else None,
            trade.current_pnl, trade.status
        ))
        await db.commit()


async def get_open_trades() -> list:
    from data.normalizer import OpenTrade, Direction
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("""
            SELECT id, pair, direction, entry_price, stop_loss, tp1, tp2,
                   position_size, open_time, current_pnl, status, tp1_hit, trailing_sl
            FROM paper_trades
            WHERE status = 'OPEN'
        """)

        return [
            OpenTrade(
                id=r[0], pair=r[1],
                direction=Direction(r[2]),
                entry_price=r[3], stop_loss=r[4],
                tp1=r[5], tp2=r[6],
                position_size=r[7],
                open_time=_ms_to_dt(r[8]),
                current_pnl=r[9] or 0.0,
                status=r[10],
                tp1_hit=bool(r[11]) if r[11] is not None else False,
                trailing_sl=r[12] or 0.0
            )
            for r in rows
        ]


async def close_paper_trade(trade_id: str, pnl: float, close_time: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE paper_trades
            SET status = 'CLOSED', pnl = ?, close_time = ?
            WHERE id = ?
        """, (pnl, _dt_to_ms(close_time), trade_id))
        await db.commit()


# ─── Balance History ───

async def save_balance(timestamp: datetime, balance: float, equity: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO balance_history (timestamp, balance, equity)
            VALUES (?, ?, ?)
        """, (_dt_to_ms(timestamp), balance, equity))
        await db.commit()


async def get_current_balance() -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await db.execute_fetchall("""
            SELECT balance FROM balance_history
            ORDER BY timestamp DESC LIMIT 1
        """)
        return row[0][0] if row else 1000.0


# ─── Trade Reflections ───

async def save_reflection(reflection) -> None:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO trade_reflections
            (id, pair, direction, entry_price, exit_price, stop_loss, tp1, tp2,
             entry_score, slippage_pct, pnl, pnl_pct, exit_reason,
             duration_min, primary_pattern, pattern_confidence, bias_direction,
             entry_time, exit_time, score_L1, score_L2, score_L3, total_score, lessons)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reflection.id,
            reflection.pair,
            reflection.direction.value if hasattr(reflection.direction, "value") else reflection.direction,
            reflection.entry_price,
            reflection.exit_price,
            reflection.stop_loss,
            reflection.tp1,
            reflection.tp2,
            reflection.entry_score,
            reflection.entry_slippage_pct,
            reflection.pnl,
            reflection.pnl_pct,
            reflection.exit_reason.value,
            reflection.duration_minutes,
            reflection.primary_pattern,
            reflection.pattern_confidence,
            reflection.bias_direction,
            _dt_to_ms(reflection.entry_time),
            _dt_to_ms(reflection.exit_time),
            reflection.score_L1,
            reflection.score_L2,
            reflection.score_L3,
            reflection.total_score,
            json.dumps(reflection.lessons),
        ))
        await db.commit()


async def get_reflections(pair: str = None, limit: int = 20) -> list[dict]:
    """Get recent reflections, optionally filtered by pair."""
    async with aiosqlite.connect(DB_PATH) as db:
        if pair:
            rows = await db.execute_fetchall("""
                SELECT id, pair, direction, entry_price, exit_price, pnl, pnl_pct,
                       exit_reason, duration_min, primary_pattern, total_score, lessons, exit_time
                FROM trade_reflections
                WHERE pair = ?
                ORDER BY exit_time DESC
                LIMIT ?
            """, (pair, limit))
        else:
            rows = await db.execute_fetchall("""
                SELECT id, pair, direction, entry_price, exit_price, pnl, pnl_pct,
                       exit_reason, duration_min, primary_pattern, total_score, lessons, exit_time
                FROM trade_reflections
                ORDER BY exit_time DESC
                LIMIT ?
            """, (limit,))

        import json
        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "pair": r[1],
                "direction": r[2],
                "entry": r[3],
                "exit": r[4],
                "pnl": r[5],
                "pnl_pct": r[6],
                "exit_reason": r[7],
                "duration_min": r[8],
                "pattern": r[9],
                "total_score": r[10],
                "lessons": json.loads(r[11]) if r[11] else [],
                "exit_time": _ms_to_dt(r[12]) if r[12] else None,
            })
        return results


if __name__ == "__main__":
    asyncio.run(init_db())
    print(f"Database initialized at {DB_PATH}")
