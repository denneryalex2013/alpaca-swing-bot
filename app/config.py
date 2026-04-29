import os

# Watchlist — comma separated via env var or use defaults
WATCHLIST = os.getenv(
    "WATCHLIST",
    "AAPL,MSFT,NVDA,TSLA,AMZN,META,AMD,GOOGL,SPY,QQQ"
).split(",")

# Position sizing
TRADE_SIZE_PCT = float(os.getenv("TRADE_SIZE_PCT", "0.20"))   # 20% of account equity
MAX_TRADE_SIZE = float(os.getenv("MAX_TRADE_SIZE", "500"))     # hard cap per trade
MAX_POSITIONS  = int(os.getenv("MAX_POSITIONS", "3"))          # max concurrent positions
MIN_TRADE_USD  = float(os.getenv("MIN_TRADE_USD", "10"))       # Alpaca notional minimum floor

# Risk management
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.10"))  # 10% take profit
STOP_LOSS_PCT   = float(os.getenv("STOP_LOSS_PCT",   "0.04"))  # 4% stop loss

# Indicator settings
EMA_SHORT          = int(os.getenv("EMA_SHORT",           "20"))
EMA_LONG           = int(os.getenv("EMA_LONG",            "50"))
RSI_PERIOD         = int(os.getenv("RSI_PERIOD",          "14"))
RSI_BUY_THRESHOLD  = float(os.getenv("RSI_BUY_THRESHOLD", "55"))
RSI_SELL_THRESHOLD = float(os.getenv("RSI_SELL_THRESHOLD","45"))

# How many calendar days back to fetch for indicator calculation
# 120 days ≈ 84 trading days — comfortable headroom above the default EMA_LONG of 50
BARS_TO_FETCH = int(os.getenv("BARS_TO_FETCH", "120"))

# Obsidian vault path — set locally to write daily trade notes directly to vault
# Leave blank on DigitalOcean (DO logs are the source of truth there)
OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
