# Doot

**Your personal AI envoy.** A small orchestrator that routes natural-language requests to agents (Gmail, and more later). Talk to it via the CLI; it uses your saved OAuth tokens and an LLM to list, search, and read your mail.

## What it does

- **Auth** — OAuth2 flow for Gmail (and Calendar scope) with a local callback server or paste-URL fallback for dev containers.
- **Gmail agent** — Lists inbox, searches mail, and fetches full messages via the Gmail API.
- **Orchestrator** — Routes your message to the right agent (e.g. “show my last 5 emails” → Gmail; “what’s on my calendar?” → Calendar; “who won the World Cup?” → Web search).
- **Web search agent** — Gemini with Google Search grounding for real-time web lookups and citations.
- **Chat CLI** — One-shot or interactive: ask in plain language and get answers.
- **Telegram bot** — Chat with the same orchestrator from Telegram; shares the global session with the CLI.
- **OpenClaw-style memory** — One shared memory store: `MEMORY.md` (long-term facts and preferences) and `memory/YYYY-MM-DD.md` (daily logs). Loaded at session start; the main (direct) agent has tools to read and write memory (`memory_get`, `memory_search`, `memory_append`). Optional per-agent memory (identity, skills, failures, working) for Gmail and Calendar agents.

## Setup

1. **Clone and install**

   ```bash
   cd doot
   pip install -r requirements.txt
   ```

2. **Environment**

   Create a `.env` file with:

   - `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — from [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → OAuth 2.0 Client (e.g. Desktop app), and add `http://localhost:8080` as a redirect URI.
   - `ANTHROPIC_API_KEY` — for the orchestrator and Gmail/Calendar agents.
   - `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) — for the web search agent (Gemini + Google Search grounding). Get a key from [Google AI Studio](https://aistudio.google.com/apikey).

   Optional: `DOOT_TOKENS_PATH`, `DOOT_SESSION_PATH` (default: `.doot/chat_session.json` in project), `DOOT_MEMORY_DIR` (default: `.doot/` for OpenClaw-style memory files), `DOOT_AUTH_PORT`, `DOOT_AUTH_PASTE_URL=1` (for dev containers), `USER_EMAIL`. For Telegram: `TELEGRAM_BOT_TOKEN` (required for the bot), `TELEGRAM_WEBHOOK_BASE_URL` (e.g. `https://yourdomain.com`) to auto-register the webhook when the server starts.

3. **Authenticate**

   ```bash
   python -m src.cli auth
   ```

   In a dev container, set `DOOT_AUTH_PASTE_URL=1` and paste the redirect URL when prompted.

4. **Customize the bot (optional)**

   Create an `agent_context/` folder in the project root and add `agent_context/agent_context.md`. That file defines the global context given to every agent (Gmail, Calendar, Web Search, direct)—e.g. who you are, your portfolio, tone, and responsibilities.

   - Put any intro or notes at the top; the text **after** the first `---` line is what the bot uses as context.
   - The `agent_context/` folder is in `.gitignore`, so your custom context is not committed.
   - If the file or folder is missing, the bot still runs with no custom context.

5. **Memory (OpenClaw-style, optional)**

   Memory lives under `.doot/` (or `DOOT_MEMORY_DIR`):

   - **`MEMORY.md`** — Long-term facts and preferences. The bot can read and append via tools; you can edit by hand.
   - **`memory/YYYY-MM-DD.md`** — One daily log per day (e.g. `memory/2026-02-26.md`). Append-only; the bot sees today and yesterday at the start of each turn.

   The main (direct) agent has tools: `memory_get` (read a file), `memory_search` (keyword search), `memory_append` (append to MEMORY.md or a daily log). So you can say “remember that I prefer short answers” or “what did we decide about X?” and it will use memory. From the CLI:

   ```bash
   python -m src.cli memory status   # show memory root and which files exist
   python -m src.cli memory search "prefer"   # keyword search over memory
   ```

## Usage

- **One-shot**

  ```bash
  python -m src.cli chat "show me my last 5 emails"
  ```

- **Interactive**

  ```bash
  python -m src.cli chat
  ```

  Then type things like “what’s in my inbox?”, “search for emails from …”, or “read email with id …”. Type `quit` or `exit` to leave.

