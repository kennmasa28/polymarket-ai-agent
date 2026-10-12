# polymarket-ai-agent
This project aims to develop an AI agent that operates on Polymarket around the clock.

## Agent logs & PolyViewer

`python src/main.py` records every step of the agent to
`agent_logs/<YYYY-MM-DD>/<session_id>.jsonl` (one JSON event per line, flushed
immediately): user messages, each LLM call (reasoning summaries, requested
tool calls, messages, token usage, latency), every tool call (arguments,
return value, duration, exceptions with traceback), final answers and run
errors. Image tool results are saved under `agent_logs/<date>/images/`.

Reasoning summaries are requested via `REASONING_SUMMARY` in `src/config.py`.

To browse and analyse the logs:

```bash
pip install streamlit altair pandas
streamlit run viewer/view_app.py
```

- **🧵 タイムライン** – turn-by-turn flow of reasoning → tool call → result → answer
- **📊 分析** – token breakdown per LLM call, context growth, latency, Gantt chart, tool stats, cost per turn
- **🔧 ツール** – searchable list of tool calls; select one to see the reasoning that led to it, its arguments and its result
- **💭 推論** – all reasoning summaries with search and the action that followed
- **⚙️ セッション情報 / 🗂️ Raw** – system prompt, tool schemas, raw events
- **🌐 全体** – cross-session summary (daily cost, tool usage, errors)

Enable "ライブ更新" in the sidebar to follow a running session. Set
`POLYVIEWER_LOG_DIR` to read logs from another directory.
