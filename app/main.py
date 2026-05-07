import os
import time
import datetime
from datetime import timedelta

import pytz
from dotenv import load_dotenv

load_dotenv()

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

from app import config
from app.strategy import calculate_signals
from app import logger
from app import prefilter

ET = pytz.timezone("America/New_York")

STRATEGY_CONFIG = {
    "EMA_SHORT":          config.EMA_SHORT,
    "EMA_LONG":           config.EMA_LONG,
    "RSI_PERIOD":         config.RSI_PERIOD,
    "RSI_BUY_THRESHOLD":  config.RSI_BUY_THRESHOLD,
    "RSI_SELL_THRESHOLD": config.RSI_SELL_THRESHOLD,
}


# ── Alpaca client setup ────────────────────────────────────────────────────────

def get_clients():
    api_key    = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET must be set")
    trading = TradingClient(api_key, api_secret, paper=False)
    data    = StockHistoricalDataClient(api_key, api_secret)
    return trading, data


# ── Data fetching ──────────────────────────────────────────────────────────────

def get_bars(data_client, symbol: str):
    end   = datetime.datetime.now(ET)
    start = end - timedelta(days=config.BARS_TO_FETCH)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=DataFeed.IEX,  # requires Alpaca Unlimited subscription for SIP
    )
    bars = data_client.get_stock_bars(request)
    df   = bars.df

    if df is None or df.empty:
        return None

    try:
        df = df.loc[symbol].reset_index()
    except KeyError:
        return None

    return df if not df.empty else None


# ── Market hours ───────────────────────────────────────────────────────────────

def is_scan_window() -> bool:
    """Returns True between 9:35–10:00 AM ET on weekdays."""
    now = datetime.datetime.now(ET)
    if now.weekday() >= 5:
        return False
    window_open  = now.replace(hour=9,  minute=35, second=0, microsecond=0)
    window_close = now.replace(hour=10, minute=0,  second=0, microsecond=0)
    return window_open <= now <= window_close


# ── Core scan logic ────────────────────────────────────────────────────────────

def run_scan(trading_client, data_client):
    logger.log("=== Alpaca Swing Bot — daily scan ===")

    try:
        account        = trading_client.get_account()
        equity         = float(account.equity)
        cash           = float(account.cash)
        open_positions = {p.symbol: p for p in trading_client.get_all_positions()}
        trade_size     = min(equity * config.TRADE_SIZE_PCT, config.MAX_TRADE_SIZE)

        market_ctx = prefilter.get_market_context()
        logger.log_scan_start(equity, cash, trade_size, open_positions, len(config.WATCHLIST), market_ctx)

        # ── Phase 1: Exit checks for open positions ────────────────────────────
        exited = set()
        for symbol, position in list(open_positions.items()):
            if symbol not in config.WATCHLIST:
                continue
            try:
                df = get_bars(data_client, symbol)
                if df is None:
                    continue

                signal, reason = calculate_signals(df, STRATEGY_CONFIG)
                current_price  = float(df.iloc[-1]["close"])

                logger.log_decision(symbol, signal, reason, current_price)
                exited.add(symbol)

                if signal != "SELL":
                    continue

                position_value = float(position.market_value)
                if position_value < config.MIN_TRADE_USD:
                    logger.log_skipped(symbol, f"Dust position (${position_value:.2f}) — skipping sell")
                    continue

                # Cancel open GTC stop-loss orders before closing the position
                open_orders = trading_client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
                )
                for order in open_orders:
                    try:
                        trading_client.cancel_order_by_id(order.id)
                    except Exception:
                        pass

                trading_client.close_position(symbol)
                qty = float(position.qty)
                logger.log_order(symbol, "SELL", current_price, qty)
                del open_positions[symbol]
                cash += qty * current_price

            except Exception as e:
                logger.log_error(f"{symbol} (exit check): {e}")

        # ── Phase 2: Entry scan ────────────────────────────────────────────────
        for symbol in config.WATCHLIST:

            # Guard: max positions
            if len(open_positions) >= config.MAX_POSITIONS:
                logger.log_skipped(symbol, "Max positions reached")
                break

            # Guard: already holding (evaluated above — skip silently)
            if symbol in open_positions:
                continue

            # Guard: trade size below minimum
            if trade_size < config.MIN_TRADE_USD:
                logger.log_skipped(symbol, f"Trade size ${trade_size:.2f} below minimum ${config.MIN_TRADE_USD:.2f}")
                break

            # Guard: insufficient cash
            if cash < trade_size:
                logger.log_skipped(symbol, f"Insufficient cash (${cash:.2f} < ${trade_size:.2f})")
                break

            try:
                df = get_bars(data_client, symbol)
                if df is None:
                    logger.log_skipped(symbol, "No price data returned")
                    continue

                signal, reason = calculate_signals(df, STRATEGY_CONFIG)
                current_price  = float(df.iloc[-1]["close"])

                # Skip logging if this symbol was already evaluated in the exit phase
                if symbol not in exited:
                    logger.log_decision(symbol, signal, reason, current_price)

                if signal != "BUY":
                    continue

                allow_buy, pf_reason = prefilter.should_allow_buy(symbol, market_ctx)
                if not allow_buy:
                    logger.log_skipped(symbol, pf_reason)
                    continue

                # Submit fractional market buy using notional (dollar amount)
                order = MarketOrderRequest(
                    symbol=symbol,
                    notional=round(trade_size, 2),
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
                submitted = trading_client.submit_order(order)

                # Poll until filled (market hours — typically fills within 1–2s)
                fill_price = None
                filled_qty = None
                for _ in range(15):
                    time.sleep(1)
                    fill_status = trading_client.get_order_by_id(submitted.id)
                    if fill_status.status == OrderStatus.FILLED:
                        fill_price = float(fill_status.filled_avg_price)
                        filled_qty = float(fill_status.filled_qty)
                        break

                if fill_price is None:
                    try:
                        trading_client.cancel_order_by_id(submitted.id)
                    except Exception:
                        pass
                    logger.log_error(f"{symbol}: Market order did not fill within 15s — cancelled")
                    continue

                # Place GTC stop-loss as safety net (signal-based SELL is the primary exit)
                sl_price = round(fill_price * (1 - config.STOP_LOSS_PCT), 2)
                stop = StopOrderRequest(
                    symbol=symbol,
                    qty=round(filled_qty, 6),
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    stop_price=sl_price,
                )
                trading_client.submit_order(stop)

                logger.log_order(symbol, "BUY", fill_price, filled_qty, sl=sl_price)

                open_positions[symbol] = True  # track locally so loop stays accurate
                cash -= trade_size

            except Exception as e:
                msg = str(e)
                if "notional" in msg.lower() or "minimum" in msg.lower():
                    logger.log_error(f"{symbol}: Order rejected — {msg}")
                else:
                    logger.log_error(f"{symbol}: {e}")

    except Exception as e:
        logger.log_error(f"Scan aborted: {e}")

    finally:
        logger.log_scan_end()


# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    logger.log("Alpaca Swing Bot started")
    trading_client, data_client = get_clients()

    scanned_today  = False
    last_scan_date = None

    while True:
        now   = datetime.datetime.now(ET)
        today = now.date()

        # Reset flag at midnight
        if last_scan_date != today:
            scanned_today  = False
            last_scan_date = today

        if not scanned_today and is_scan_window():
            run_scan(trading_client, data_client)
            scanned_today = True

        time.sleep(60)  # check every minute


if __name__ == "__main__":
    main()
