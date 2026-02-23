# Gmail Pub/Sub setup: get new-email webhooks working

This guide walks through getting Doot’s webhook receiving Gmail push notifications so you can run proactive actions (e.g. Telegram) when new email arrives.

## Prerequisites

- Python env set up (`pip install -r requirements.txt`)
- `.env` with `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ANTHROPIC_API_KEY`
- Optional for Pub/Sub: `PUBSUB_TOPIC`, `WEBHOOK_URL` in `.env`

---

## 1. Auth

```bash
python -m src.cli auth
```

Complete the Google OAuth flow. Tokens are saved to `~/.doot/tokens.json` (or `DOOT_TOKENS_PATH`). In a dev container, set `DOOT_AUTH_PASTE_URL=1` and paste the redirect URL when prompted.

---

## 2. Start the webhook server

The webhook listens on **port 8000** (or `PORT` in `.env`).

**Foreground (keep terminal open):**

```bash
python -m src.cli start
# or: python -m src.cli
```

**Background:**

```bash
python -m src.cli start --background   # or: start -d
```

- PID file: `~/.doot/doot.pid` (or `DOOT_PID_PATH`)
- Logs: `~/.doot/doot.log` (or `DOOT_LOG_PATH`)
- Stop: `python -m src.cli stop`

---

## 3. Expose port 8000 to the internet

Pub/Sub can only push to a **public URL**. Use a tunnel:

**ngrok:**

```bash
ngrok http 8000
```

Use the HTTPS URL ngrok shows (e.g. `https://inocencia-aiguilletted-cristy.ngrok-free.dev`). Set `WEBHOOK_URL` in `.env` to this base URL if you use it elsewhere.

**Alternatives:** Tailscale Funnel, cloudflared, or any tunnel that gives you a public HTTPS endpoint to `localhost:8000`.

---

## 4. Google Cloud: Pub/Sub topic and push subscription

### 4.1 Create a topic

1. Open [Google Cloud Console](https://console.cloud.google.com/) → **Pub/Sub** → **Topics**.
2. **Create topic** (e.g. ID: `doot-gmail`).
3. After creation, go to the topic → **Permissions** → **Grant access**:
   - Principal: `gmail-api-push@system.gserviceaccount.com`
   - Role: **Pub/Sub Publisher**

### 4.2 Create a push subscription

1. **Pub/Sub** → **Subscriptions** → **Create subscription**.
2. **Subscription ID**: any name (e.g. `doot-gmail-push`). Full name will be `projects/<project-id>/subscriptions/<subscription-id>`.
3. **Select a Cloud Pub/Sub topic**: choose the topic you created (e.g. `projects/doot-488123/topics/doot-gmail`).
4. **Delivery type**: **Push**.
5. **Endpoint URL**: `https://<your-tunnel-host>/webhook/gmail`  
   Example: `https://inocencia-aiguilletted-cristy.ngrok-free.dev/webhook/gmail`
6. Leave **Enable payload unwrapping** unchecked (Doot expects the wrapped Pub/Sub payload).
7. Create the subscription.

### 4.3 Set `.env`

- `PUBSUB_TOPIC=projects/<project-id>/topics/<topic-name>`  
  Example: `PUBSUB_TOPIC=projects/doot-488123/topics/doot-gmail`
- `WEBHOOK_URL=https://<your-tunnel-host>` (optional; for reference)

---

## 5. Register Gmail to push to your topic

With the webhook and tunnel running:

```bash
python -m src.cli watch-gmail
```

You should see: `Watch registered: historyId=... expiration=...`

Gmail will now publish to your Pub/Sub topic when the mailbox changes (e.g. new email). You must call `watch-gmail` again before **expiration** (e.g. once a day); the response shows the expiration timestamp.

---

## 6. Verify it’s working

1. Send yourself a test email (from another address or account).
2. **Webhook terminal or log** (`~/.doot/doot.log` if background): you should see a line like  
   `Gmail push: email=... historyId=... subscription=... messageId=...`
3. **ngrok terminal/dashboard**: you should see a **POST** to `/webhook/gmail` with **200 OK**.

If both show up, the pipeline is working: **Gmail → Pub/Sub → your webhook**.

---

## Optional: proactive actions (e.g. Telegram)

When a push is received, Doot calls the **`on_gmail_push(payload)`** hook in `src/webhook.py`. The hook receives the decoded Gmail notification:

```python
{"emailAddress": "you@example.com", "historyId": "1234567890"}
```

By default the hook is a no-op. To send a Telegram (or run the Gmail agent, etc.), implement your logic inside `on_gmail_push` in `src/webhook.py` (or call into a separate module from there).

---

## Quick checklist

| Step | What to do |
|------|------------|
| 1. Auth | `python -m src.cli auth` |
| 2. Start webhook | `python -m src.cli start` or `start --background` |
| 3. Expose | `ngrok http 8000` (or Tailscale Funnel, etc.) |
| 4. Pub/Sub | Create topic, grant Gmail publish, create **push** subscription with endpoint `https://<url>/webhook/gmail` |
| 5. Watch | `python -m src.cli watch-gmail` |
| 6. Test | Send yourself an email; check webhook log and ngrok for POST `/webhook/gmail` 200 |
