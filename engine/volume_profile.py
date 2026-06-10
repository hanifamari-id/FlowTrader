"""
FlowTrader — Volume Profile Engine (Layer 1)
Implements: Volume Profile construction, POC/VAH/VAL, Profile Shape,
Daily Bias, Key Level Identification, Entry Zone Detection.
"""

from config.settings import VALUE_AREA_PCT, LVN_THRESHOLD_PCT, HVN_THRESHOLD_PCT
from data.normalizer import (
    Candle, VolumeProfile, ValueArea, ProfileShape, LevelType,
    Bias, BiasStrength, Direction, KeyLevel, EntryZone,
)


def build_volume_profile(candles: list[Candle], tick_size: float = 0.01) -> VolumeProfile:
    """Build volume profile from OHLCV candles using price-range distribution."""
    if not candles:
        raise ValueError("No candles provided")

    profile: dict[float, int] = {}

    for candle in candles:
        low_rounded = round(candle.low / tick_size) * tick_size
        high_rounded = round(candle.high / tick_size) * tick_size
        price = low_rounded
        level_count = max(1, int((high_rounded - low_rounded) / tick_size) + 1)
        volume_per_level = candle.volume / level_count

        while price <= high_rounded:
            profile[price] = profile.get(price, 0) + int(volume_per_level)
            price += tick_size
            if tick_size == 0:
                break

    if not profile:
        raise ValueError("Empty volume profile")

    total_volume = sum(profile.values())
    poc_price = max(profile, key=profile.get)
    poc_volume = profile[poc_price]
    value_area = _calculate_value_area(profile, poc_price, total_volume, VALUE_AREA_PCT)
    classified_levels = _classify_levels(profile, poc_volume)
    shape = _determine_profile_shape(profile, value_area, poc_price)

    return VolumeProfile(
        levels=classified_levels,
        poc=poc_price,
        vah=value_area.high,
        val=value_area.low,
        total_volume=total_volume,
        shape=shape,
    )


def _calculate_value_area(
    profile: dict[float, int],
    poc_price: float,
    total_volume: int,
    target_pct: float = 0.68,
) -> ValueArea:
    target_volume = total_volume * target_pct
    sorted_prices = sorted(profile.keys())
    poc_idx = sorted_prices.index(poc_price)

    accumulated = profile[poc_price]
    upper_idx = poc_idx
    lower_idx = poc_idx

    while accumulated < target_volume and (upper_idx < len(sorted_prices) - 1 or lower_idx > 0):
        next_upper = profile.get(sorted_prices[upper_idx + 1], 0) if upper_idx + 1 < len(sorted_prices) else 0
        next_lower = profile.get(sorted_prices[lower_idx - 1], 0) if lower_idx > 0 else 0

        if next_upper >= next_lower and upper_idx + 1 < len(sorted_prices):
            upper_idx += 1
            accumulated += next_upper
        elif lower_idx > 0:
            lower_idx -= 1
            accumulated += next_lower
        elif upper_idx + 1 < len(sorted_prices):
            upper_idx += 1
            accumulated += next_upper
        else:
            break

    return ValueArea(high=sorted_prices[upper_idx], low=sorted_prices[lower_idx], volume=accumulated)


def _classify_levels(profile: dict[float, int], poc_volume: int) -> dict[float, LevelType]:
    classified = {}
    for price, volume in profile.items():
        ratio = volume / poc_volume if poc_volume > 0 else 0
        if ratio < LVN_THRESHOLD_PCT:
            classified[price] = LevelType.LVN
        elif ratio >= HVN_THRESHOLD_PCT:
            classified[price] = LevelType.HVN
        else:
            classified[price] = LevelType.NEUTRAL
    poc_price = max(profile, key=profile.get)
    classified[poc_price] = LevelType.POC
    return classified


def _determine_profile_shape(
    profile: dict[float, int],
    value_area: ValueArea,
    poc_price: float,
) -> ProfileShape:
    prices = sorted(profile.keys())
    if len(prices) < 2:
        return ProfileShape.D_SHAPE
    total_range = prices[-1] - prices[0]
    if total_range == 0:
        return ProfileShape.D_SHAPE
    poc_position = (poc_price - prices[0]) / total_range

    mid_price = (prices[-1] + prices[0]) / 2
    mid_range_prices = [p for p in prices if abs(p - mid_price) < total_range * 0.15]
    poc_vol = profile[poc_price]
    mid_avg_volume = sum(profile.get(p, 0) for p in mid_range_prices) / max(len(mid_range_prices), 1)

    if mid_avg_volume < poc_vol * 0.20 and len(mid_range_prices) > 0:
        return ProfileShape.DOUBLE_DISTRIBUTION
    if poc_position > 0.60:
        return ProfileShape.P_SHAPE
    elif poc_position < 0.40:
        return ProfileShape.B_SHAPE
    return ProfileShape.D_SHAPE


