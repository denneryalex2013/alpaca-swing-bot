import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import pytz

ET = pytz.timezone("America/New_York")

# ── Internal state ─────────────────────────────────────────────────────────────

_log_buffer:    list[str] = []
_buy_lines:     list[str] = []
_sell_lines:    list[str] = []
_signal_lines:  list[str] = []
_skip_lines:    list[str] = []
_error_lines:   list[str] = []

_current_equity:     float = 0.0
_current_cash:       float = 0.0
_current_trade_size: float = 0.0
_open_positions:     list[dict] = []   # [{symbol, qty, entry, price, pl, plpc}]
_watchlist_size:     int = 0

# Discord embed colors
_BLUE   = 3447003   # #3498DB
_GREEN  = 3066993   # #2ECC71
_RED    = 15158332  # #E74C3C
_YELLOW = 15844367  # #F1C40F
_PURPLE = 10181046  # #9B59B6


def _now() -> str:
    return datetime.now(ET).strftime("%H:%M:%S")


def _today() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def log(msg: str):
    """Print timestamped message to stdout — captured by DigitalOcean logs."""
    print(f"[{_now()}] {msg}", flush=True)


def _buffer(line: str):
    _log_buffer.append(line)


def _write_obsidian(line: str):
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if not vault_path:
        return

    trading_dir = os.path.join(vault_path, "Trading")
    os.makedirs(trading_dir, exist_ok=True)

    note_path = os.path.join(trading_dir, f"{_today()}.md")

    if not os.path.exists(note_path):
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(f"# Trade Log — {_today()}\n")

    with open(note_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _next_scan_str() -> str:
    now  = datetime.now(ET)
    next_day = now.date() + timedelta(days=1)
    while next_day.weekday() >= 5:   # skip Saturday (5) and Sunday (6)
        next_day += timedelta(days=1)
    return f"{next_day.strftime('%A, %b')} {next_day.day} at 9:35 AM ET"


def _send_discord():
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return

    embeds = []

    # ── Embed 1: Account Snapshot (blue) ──────────────────────────────────────
    pos_lines = []
    for p in _open_positions:
        pl_sign = "+" if p["pl"] >= 0 else ""
        pos_lines.append(
            f"**{p['symbol']}** | Qty: {p['qty']} | "
            f"Entry: ${p['entry']:.2f} | Price: ${p['price']:.2f} | "
            f"P&L: {pl_sign}${p['pl']:.2f} ({pl_sign}{p['plpc']:.1f}%)"
        )

    max_pos = os.getenv("MAX_POSITIONS", "3")
    embeds.append({
        "title": f"Alpaca Swing Bot — {_today()}",
        "color": _BLUE,
        "fields": [
            {
                "name": "Portfolio",
                "value": (
                    f"Equity: **${_current_equity:,.2f}** | "
                    f"Cash: **${_current_cash:,.2f}** | "
                    f"Trade size: **${_current_trade_size:,.2f}**"
                ),
                "inline": False,
            },
            {
                "name": f"Open Positions ({len(_open_positions)}/{max_pos})",
                "value": "\n".join(pos_lines) if pos_lines else "No open positions",
                "inline": False,
            },
        ],
    })

    # ── Embed 2a: Buy Orders (green) ──────────────────────────────────────────
    if _buy_lines:
        embeds.append({
            "title": "Buy Orders",
            "color": _GREEN,
            "fields": [{
                "name": f"{len(_buy_lines)} order(s) executed",
                "value": "\n".join(_buy_lines),
                "inline": False,
            }],
        })

    # ── Embed 2b: Sell Orders (red) ───────────────────────────────────────────
    if _sell_lines:
        embeds.append({
            "title": "Sell Orders",
            "color": _RED,
            "fields": [{
                "name": f"{len(_sell_lines)} order(s) executed",
                "value": "\n".join(_sell_lines),
                "inline": False,
            }],
        })

    # ── Embed 3: Signals Evaluated (yellow) ───────────────────────────────────
    if _signal_lines:
        embeds.append({
            "title": "Signals Evaluated",
            "color": _YELLOW,
            "fields": [{
                "name": f"{len(_signal_lines)} symbol(s) reached strategy",
                "value": "\n".join(_signal_lines),
                "inline": False,
            }],
        })

    # ── Embed 4: Pre-filter Skips (purple) ────────────────────────────────────
    if _skip_lines:
        embeds.append({
            "title": "Pre-filter Skips",
            "color": _PURPLE,
            "fields": [{
                "name": f"{len(_skip_lines)} symbol(s) filtered before strategy",
                "value": "\n".join(_skip_lines),
                "inline": False,
            }],
        })

    # ── Embed 5: Errors (red) — only if any ──────────────────────────────────
    if _error_lines:
        embeds.append({
            "title": "Errors",
            "color": _RED,
            "fields": [{
                "name": f"{len(_error_lines)} error(s) during scan",
                "value": "\n".join(_error_lines),
                "inline": False,
            }],
        })

    # ── Embed 6: Summary (blue) — always present ──────────────────────────────
    trades_placed = len(_buy_lines) + len(_sell_lines)
    summary_value = "\n".join([
        f"Symbols scanned: **{_watchlist_size}**",
        f"Trades placed: **{trades_placed}**",
        f"Signals evaluated: **{len(_signal_lines)}**",
        f"Pre-filtered: **{len(_skip_lines)}**",
    ])

    embeds.append({
        "title": "Scan Summary",
        "color": _BLUE,
        "fields": [
            {"name": "Results",    "value": summary_value,      "inline": False},
            {"name": "Next Scan",  "value": _next_scan_str(),   "inline": False},
        ],
    })

    try:
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
            log("Discord notification sent")
    except urllib.error.HTTPError as e:
        log(f"Discord notify failed (HTTP {e.code}): {e.read().decode()}")
    except urllib.error.URLError as e:
        log(f"Discord notify failed: {e.reason}")


# ── Public logging helpers ─────────────────────────────────────────────────────

def log_scan_start(equity: float, cash: float, trade_size: float, positions: dict, watchlist_size: int):
    global _current_equity, _current_cash, _current_trade_size, _open_positions, _watchlist_size
    _current_equity     = equity
    _current_cash       = cash
    _current_trade_size = trade_size
    _watchlist_size     = watchlist_size

    _open_positions = []
    for symbol, p in positions.items():
        _open_positions.append({
            "symbol": symbol,
            "qty":    float(p.qty),
            "entry":  float(p.avg_entry_price),
            "price":  float(p.current_price),
            "pl":     float(p.unrealized_pl),
            "plpc":   float(p.unrealized_plpc) * 100,  # decimal → percentage
        })

    msg = (
        f"Scan started | "
        f"Equity: ${equity:.2f} | "
        f"Cash: ${cash:.2f} | "
        f"Trade size: ${trade_size:.2f} | "
        f"Open positions: {len(positions)}/{os.getenv('MAX_POSITIONS', '3')}"
    )
    log(msg)
    _write_obsidian(f"\n## Scan — {_now()}\n**{msg}**\n")
    _buffer(f"# Trade Log — {_today()}\n")
    _buffer(f"## Scan — {_now()}\n**{msg}**\n")


def log_decision(symbol: str, signal, reason: str, price: float):
    icon = {"BUY": "[BUY]", "SELL": "[SELL]"}.get(signal, "[SKIP]")
    msg  = f"{icon} {symbol} @ ${price:.2f} — {reason}"
    log(msg)
    _write_obsidian(f"- {msg}")
    _buffer(f"- {msg}")
    _signal_lines.append(msg)


def log_order(symbol: str, action: str, price: float, qty: float, tp: float = 0.0, sl: float = 0.0):
    if action == "BUY":
        parts = [f"ORDER BUY {qty:.6f} {symbol} @ ${price:.2f}"]
        if tp:
            parts.append(f"TP: ${tp:.2f} (+{((tp/price)-1)*100:.1f}%)")
        if sl:
            parts.append(f"SL: ${sl:.2f} (-{(1-(sl/price))*100:.1f}%)")
        msg = " | ".join(parts)
    else:
        msg = f"ORDER SELL {qty:.6f} {symbol} @ ${price:.2f}"
    log(msg)
    _write_obsidian(f"  - **{msg}**")
    _buffer(f"  - **{msg}**")
    if action == "BUY":
        _buy_lines.append(msg)
    else:
        _sell_lines.append(msg)


def log_skipped(symbol: str, reason: str):
    msg = f"SKIPPED {symbol} — {reason}"
    log(msg)
    _write_obsidian(f"- {msg}")
    _buffer(f"- {msg}")
    _skip_lines.append(msg)


def log_error(msg: str):
    log(f"ERROR: {msg}")
    _write_obsidian(f"- ERROR: {msg}")
    _buffer(f"- ERROR: {msg}")
    _error_lines.append(msg)


def log_scan_end():
    log("=== Scan complete ===")
    _write_obsidian("\n---\n")
    _buffer("\n---\n")
    try:
        _send_discord()
    finally:
        _log_buffer.clear()
        _buy_lines.clear()
        _sell_lines.clear()
        _signal_lines.clear()
        _skip_lines.clear()
        _error_lines.clear()
