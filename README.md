# Doot

**Your personal AI envoy.** A small orchestrator that routes natural-language requests to agents (Gmail, and more later). Talk to it via the CLI; it uses your saved OAuth tokens and an LLM to list, search, and read your mail.

## What it does

- **Auth** — OAuth2 flow for Gmail (and Calendar scope) with a local callback server or paste-URL fallback for dev containers.
- **Gmail agent** — Lists inbox, searches mail, and fetches full messages via the Gmail API.
- **Orchestrator** — Routes your message to the right agent (e.g. “show my last 5 emails” → Gmail agent).
- **Chat CLI** — One-shot or interactive: ask in plain language and get answers.

## Setup

1. **Clone and install**

   ```bash
   cd doot
   pip install -r requirements.txt
   ```

2. **Environment**

   Create a `.env` file with:

   - `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — from [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → OAuth 2.0 Client (e.g. Desktop app), and add `http://localhost:8080` as a redirect URI.
   - `ANTHROPIC_API_KEY` — for the orchestrator and Gmail agent.

   Optional: `DOOT_TOKENS_PATH`, `DOOT_AUTH_PORT`, `DOOT_AUTH_PASTE_URL=1` (for dev containers), `USER_EMAIL`.

3. **Authenticate**

   ```bash
   python -m src.cli auth
   ```

   In a dev container, set `DOOT_AUTH_PASTE_URL=1` and paste the redirect URL when prompted.

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

## Docs

- **[docs/setup-gmail-pubsub.md](docs/setup-gmail-pubsub.md)** — Step-by-step: auth, webhook, ngrok, Pub/Sub topic & push subscription, `watch-gmail`, and how to verify new-email webhooks are working.

## Project layout

```
src/
  cli.py              # Entrypoint: auth, chat, start (--background), stop, webhook, watch-gmail, version
  webhook.py          # FastAPI server: POST /webhook/gmail; on_gmail_push(payload) hook for proactive actions
  graph/
    orchestrator.py   # Router + graph (router → gmail | direct → END)
  agents/
    gmail/
      auth.py         # OAuth2 credentials (tokens in ~/.doot/tokens.json)
      client.py       # Gmail API client (list, get messages)
      tools.py        # LangChain tools (gmail_list_inbox, gmail_search, gmail_get_email)
      agent.py        # ReAct agent (Claude + Gmail tools)
```

## License

MIT
