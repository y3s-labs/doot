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

## Project layout

```
src/
  cli.py              # Entrypoint: auth, chat, version
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
