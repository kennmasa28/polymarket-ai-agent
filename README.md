# polymarket-ai-agent
This project aims to develop an AI agent that operates on Polymarket around the clock.

## PolyAgent web app (Flask)

```bash
pip install -r requirements.txt
python -m webapp.passwords 'your-password'      # prints a password hash
```

```powershell
$env:POLYAGENT_USERNAME = "admin"               # optional (default: admin)
$env:POLYAGENT_PASSWORD_HASH = 'scrypt:...'     # the printed hash
python -m webapp                                # http://127.0.0.1:8000
```

Options: `python -m webapp --host 0.0.0.0 --port 8000`. When exposing it beyond
localhost, put it behind HTTPS and set `POLYAGENT_SECURE_COOKIE=1`. An existing
`.streamlit/secrets.toml` `[auth]` section and hashes made by the former
`viewer/password_hash.py` are still accepted. The session key is stored in
`instance/secret_key` (or set `FLASK_SECRET_KEY`).

Pages:

- **チャット** – talk to the trading agent. Its reasoning and tool calls stream
  in live (Server-Sent Events) and stay available per turn under
  "🧠 思考とツール". **Orders require approval**: `buy_token` / `sell_token` are
  declared with `needs_approval=True`, so the run pauses on an approval card
  and the order is placed only after "✅ 承認して発注" ("❌ 却下" with an
  optional reason tells the agent it was declined). The side panel shows the
  portfolio, quick actions and this conversation's orders and cost. Past
  conversations are listed on the left; agent memory is stored in
  `agent_logs/chat_memory.db`.
- **トレード** – manual trading: trending events by category or slug / URL
  search, markets with outcome prices and price-history chart, a buy ticket,
  and a holdings table with partial / full sell. Every order is confirmed in a
  dialog before it is sent.
- **ログ分析** – analyse the agent logs (below).

The CLI (`python src/main.py`) runs the same agent in a terminal and asks for
order approval with `[y/N]`.

## Agent logs

Every conversation (web and CLI) is recorded step by step to
`agent_logs/<YYYY-MM-DD>/<session_id>.jsonl` (one JSON event per line, flushed
immediately): user messages, each LLM call (reasoning summaries, requested
tool calls, messages, token usage, latency), every tool call (arguments,
return value, duration, exceptions with traceback), order approvals, final
answers and run errors. Image tool results are saved under
`agent_logs/<date>/images/`. Reasoning summaries are requested via
`REASONING_SUMMARY` in `src/config.py`.

The **ログ分析** page shows:

- **🧵 タイムライン** – turn-by-turn flow of reasoning → tool call → result → answer
- **📊 分析** – token breakdown per LLM call, context growth & latency, Gantt chart, tool stats, cost per turn
- **🔧 ツール** – searchable tool calls; select one to see the reasoning that led to it, its arguments and its result
- **💭 推論** – reasoning summaries with search and the action that followed
- **⚙️ 情報 / 🗂️ Raw** – system prompt, tool schemas, raw events, JSONL download
- **🌐 全体サマリー** – cross-session summary (daily cost, tool usage, errors)

"ライブ更新" follows a running session. Token prices for the cost estimate are
set with 💲 (stored in the browser). Set `POLYVIEWER_LOG_DIR` to read logs from
another directory.

## Polymarket API notes

Positions are read from Data API **v2** (`/v2/positions`); Data API v1 was
retired on 2026-11-02 and answers `410 Gone`. Orders go through the CLOB via
the official `polymarket-client` SDK.
