# Alpaca Swing Bot

A lightweight Python swing trading bot that runs on DigitalOcean App Platform. Scans a stock watchlist every weekday morning, applies a market pre-filter, then uses a confluence of technical indicators to automatically place fractional orders via the Alpaca API.

---

## How It Works

Every weekday at **9:35 AM ET**, the bot:

1. Fetches account equity, cash, and open positions from Alpaca
2. Runs the **market pre-filter** — checks VIX and SPY trend before evaluating any symbols
3. Evaluates exit signals for all open positions first (sells before buying anything new)
4. Scans the watchlist for BUY signals on symbols not currently held
5. Places fractional market orders for any qualifying BUY signals, attaches a GTC stop-loss
6. Sends a Discord summary and saves equity history for daily delta tracking

---

## Market Pre-Filter

Before any BUY signal is acted on, two market-wide conditions are checked using free Yahoo Finance data (no API key required). **Sells are never blocked** — you can always exit a position regardless of market conditions.

| Condition | Rule |
|---|---|
| VIX > 30 | Block all buys — market is stressed |
| SPY below 50-day MA | Block all buys — broad market in downtrend |

Both checks fail open — if Yahoo Finance is unavailable, trading continues normally.

---

## Signal Strategy

**BUY** requires all three indicators to confirm bullish:

| Indicator | Period | Condition |
|---|---|---|
| EMA crossover | 20 / 50 | Short EMA > Long EMA (0.5% tolerance) |
| RSI | 14 | RSI > 55 |
| VWAP | Rolling 20-day | Price > VWAP |

**SELL** requires any two of three indicators to confirm bearish:

| Indicator | Period | Condition |
|---|---|---|
| EMA crossover | 20 / 50 | Short EMA < Long EMA (0.5% tolerance) |
| RSI | 14 | RSI < 50 |
| VWAP | Rolling 20-day | Price < VWAP |

Exits are signal-driven rather than fixed take-profit targets — stock trends can run further than a fixed percentage allows.

---

## Risk Management

| Setting | Default |
|---|---|
| Trade size | 20% of account equity |
| Max trade size | $500 hard cap |
| Max open positions | 3 |
| Stop loss | 4% GTC safety net (primary exit is signal-based) |

Position sizing compounds automatically — as the account grows, trade size grows with it. Fractional shares mean the full trade size is deployed regardless of share price.

---

## Discord Notifications

A notification is sent after every scan regardless of whether trades were placed. The status embed color tells you at a glance what happened:

| Color | Meaning |
|---|---|
| Green | Trades executed |
| Yellow | Signals evaluated but no trades placed |
| Blue | Quiet scan — no signals found |
| Red | Scan completed with errors |

Embeds sent each scan:

| Embed | Content |
|---|---|
| **Status** | Activity summary, equity with daily delta, open positions with P&L, next scan time |
| **Bought** *(if any)* | Buy orders executed with fill price, qty, stop-loss |
| **Sold** *(if any)* | Sell orders executed |
| **Market Context** | VIX level, SPY price vs 50-day MA |
| **Scan Detail** | Actual BUY/SELL signals found, no-signal asset count, blocked symbols, errors |

---

## Project Structure

```
alpaca-swing-bot/
├── app/
│   ├── config.py       # All settings — configurable via env vars
│   ├── prefilter.py    # Market pre-filter (VIX, SPY MA50)
│   ├── strategy.py     # EMA + RSI + VWAP signal logic
│   ├── logger.py       # Console, Obsidian, and Discord logging
│   └── main.py         # Orchestration and daily scan loop
├── storage/            # Persistent equity history for daily delta
├── deploy.py           # Automated DigitalOcean deployment script
├── test_notify.py      # Send a test Discord notification with mock data
├── Dockerfile
└── requirements.txt
```

---

## Deployment

### Automated (recommended)

1. Copy `.env.example` to `.env` and fill in your credentials
2. Run:

```bash
python deploy.py
```

The script creates or updates the DO app, injects all secrets, and tails the deployment until live.

### Manual (DigitalOcean App Platform)

1. Connect this repo to DigitalOcean App Platform
2. Set component type to **Worker**
3. Set run command to `python -m app.main`
4. Add environment variables (see below)

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALPACA_API_KEY` | Yes | — | Alpaca live trading API key |
| `ALPACA_API_SECRET` | Yes | — | Alpaca live trading API secret |
| `DISCORD_WEBHOOK_URL` | Yes | — | Discord channel webhook URL |
| `DO_TOKEN` | Deploy only | — | DigitalOcean API token (used by deploy.py) |
| `GITHUB_TOKEN` | Deploy only | — | GitHub token with repo scope (used by deploy.py) |
| `WATCHLIST` | No | AAPL,MSFT,NVDA,TSLA,AMZN,META,AMD,GOOGL,SPY,QQQ | Comma-separated symbols |
| `TRADE_SIZE_PCT` | No | 0.20 | Fraction of equity per trade |
| `MAX_TRADE_SIZE` | No | 500 | Hard cap per trade in dollars |
| `MAX_POSITIONS` | No | 3 | Max concurrent positions |
| `STOP_LOSS_PCT` | No | 0.04 | Stop loss percentage for GTC safety net |
| `VIX_BUY_BLOCK_THRESHOLD` | No | 30.0 | Block buys when VIX exceeds this |
| `EMA_SHORT` | No | 20 | Short EMA period |
| `EMA_LONG` | No | 50 | Long EMA period |
| `RSI_BUY_THRESHOLD` | No | 55 | RSI threshold to confirm a buy |
| `RSI_SELL_THRESHOLD` | No | 50 | RSI threshold to confirm a sell |

---

## Requirements

- Python 3.12+
- Alpaca account with live trading enabled
- DigitalOcean account
- Discord server with a webhook configured
