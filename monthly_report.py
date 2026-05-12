#!/usr/bin/env python3
"""
Monthly P&L report for Alpaca Swing Bot.
Sends a Discord embed with performance summary, trade stats, and goal progress.

Usage:
    python monthly_report.py                        # current month-to-date
    python monthly_report.py --since 2026-04-09     # all-time from a specific date
    python monthly_report.py --month 2026-04        # specific past month
"""
import os
import sys
import json
import argparse
import calendar
import datetime
import urllib.request
import urllib.error
from collections import defaultdict

import pytz
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

ET = pytz.timezone("America/New_York")

_GREEN  = 3066993
_RED    = 15158332
_BLUE   = 3447003
_GOLD   = 15844367
_PURPLE = 10181046


# ── Period helpers ─────────────────────────────────────────────────────────────

def get_period(since: str = None, month: str = None):
    """Returns (start, end, label) as timezone-aware ET datetimes."""
    now = datetime.datetime.now(ET)

    if since:
        start = ET.localize(datetime.datetime.strptime(since, "%Y-%m-%d"))
        return start, now, f"{start.strftime('%b %d, %Y')} -> Today"

    if month:
        year, mon = map(int, month.split("-"))
    elif now.day == 1:
        # On the 1st, report on the month that just ended
        first_of_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev          = first_of_this - datetime.timedelta(days=1)
        year, mon     = prev.year, prev.month
    else:
        year, mon = now.year, now.month

    start = ET.localize(datetime.datetime(year, mon, 1, 0, 0, 0))
    if year == now.year and mon == now.month:
        end   = now
        label = f"{start.strftime('%B %Y')} (MTD)"
    else:
        last_day = calendar.monthrange(year, mon)[1]
        end      = ET.localize(datetime.datetime(year, mon, last_day, 23, 59, 59))
        label    = start.strftime("%B %Y")

    return start, end, label


def get_period_last_month():
    """Used by main.py on the 1st of the month."""
    now           = datetime.datetime.now(ET)
    first_of_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev          = first_of_this - datetime.timedelta(days=1)
    year, mon     = prev.year, prev.month
    last_day      = calendar.monthrange(year, mon)[1]
    start         = ET.localize(datetime.datetime(year, mon, 1, 0, 0, 0))
    end           = ET.localize(datetime.datetime(year, mon, last_day, 23, 59, 59))
    return start, end, prev.strftime("%B %Y")


# ── Trade analysis ─────────────────────────────────────────────────────────────

def analyze_trades(orders) -> dict:
    """FIFO match of buys → sells per symbol to compute realized P&L and win rate."""
    by_symbol = defaultdict(lambda: {"buys": [], "sells": []})

    for o in orders:
        try:
            status = o.status.value if hasattr(o.status, "value") else str(o.status)
            if status not in ("filled", "partially_filled"):
                continue
            price = float(o.filled_avg_price or 0)
            qty   = float(o.filled_qty or 0)
            if qty == 0 or price == 0:
                continue
            side = o.side.value if hasattr(o.side, "value") else str(o.side)
            entry = {"price": price, "qty": qty, "time": o.filled_at}
            if "buy" in side.lower():
                by_symbol[o.symbol]["buys"].append(entry)
            else:
                by_symbol[o.symbol]["sells"].append(entry)
        except Exception:
            continue

    realized_pnl = 0.0
    win_count    = 0
    loss_count   = 0
    best_trade   = None  # (symbol, pct, $pnl)
    worst_trade  = None
    total_buys   = sum(len(v["buys"])  for v in by_symbol.values())
    total_sells  = sum(len(v["sells"]) for v in by_symbol.values())

    for symbol, data in by_symbol.items():
        buys  = sorted(data["buys"],  key=lambda x: x["time"] or datetime.datetime.min)
        sells = sorted(data["sells"], key=lambda x: x["time"] or datetime.datetime.min)

        for sell in sells:
            if not buys:
                break
            buy      = buys.pop(0)
            pnl      = (sell["price"] - buy["price"]) * min(sell["qty"], buy["qty"])
            pnl_pct  = (sell["price"] - buy["price"]) / buy["price"] * 100
            realized_pnl += pnl

            if pnl >= 0:
                win_count += 1
            else:
                loss_count += 1

            if best_trade is None or pnl_pct > best_trade[1]:
                best_trade = (symbol, pnl_pct, pnl)
            if worst_trade is None or pnl_pct < worst_trade[1]:
                worst_trade = (symbol, pnl_pct, pnl)

    return {
        "total_buys":   total_buys,
        "total_sells":  total_sells,
        "realized_pnl": realized_pnl,
        "win_count":    win_count,
        "loss_count":   loss_count,
        "best_trade":   best_trade,
        "worst_trade":  worst_trade,
    }


# ── Discord ────────────────────────────────────────────────────────────────────

def _send_discord(webhook_url: str, embeds: list):
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"embeds": embeds}).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "DiscordBot (https://github.com, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req):
        pass


# ── Core report ────────────────────────────────────────────────────────────────