- **Other commands**

  ```bash
  python -m src.cli auth    # (re)auth Gmail/Calendar
  python -m src.cli check-gemini  # verify Gemini API key (for web search)
  python -m src.cli memory status   # OpenClaw-style memory: show root and files
  python -m src.cli memory search "query"   # keyword search over MEMORY.md and daily logs
  python -m src.cli version # show version
  python -m src.cli --help  # list commands
  ```

- **Run in background**

  To run the webhook server in the background (e.g. so Pub/Sub can reach it without keeping a terminal open):

  ```bash
  python -m src.cli start --background   # or: start -d
  ```

  The PID is written to `~/.doot/doot.pid` (or `DOOT_PID_PATH`). Logs go to `~/.doot/doot.log` (or `DOOT_LOG_PATH`). To stop:

  ```bash
  python -m src.cli stop
  ```

  Expose port 8000 (e.g. `ngrok http 8000` or Tailscale Funnel) and point your Pub/Sub push subscription at your public URL. When a new email triggers the webhook, the `on_gmail_push` hook in `src/webhook.py` runs (no-op by default; you can implement Telegram or other actions there).

- **Gmail Pub/Sub (verify push is working)**

  1. In Google Cloud: create a Pub/Sub topic, grant `gmail-api-push@system.gserviceaccount.com` publish on it, create a **push** subscription with endpoint `https://your-tunnel/webhook/gmail` (e.g. ngrok or Tailscale Funnel). Set `PUBSUB_TOPIC` and `WEBHOOK_URL` in `.env`.
  2. Start the webhook server and expose it (e.g. `ngrok http 8000` pointing at your machine):

     ```bash
     python -m src.cli webhook
     ```

  3. Register Gmail to push to your topic:

     ```bash
     python -m src.cli watch-gmail
     ```

  4. Send yourself a test email; you should see a POST to `/webhook/gmail` and a log line with `emailAddress` and `historyId`.

- **Telegram**

  Set `TELEGRAM_BOT_TOKEN` in `.env` (from [@BotFather](https://t.me/BotFather)). With the webhook server running and reachable at a public HTTPS URL, set `TELEGRAM_WEBHOOK_BASE_URL` to that base URL (e.g. `https://your-ngrok-host.ngrok.io`); on startup the server will register `POST /webhook/telegram` as the bot’s webhook. You can then chat with your bot in Telegram; it uses the same global session as the CLI. See **[docs/telegram-setup.md](docs/telegram-setup.md)** for the full walkthrough.

- **[docs/telegram-setup.md](docs/telegram-setup.md)** — Step-by-step: create a Telegram bot, set `TELEGRAM_BOT_TOKEN`, webhook vs polling, and chat with Doot from Telegram (shared global session with CLI).
- **[docs/setup-gmail-pubsub.md](docs/setup-gmail-pubsub.md)** — Step-by-step: auth, webhook, ngrok, Pub/Sub topic & push subscription, `watch-gmail`, and how to verify new-email webhooks are working.

## Project layout

```
agent_context/        # (optional, gitignored) agent_context.md = global context for all agents
agent_memory/         # (optional) per-agent identity/skills/failures/working for Gmail, Calendar, etc.
.doot/                # session, memory (default: chat_session.json, MEMORY.md, memory/YYYY-MM-DD.md)
src/
  cli.py              # Entrypoint: auth, chat, start (--background), stop, webhook, watch-gmail, memory, version
  webhook.py          # FastAPI: POST /webhook/gmail, POST /webhook/telegram; Gmail push + Telegram bot
  session.py          # Global chat session load/save (CLI + Telegram)
  orchestrator_runner.py  # invoke_orchestrator(messages) → (result, last_ai_text)
  graph/
    orchestrator.py   # Router + graph (router → gmail | calendar | websearch | direct → END)
  memory/             # OpenClaw-style: claw_store.py, claw_tools.py; per-agent: service.py, loader.py, saver.py
  agents/
    gmail/
      auth.py         # OAuth2 credentials (tokens in ~/.doot/tokens.json)
      client.py       # Gmail API client (list, get messages)
      tools.py        # LangChain tools (gmail_list_inbox, gmail_search, gmail_get_email)
      agent.py        # ReAct agent (Claude + Gmail tools)
    calendar/         # Google Calendar (list/create/delete events)
    websearch/        # Gemini + Google Search grounding (client.py, agent.py)
```

## License

MIT
