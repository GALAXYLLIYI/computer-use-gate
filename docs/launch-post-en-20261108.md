# Show HN: A default-deny safety gate for Windows desktop agents

> Draft for Hacker News / Reddit / X. Replace `{{DEMO_VIDEO}}`, `{{RELEASE_URL}}`, `{{INSTALL_CMD}}` before posting.

## Short version

AI agents can already click, type, and switch windows on Windows. The hard part is not making them capable — it is stopping them before they click the wrong window, proving what happened, and giving the human a kill switch.

I built **computer-use-gate**, an open-source (Apache-2.0) safety gate for Windows desktop agents.

> The agent does nothing until you allow it. Wrong-target actions are blocked. Every action is verified and replayable.

## What it does

- **Default-deny**: nothing moves until you enter the authorization key and click Authorize on an on-screen prompt. A pass lasts 30 minutes or 60 actions.
- **Lease**: only one agent can drive the keyboard/mouse at a time.
- **Frame credential**: an action must carry a fresh snapshot; a stale screenshot is rejected.
- **Sensitive-window block**: authorization/password dialogs are blocked server-side.
- **Emergency stop**: `Ctrl+Alt+Home` halts everything.
- **Post-action verification**: the screen must change; “no change” and “unobservable” are not success.
- **Evidence chain**: before/after screenshots, hash-chained log, replay video.

## No GPU needed

It reads Windows UI Automation first, then Windows OCR, then browser CDP, then icon-font matching. A vision model is a default-off last resort. A normal laptop is enough.

## What it is not

- Not an unattended bulk-clicking bot
- Not a CAPTCHA/risk-control bypass
- Not Linux/macOS
- Not production SLA (0.x experimental)
- Canvas/games/PDF/Electron without accessibility may be unobservable

## Try it

> v0.1.x requires Windows 10/11 x64 + Python 3.12 + git.

```powershell
{{INSTALL_CMD}}
```

MCP config for Claude Code / Codex / Gemini CLI / Cursor:

```json
{{MCP_CONFIG}}
```

Demo: {{DEMO_VIDEO}}<br>
Repo: {{RELEASE_URL}}

## Why open source

Every Windows desktop agent will need permissions, audit, and rollback. That layer should not be rebuilt by every project.

> Others make the agent able to act. computer-use-gate makes the action governed, verified, and replayable.

If you run agents on Windows, I would love you to break it and tell me where it fails.
