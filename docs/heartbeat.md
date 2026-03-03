# Heartbeat (OpenClaw-style)

When the webhook server is running, Doot runs a **heartbeat** every 30 minutes (configurable via `DOOT_HEARTBEAT_INTERVAL_SEC`). Each heartbeat is one orchestrator turn: the agent reads a checklist, can use Gmail, Calendar, and memory tools, and either replies **HEARTBEAT_OK** (nothing to report) or a short summary of what needs your attention. Only in the latter case is a message sent to Telegram.

You control what the bot checks by editing the checklist file.

## Checklist file

- **Path:** `.doot/HEARTBEAT.md` (or `{DOOT_MEMORY_DIR}/HEARTBEAT.md`).
- **Content:** Markdown or plain text. One or more items the agent should run through each heartbeat (e.g. check email, review calendar).
- **If the file is missing:** A default checklist is used (“Check email and calendar for anything needing attention…”). You can still create `.doot/HEARTBEAT.md` to customize.

The agent is instructed to reply with exactly **HEARTBEAT_OK** when nothing requires your attention; otherwise it summarizes. So you only get a Telegram message when there is something to report.

## Example HEARTBEAT.md

Copy this into `.doot/HEARTBEAT.md` and edit as you like:

```markdown
# Heartbeat checklist

- Check email for urgent or important messages
- Review calendar for events in the next 2 hours
- If nothing needs attention, reply HEARTBEAT_OK
```

You can add or remove bullets (e.g. “Check for pending tasks”, “If idle for 8+ hours, send a brief check-in”). The orchestrator will route to the right agents (Gmail, Calendar, or direct with memory tools) based on the checklist.

## Configuration

| Env | Default | Description |
|-----|---------|-------------|
| `DOOT_HEARTBEAT_INTERVAL_SEC` | `1800` (30 min) | Seconds between heartbeat runs. Set to `0` to disable. |
| `DOOT_MEMORY_DIR` | `.doot/` | Directory containing `HEARTBEAT.md` and memory files. |

Telegram delivery uses the same chat as Gmail push summaries (`TELEGRAM_CHAT_ID` or the last chat that messaged the bot).
