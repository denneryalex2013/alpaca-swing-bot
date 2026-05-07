import logging
import yfinance as yf

from app import config


def get_market_context() -> dict:
    """
    Fetch VIX and SPY 50-day MA from Yahoo Finance.
    Returns a context dict. On any failure, returns safe defaults so trading continues.
    """
    context = {
        "vix":      0.0,
        "spy_price": 0.0,
        "spy_ma50":  0.0,
        "vix_ok":   False,
        "spy_ok":   False,
    }

    # VIX — CBOE Volatility Index
    try:
        hist = yf.Ticker("^VIX").history(period="2d")
        if not hist.empty:
            context["vix"]    = float(hist["Close"].iloc[-1])
            context["vix_ok"] = True
    except Exception as e:
        logging.warning(f"VIX fetch failed: {e}")

    # SPY — fetch 60 days to compute 50-day MA
    try:
        hist = yf.Ticker("SPY").history(period="60d")
        if len(hist) >= 50:
            context["spy_price"] = float(hist["Close"].iloc[-1])
            context["spy_ma50"]  = float(hist["Close"].tail(50).mean())
            context["spy_ok"]    = True
    except Exception as e:
        logging.warning(f"SPY fetch failed: {e}")

    return context


def should_allow_buy(symbol: str, context: dict) -> tuple[bool, str]:
    """
    Returns (allow, reason). Only blocks BUY signals — sells are never gated.

    Rules:
    - VIX > threshold: market is stressed, skip buys
    - SPY below 50-day MA: broad market in downtrend, skip buys
    """
    vix       = context["vix"]
    spy_price = context["spy_price"]
    spy_ma50  = context["spy_ma50"]

    if context["vix_ok"] and vix > config.VIX_BUY_BLOCK_THRESHOLD:
        return False, f"VIX={vix:.1f} > {config.VIX_BUY_BLOCK_THRESHOLD} — market stressed, buy signals suppressed"

    if context["spy_ok"] and spy_price < spy_ma50:
        return False, f"SPY ${spy_price:.2f} below 50-day MA ${spy_ma50:.2f} — broad market in downtrend"

    return True, f"VIX={vix:.1f} | SPY ${spy_price:.2f} vs MA50 ${spy_ma50:.2f}"