def send(trading_client: TradingClient, webhook_url: str, start=None, end=None, label=None):
    """
    Build and send the monthly report. Called by main.py (auto) or monthly_report.py (manual).
    If start/end/label are None, defaults to last complete calendar month.
    """
    if start is None:
        start, end, label = get_period_last_month()

    print(f"[monthly_report] Generating: {label}")

    # ── Account snapshot ──────────────────────────────────────────────────────
    account    = trading_client.get_account()
    equity_now = float(account.equity)
    cash_now   = float(account.cash)
    positions  = trading_client.get_all_positions()

    unrealized_pnl = sum(float(p.unrealized_pl) for p in positions)

    # ── Portfolio history: find starting equity ───────────────────────────────
    start_equity = None
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        period_days = max(7, (end.date() - start.date()).days + 2)
        hist = trading_client.get_portfolio_history(
            GetPortfolioHistoryRequest(period=f"{period_days}D", timeframe="1D")
        )
        if hist and hist.equity:
            for eq in hist.equity:
                if eq and float(eq) > 0:
                    start_equity = float(eq)
                    break
    except Exception as e:
        print(f"[monthly_report] Portfolio history unavailable: {e}")

    # ── Closed orders in period ───────────────────────────────────────────────
    orders = []
    try:
        orders = list(trading_client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=start.replace(tzinfo=None),
            until=end.replace(tzinfo=None),
            direction="asc",
            limit=500,
        )))
    except Exception as e:
        print(f"[monthly_report] Order history error: {e}")

    stats = analyze_trades(orders)

    # ── P&L strings ───────────────────────────────────────────────────────────
    if start_equity and start_equity > 0:
        total_pnl     = equity_now - start_equity
        total_pnl_pct = total_pnl / start_equity * 100
        sign          = "+" if total_pnl >= 0 else ""
        pnl_color     = _GREEN if total_pnl >= 0 else _RED
        pnl_str       = f"**{sign}${total_pnl:,.2f}** ({sign}{total_pnl_pct:.1f}%)"
        equity_str    = f"${start_equity:,.2f} → **${equity_now:,.2f}**"
    else:
        pnl_color  = _GOLD
        pnl_str    = "N/A"
        equity_str = f"**${equity_now:,.2f}**"

    real_sign   = "+" if stats["realized_pnl"] >= 0 else ""
    unreal_sign = "+" if unrealized_pnl >= 0 else ""
    pnl_breakdown = (
        f"Realized: **{real_sign}${stats['realized_pnl']:.2f}**\n"
        f"Unrealized: **{unreal_sign}${unrealized_pnl:.2f}**"
    )

    # ── Goal progress ($500 → $600) ───────────────────────────────────────────
    goal_start  = 500.0
    goal_target = 600.0
    progress    = max(0.0, equity_now - goal_start)
    goal_range  = goal_target - goal_start
    goal_pct    = min(100.0, progress / goal_range * 100)
    filled      = int(goal_pct / 10)
    goal_bar    = "█" * filled + "░" * (10 - filled)
    goal_str    = f"`{goal_bar}` {goal_pct:.0f}%  (${equity_now:,.2f} / ${goal_target:,.2f})"

    # ── Win rate ──────────────────────────────────────────────────────────────
    closed = stats["win_count"] + stats["loss_count"]
    if closed > 0:
        win_pct     = stats["win_count"] / closed * 100
        winrate_str = f"{win_pct:.0f}%  ({stats['win_count']}W / {stats['loss_count']}L of {closed} closed)"
    else:
        winrate_str = "No closed round-trips yet"

    def trade_str(t):
        if not t:
            return "—"
        sym, pct, pnl = t
        s = "+" if pct >= 0 else ""
        return f"**{sym}** {s}{pct:.1f}% ({s}${pnl:.2f})"

    # ── Open positions ────────────────────────────────────────────────────────
    if positions:
        pos_lines = []
        for p in positions:
            pl    = float(p.unrealized_pl)
            plpct = float(p.unrealized_plpc) * 100
            s     = "+" if pl >= 0 else ""
            pos_lines.append(f"**{p.symbol}** {s}{plpct:.1f}% ({s}${pl:.2f})")
        pos_str = "\n".join(pos_lines)
    else:
        pos_str = "None"

    embeds = [
        {
            "title":       "Alpaca Swing Bot — Monthly Report",
            "description": f"**{label}**",
            "color":       pnl_color,
            "fields": [
                {"name": "Equity",                       "value": equity_str,    "inline": False},
                {"name": "Total P&L",                    "value": pnl_str,       "inline": False},
                {"name": "P&L Breakdown",                "value": pnl_breakdown, "inline": False},
                {"name": "Goal Progress ($500 → $600)",  "value": goal_str,      "inline": False},
            ],
        },
        {
            "title": "Trade Stats",
            "color": _BLUE,
            "fields": [
                {"name": "Trades",          "value": f"{stats['total_buys']} buys · {stats['total_sells']} sells", "inline": False},
                {"name": "Win Rate",        "value": winrate_str,              "inline": False},
                {"name": "Best Trade",      "value": trade_str(stats["best_trade"]),  "inline": True},
                {"name": "Worst Trade",     "value": trade_str(stats["worst_trade"]), "inline": True},
                {"name": "Open Positions",  "value": pos_str,                  "inline": False},
                {"name": "Cash Available",  "value": f"${cash_now:,.2f}",      "inline": True},
            ],
        },
    ]

    _send_discord(webhook_url, embeds)
    print(f"[monthly_report] Sent to Discord.")


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="Start date YYYY-MM-DD (all-time from this date)")
    parser.add_argument("--month", help="Specific month YYYY-MM")
    args = parser.parse_args()

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    api_key     = os.getenv("ALPACA_API_KEY", "")
    api_secret  = os.getenv("ALPACA_API_SECRET", "")

    if not all([webhook_url, api_key, api_secret]):
        print("Missing env vars. Need: DISCORD_WEBHOOK_URL, ALPACA_API_KEY, ALPACA_API_SECRET")
        sys.exit(1)

    trading_client    = TradingClient(api_key, api_secret, paper=False)
    start, end, label = get_period(since=args.since, month=args.month)
    send(trading_client, webhook_url, start, end, label)


if __name__ == "__main__":
    main()
