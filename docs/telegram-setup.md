# Telegram setup: chat with Doot from Telegram

This guide walks through connecting a Telegram bot to Doot so you can chat with the same orchestrator (Gmail agent, etc.) from Telegram. The bot uses the **same global session** as the CLI—one conversation whether you type in the terminal or in Telegram.

## Prerequisites

- Doot is set up and working (auth, `.env` with `ANTHROPIC_API_KEY`, etc.).
- The webhook server can run (e.g. `python -m src.cli webhook`).

---

## 1. Create a bot and get the token

1. Open Telegram and search for **@BotFather**.
2. Send: `/newbot`.
3. Follow the prompts:
   - Choose a **name** for your bot (e.g. "Doot Assistant").
   - Choose a **username** that ends in `bot` (e.g. `doot_myuser_bot`). It must be unique.
4. BotFather replies with a message containing your **token**, e.g.:
   ```
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
5. Copy that token; you will add it to `.env` in the next step.

---

## 2. Add the token to your environment

In your project `.env` file, add:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

Replace the value with the token BotFather gave you. Do not commit this file if it contains secrets.

---

## 3. Choose how Telegram will talk to your server

Telegram can deliver updates in two ways:

| Mode     | Best for        | What you need |
|----------|-----------------|----------------|
| **Webhook** | A server with a public URL | `TELEGRAM_WEBHOOK_BASE_URL` (e.g. `https://yourdomain.com`) |
| **Polling** | Local dev, no public URL   | No base URL; run `doot telegram-poll` (if implemented) |

---

## 4a. Webhook mode (public server)

Use this when your Doot webhook server is reachable at a public HTTPS URL (e.g. same host you use for Gmail Pub/Sub).

1. **Set the base URL** in `.env`:

   ```env
   TELEGRAM_WEBHOOK_BASE_URL=https://your-public-host.com
   ```

   Use the exact base URL (no path, no trailing slash). Example: if your Gmail webhook is `https://abc123.ngrok.io/webhook/gmail`, set:

   ```env
   TELEGRAM_WEBHOOK_BASE_URL=https://abc123.ngrok.io
   ```

2. **Start the webhook server.** On startup, if both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_BASE_URL` are set, Doot will register the Telegram webhook at:

   ```
   {TELEGRAM_WEBHOOK_BASE_URL}/webhook/telegram
   ```

   So Telegram will send all updates to that URL.

3. **Expose port 8000** the same way you do for Gmail (e.g. ngrok, Tailscale Funnel). Your tunnel URL is what you put in `TELEGRAM_WEBHOOK_BASE_URL`.

4. **Run the server:**

   ```bash
   python -m src.cli webhook
   # or: python -m src.cli start
   ```

   Check the logs to confirm the Telegram webhook was set successfully.

---

## 4b. Polling mode (local dev, no public URL)

If you don’t have a public URL (e.g. testing on your laptop), you can run the bot in **polling** mode. The bot process will call Telegram’s API to fetch new messages instead of receiving them via webhook.

1. **Do not set** `TELEGRAM_WEBHOOK_BASE_URL`.
2. **Run the polling command:**

   ```bash
   python -m src.cli telegram-poll
   ```

   This keeps running and processes messages as you send them to your bot. It uses the same global session as the webhook and CLI.

---

## 5. Chat with your bot

1. In Telegram, search for your bot by its **username** (the one you chose in BotFather, e.g. `@doot_myuser_bot`).
2. Start a chat and send a message (e.g. “What’s in my inbox?”).
3. The bot will:
   - Load the global session (same as the CLI),
   - Append your message,
   - Run the orchestrator (Gmail agent, etc.),
   - Save the updated session,
   - Reply with the last AI response.

If something goes wrong, the bot may reply with a short error message; check the server logs for details.

---

## 6. Environment reference

| Variable                    | Required | Description |
|----------------------------|----------|-------------|
| `TELEGRAM_BOT_TOKEN`       | Yes      | Token from BotFather. |
| `TELEGRAM_WEBHOOK_BASE_URL`| No       | Public base URL (e.g. `https://yourdomain.com`). If set, the server will register the webhook at `{base}/webhook/telegram`. Omit for polling-only. |

---

## Troubleshooting

- **Bot doesn’t reply**
  - Ensure the server is running and (in webhook mode) that `TELEGRAM_WEBHOOK_BASE_URL` is correct and the server is reachable at `https://{that_host}/webhook/telegram`.
  - Check logs for errors (e.g. orchestrator or Telegram API errors).

- **Webhook registration fails**
  - Telegram requires HTTPS. Use a tunnel (ngrok, Tailscale Funnel) and set `TELEGRAM_WEBHOOK_BASE_URL` to that HTTPS base URL.
  - Ensure port 8000 is open and the app is listening.

- **Session is empty or different from CLI**
  - The bot uses the same session file as the CLI (e.g. `~/.doot/chat_session.json` or path from `DOOT_TOKENS_PATH`). If you run CLI and bot on different machines or different `DOOT_TOKENS_PATH`, they will have different sessions.

For more on the webhook server and Gmail push, see [setup-gmail-pubsub.md](setup-gmail-pubsub.md).
