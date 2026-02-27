# Scheduled tasks

When the webhook server is running, the **heartbeat** (every 30 minutes) not only runs the HEARTBEAT.md checklist but also **checks the current time** and **kicks off any scheduled tasks** that are due. So you can run a daily report at 7am (or other long-running tasks at various times) without a separate cron or sleep-until loop.

## How it works

1. On each heartbeat tick, after running the HEARTBEAT.md checklist, the server loads the **schedule** from `.doot/schedule.json` (or `DOOT_SCHEDULE_PATH`).
2. It gets the current time in the configured timezone (`DOOT_SCHEDULE_TZ`, default `America/New_York`).
3. For each task whose scheduled time has **passed today** and that has **not yet run today** (tracked in `.doot/schedule_last_run.json`), it starts the task in the background (`asyncio.create_task`).
4. The task runs (e.g. report: orchestrator with REPORT_PROMPT.md, multi-step web search), then the result is saved and delivered (email, file, optional Telegram).

## Schedule file

- **Path:** `.doot/schedule.json` (or set `DOOT_SCHEDULE_PATH`).
- **Format:** JSON array of objects with `time`, `task_id`, `recurrence`, `delivery`.

Example:

```json
[
  {
    "time": "07:00",
    "task_id": "report",
    "recurrence": "daily",
    "delivery": "email"
  }
]
```

You can add more entries (e.g. another task at 14:00) to run different long-running tasks at different times.

## Report task

The built-in **report** task:

1. Loads the prompt from `.doot/REPORT_PROMPT.md` (or `DOOT_REPORT_PROMPT_PATH`). The prompt can use `[location]` or `{location}`, replaced by `DOOT_REPORT_LOCATION` (default `Providence, RI`).
2. Invokes the orchestrator with that prompt only (no chat session). The orchestrator plans and runs multiple steps (e.g. websearch for weather, websearch for police activity, then compile).
3. Saves the full report to `.doot/reports/YYYY-MM-DD.md`.
4. Sends the report by **email** via the Gmail API (recipient: `DOOT_REPORT_TO_EMAIL` or `USER_EMAIL`).
5. Optionally sends a one-line summary to Telegram (“Daily report sent to your email and saved to .doot/reports/YYYY-MM-DD.md”).
6. Records that the report ran today so it does not run again until tomorrow.

## Configuration

| Env | Default | Description |
|-----|---------|-------------|
| `DOOT_SCHEDULE_TZ` | `America/New_York` | Timezone for schedule times. |
| `DOOT_SCHEDULE_PATH` | `.doot/schedule.json` | Path to schedule file. |
| `DOOT_REPORT_TO_EMAIL` | `USER_EMAIL` | Email address to send the report to. |
| `DOOT_REPORT_LOCATION` | `Providence, RI` | Location used in the report prompt (weather, police activity). |
| `DOOT_REPORT_PROMPT_PATH` | `.doot/REPORT_PROMPT.md` | Path to the report prompt file. |

Gmail send uses the same OAuth credentials as the Gmail agent (`gmail.modify` scope includes send). Ensure you have run `python -m src.cli auth` so sending is allowed.

## Adding more tasks

The schedule file can list multiple tasks. Currently only `task_id: "report"` is implemented. To add more task types, you would extend the webhook code to handle other `task_id` values (e.g. load a different prompt, different delivery). The schedule format is already extensible: add another object with `time`, `task_id`, `recurrence`, and `delivery`.