def get_daily_bias(
    today_profile: VolumeProfile,
    yesterday_profile: VolumeProfile | None,
    current_price: float,
) -> Bias:
    shape_map = {
        ProfileShape.P_SHAPE: Direction.LONG,
        ProfileShape.B_SHAPE: Direction.SHORT,
        ProfileShape.D_SHAPE: Direction.NEUTRAL,
        ProfileShape.DOUBLE_DISTRIBUTION: Direction.NEUTRAL,
    }
    bias = Bias(
        direction=shape_map.get(today_profile.shape, Direction.NEUTRAL),
        strength=BiasStrength.WEAK,
    )

    if yesterday_profile:
        if current_price > yesterday_profile.vah:
            bias.direction = Direction.LONG
            bias.strength = BiasStrength.STRONG
            bias.key_level = yesterday_profile.vah
        elif current_price < yesterday_profile.val:
            bias.direction = Direction.SHORT
            bias.strength = BiasStrength.STRONG
            bias.key_level = yesterday_profile.val

        if today_profile.poc > yesterday_profile.poc and bias.direction == Direction.LONG:
            bias.strength = BiasStrength.STRONG
        elif today_profile.poc < yesterday_profile.poc and bias.direction == Direction.SHORT:
            bias.strength = BiasStrength.STRONG

    return bias


def identify_key_levels(profiles: list[VolumeProfile], lookback_days: int = 5) -> list[KeyLevel]:
    raw: list[tuple[float, LevelType, int]] = []
    for day_idx, profile in enumerate(profiles[-lookback_days:]):
        actual_day = len(profiles) - lookback_days + day_idx
        raw.append((profile.vah, LevelType.VAH, actual_day))
        raw.append((profile.val, LevelType.VAL, actual_day))
        raw.append((profile.poc, LevelType.POC, actual_day))
        for price, lt in profile.levels.items():
            if lt == LevelType.LVN:
                raw.append((price, LevelType.LVN, actual_day))

    clustered: dict[float, list[tuple[LevelType, int]]] = {}
    tick = 0.01
    for price, lt, day in raw:
        found = False
        for cp in clustered:
            if abs(cp - price) <= tick * 2:
                clustered[cp].append((lt, day))
                found = True
                break
        if not found:
            clustered[price] = [(lt, day)]

    key_levels = []
    for price, occurrences in clustered.items():
        unique_days = len(set(d for _, d in occurrences))
        type_counts: dict[LevelType, int] = {}
        for lt, _ in occurrences:
            if lt != LevelType.LVN:
                type_counts[lt] = type_counts.get(lt, 0) + 1
        best_type = max(type_counts, key=type_counts.get) if type_counts else LevelType.LVN
        key_levels.append(KeyLevel(price=price, level_type=best_type, strength=unique_days))

    return sorted(key_levels, key=lambda x: x.strength, reverse=True)


def find_best_entry_zones(
    key_levels: list[KeyLevel],
    bias: Bias,
    current_price: float,
    max_distance_pct: float = 2.0,
) -> list[EntryZone]:
    zones = []
    for level in key_levels:
        if bias.direction == Direction.LONG and level.price < current_price:
            dist = (current_price - level.price) / current_price * 100
            if dist <= max_distance_pct:
                zones.append(EntryZone(
                    price=level.price,
                    direction=Direction.LONG,
                    level_type=level.level_type,
                    strength=level.strength,
                    confluence_score=_calc_confluence(level, key_levels),
                ))
        elif bias.direction == Direction.SHORT and level.price > current_price:
            dist = (level.price - current_price) / current_price * 100
            if dist <= max_distance_pct:
                zones.append(EntryZone(
                    price=level.price,
                    direction=Direction.SHORT,
                    level_type=level.level_type,
                    strength=level.strength,
                    confluence_score=_calc_confluence(level, key_levels),
                ))
    return sorted(zones, key=lambda z: z.confluence_score, reverse=True)


def _calc_confluence(level: KeyLevel, all_levels: list[KeyLevel]) -> float:
    score = float(level.strength) * 0.5
    tick = 0.01
    nearby = sum(
        1 for o in all_levels
        if o.price != level.price
        and abs(o.price - level.price) <= tick * 5
        and o.level_type in (LevelType.VAH, LevelType.VAL, LevelType.POC)
    )
    score += nearby * 0.2
    bonus = {LevelType.POC: 0.3, LevelType.VAH: 0.2, LevelType.VAL: 0.2, LevelType.HVN: 0.1, LevelType.LVN: 0.1}
    score += bonus.get(level.level_type, 0.0)
    return min(score, 1.0)


def is_near_key_level(price: float, zone: EntryZone, tolerance_ticks: int = 5) -> bool:
    tick = 0.01
    return abs(price - zone.price) <= tolerance_ticks * tick
