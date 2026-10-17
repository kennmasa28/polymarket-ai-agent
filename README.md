# polymarket-ai-agent
This project aims to develop an AI agent that operates on Polymarket around the clock.

## PolyAgent UI (chat & trade)

```bash
pip install streamlit altair pandas
streamlit run viewer/view_app.py
```

Chat with the trading agent in the browser:

- The agent's reasoning and tool calls are shown live while it works, and stay
  available per turn under "🧠 思考とツール" (arguments / results in popovers,
  price charts inline).
- **Orders require approval.** `buy_token` / `sell_token` are declared with
  `needs_approval=True`, so the run pauses and an approval card (side, token,
  amount, current holding) is shown. The order is placed only after
  "✅ 承認して発注"; "❌ 却下" (with an optional reason) tells the agent it was
  declined. The CLI (`python src/main.py`) asks the same question with `[y/N]`.
- The side panel shows the portfolio (refreshed after each order), quick
  actions and this conversation's orders / cost.
- Past conversations can be reopened from "会話履歴"; agent memory is stored in
  `agent_logs/chat_memory.db`.

## Agent logs & log viewer

Every conversation (UI and CLI) is recorded step by step to
`agent_logs/<YYYY-MM-DD>/<session_id>.jsonl` (one JSON event per line, flushed
immediately): user messages, each LLM call (reasoning summaries, requested
tool calls, messages, token usage, latency), every tool call (arguments,
return value, duration, exceptions with traceback), order approvals, final
answers and run errors. Image tool results are saved under
`agent_logs/<date>/images/`. Reasoning summaries are requested via
`REASONING_SUMMARY` in `src/config.py`.

Open the **logview** page in the app's sidebar (or "📊 ログビューアで詳しく見る"
in a conversation) to analyse them:

- **🧵 タイムライン** – turn-by-turn flow of reasoning → tool call → result → answer
- **📊 分析** – token breakdown per LLM call, context growth, latency, Gantt chart, tool stats, cost per turn
- **🔧 ツール** – searchable list of tool calls; select one to see the reasoning that led to it, its arguments and its result
- **💭 推論** – all reasoning summaries with search and the action that followed
- **⚙️ セッション情報 / 🗂️ Raw** – system prompt, tool schemas, raw events
- **🌐 全体** – cross-session summary (daily cost, tool usage, errors)

Enable "ライブ更新" in the sidebar to follow a running session. Set
`POLYVIEWER_LOG_DIR` to read logs from another directory.
