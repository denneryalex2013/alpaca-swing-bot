import pandas as pd


def calculate_signals(df: pd.DataFrame, config: dict) -> tuple:
    """
    Calculates swing trading signals using EMA crossover, RSI, and VWAP.

    Returns:
        (signal, reason) where signal is "BUY", "SELL", or None
    """
    if len(df) < config["EMA_LONG"]:
        return None, f"Insufficient data ({len(df)} bars, need {config['EMA_LONG']})"

    df = df.copy()  # don't mutate the caller's DataFrame

    # --- Exponential Moving Averages (trend direction) ---
    df["ema_short"] = df["close"].ewm(span=config["EMA_SHORT"], adjust=False).mean()
    df["ema_long"]  = df["close"].ewm(span=config["EMA_LONG"],  adjust=False).mean()

    # --- RSI (momentum) — Wilder's smoothing method ---
    delta    = df["close"].diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / config["RSI_PERIOD"], adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / config["RSI_PERIOD"], adjust=False).mean()
    rs       = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # --- VWAP (20-day rolling fair value) ---
    vol        = df["volume"].astype(float)
    df["vwap"] = (df["close"] * vol).rolling(20).sum() / vol.rolling(20).sum()

    latest    = df.iloc[-1]
    ema_short = latest["ema_short"]
    ema_long  = latest["ema_long"]
    rsi       = latest["rsi"]
    price     = latest["close"]
    vwap      = latest["vwap"]

    ema_label = f"EMA{config['EMA_SHORT']}={ema_short:.2f} / EMA{config['EMA_LONG']}={ema_long:.2f}"
    rsi_label = f"RSI={rsi:.1f}"
    vwap_label = f"Price={price:.2f} vs VWAP={vwap:.2f}"

    # --- BUY: all three confirm bullish ---
    # 0.5% tolerance on EMA to catch near-crossovers
    ema_bullish  = ema_short > ema_long * 0.995
    rsi_bullish  = rsi > config["RSI_BUY_THRESHOLD"]
    above_vwap   = price > vwap

    if ema_bullish and rsi_bullish and above_vwap:
        return "BUY", f"{ema_label} | {rsi_label} | {vwap_label}"

    # --- SELL: 2-of-3 bearish conditions ---
    ema_bearish   = ema_short < ema_long * 1.005
    rsi_bearish   = rsi < config["RSI_SELL_THRESHOLD"]
    below_vwap    = price < vwap
    bearish_count = sum([ema_bearish, rsi_bearish, below_vwap])

    if bearish_count >= 2:
        return "SELL", f"{ema_label} | {rsi_label} | {vwap_label}"

    # --- No signal — explain which conditions failed ---
    failed = []
    if not ema_bullish:
        failed.append(f"EMA not crossed ({ema_short:.2f} vs {ema_long:.2f})")
    if not rsi_bullish:
        failed.append(f"RSI too low ({rsi:.1f} < {config['RSI_BUY_THRESHOLD']})")
    if not above_vwap:
        failed.append(f"Price below VWAP ({price:.2f} < {vwap:.2f})")

    return None, "No signal — " + " | ".join(failed)
