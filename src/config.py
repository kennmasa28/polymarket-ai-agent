import os

PRIVATE_KEY = os.getenv("METAMASK_PRIVATEKEY1") # Private key of your wallet connecting polymarket
FUNDER = os.getenv("POLYMARKET_ACCOUNT1")       # Polymarket account address (not wallet address)
GEMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
TREAT_EVENT_TAG_LIST = ["trump", "ukraine", "economy", "technology", "japan", "ai", "finance"]
CHAIN_ID = 137
MIN_BUY_TOKENS = 5
MAX_BUY_TOKENS = 10
BUY_BUFFER_RATE = 1.01
SELL_BUFFER_RATE = 0.99
MAX_HIGHER_PRICE = 0.90

# track_top_liquidity
POLL_INTERVAL_SECONDS = 30
TOP_MARKET_COUNT = 200
MARKET_REFRESH_EVERY = 90
GAMMA_PAGE_SIZE = 200
MIDPOINT_BATCH_SIZE = 200
CONSECUTIVE_INCREASE_THRESHOLD = 0.1
CONSECUTIVE_DECREASE_THRESHOLD = 0.07

## OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-5-mini"
