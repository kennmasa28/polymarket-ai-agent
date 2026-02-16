import os

PRIVATE_KEY = os.getenv("METAMASK_PRIVATEKEY1") # Private key of your wallet connecting polymarket
FUNDER = os.getenv("POLYMARKET_ACCOUNT1")       # Polymarket account address (not wallet address)
GEMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
TREAT_EVENT_TAG_LIST = ["trump", "ukraine", "economy", "technology", "japan"]
CHAIN_ID = 137
MIN_BUY_TOKENS = 5
MAX_BUY_TOKENS = 8

## OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-5-mini"
