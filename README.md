# CSRP Utilities

CSRP Utilities is a custom Discord operations platform for California State Roleplay. It combines a `discord.py` bot, a Flask backend, and a Next.js dashboard into one repo so staff can manage moderation, ERLC workflows, evidence, staff actions, embeds, and internal tooling from Discord or the web.

## What This Repo Contains

- A Discord bot with hybrid prefix and slash commands
- A Flask backend for dashboard APIs, Discord OAuth, evidence handling, and internal endpoints
- A Next.js frontend that proxies requests to the Flask backend
- Persistent local storage for settings, modlogs, evidence metadata, themes, and other runtime state
- Internal utilities for Sentry lookups, sales lookups, Docker/database actions, and Codex-triggered prompts

## High-Level Architecture

The main production entry point is [`bot.py`](./bot.py), which:

- imports the Discord bot from [`bot_app.py`](./bot_app.py)
- starts the Flask dashboard in a background thread through [`dashboard_web.py`](./dashboard_web.py)
- starts the Discord bot process

The web stack is split in two parts:

- Flask backend on port `4000` by default
- Next.js dashboard on port `3000` by default

The Next app forwards dashboard API calls through [`app/api/[...path]/route.ts`](./app/api/%5B...path%5D/route.ts) and [`lib/backendProxy.ts`](./lib/backendProxy.ts) to the Flask backend.

## Core Features

### Discord bot

- Moderation commands: warn, kick, ban, unban, mute, unmute, infract, modlog lookup and clearing
- ERLC tools and custom ERLC actions
- Staff management: retire, reinstate, demote, staff feedback, blacklist controls
- Training workflows and training result posting
- Session management and live session info
- Hits and hostage-related workflows
- Embed creation utilities
- Utility commands such as help, server info, dashboard link, status, support, partnership, sales, Sentry lookup, and API helpers
- Fun/media commands including reminders, trivia, avatar, TTS, dog/cat images, and music playback
- Owner/admin tooling including command blacklists and a Discord-based console via Jishaku

### Dashboard

- Discord OAuth login
- Permission-gated staff dashboard
- Moderation actions from the browser
- Staff actions and infractions workflows
- ERLC server/player visibility and custom ERLC actions
- Embed sending tools
- Theme marketplace and custom theme management
- Evidence logging and evidence request flows
- Modlog inspection and cleanup
- Command blacklist management
- Bot status and message actions
- Settings and access control management

### Internal/API endpoints

- `/v1/generateAPI`
- `/v1/logs`
- `/v1/uptime`
- `/v1/latency`

These are served by the Flask app and use token-based authentication from environment variables or `APIKeys.txt`.

## Tech Stack

### Backend

- Python 3
- `discord.py`
- Flask
- FastAPI is listed in dependencies, but the current runtime in this repo is Flask-based
- `aiohttp`, `requests`, `python-dotenv`, `sentry-sdk`

### Frontend

- Next.js
- React
- TypeScript
- `lucide-react`
- `react-icons`

### Storage

- JSON files for lightweight state
- SQLite databases for themes/modlogs and other local data
- Uploaded dashboard evidence files stored under `dashboard_evidence_uploads/`

## Repository Layout

```text
.
|-- bot.py                     # Main app entry point
|-- bot_app.py                 # Discord bot setup, cog loading, console tooling
|-- dashboard_web.py           # Flask dashboard backend and OAuth/API routes
|-- server.py                  # Dashboard-only launcher
|-- config.py                  # Environment loading and permission constants
|-- cogs/                      # Discord bot features, grouped by domain
|-- app/                       # Next.js App Router frontend
|-- lib/                       # Frontend proxy helpers and Codex runner support
|-- templates/                 # Flask-rendered templates
|-- static/                    # Flask static assets
|-- requirements.txt           # Python dependencies
|-- package.json               # Node/Next dependencies
|-- .env.example               # Environment variable template
`-- update.sh                  # Pull/build/restart helper for PM2-based deploys
```

## Important Runtime Files

The repo uses several local files for state and operational data. Many of these are ignored by Git and created at runtime.

- `afk.json`
- `guild_settings.json`
- `modlogs.json` and `modlogs.sqlite3`
- `dashboard_permissions.json`
- `dashboard_evidence_logs.json`
- `dashboard_evidence_uploads/`
- `dashboard_themes.sqlite3`
- `APIKeys.txt`
- `log.txt` and `logs.txt`

## Prerequisites

Before running the project, make sure you have:

- Python 3.11+ recommended
- Node.js 20+ recommended
- `npm`
- A Discord bot application with the required intents enabled
- A Discord OAuth application using the same app or a compatible app configuration
- Access to any external services your deployment expects, such as:
  - PRC/ERLC API credentials
  - Sentry credentials
  - any internal logging or sales endpoints referenced by the bot

## Installation

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd "CSRP Utilites"
```

### 2. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Install Node dependencies

```bash
npm install
```

### 4. Create your environment file

```bash
cp .env.example .env
```

Then fill in the required values.

## Environment Variables

The repo ships with an [`.env.example`](./.env.example). The most important variables are:

### Discord bot

- `BOT_TOKEN`: Discord bot token
- `SERVER_KEY`: PRC/ERLC server key
- `IS_TESTING`: Optional testing-mode switch

### Sentry

- `SENTRY_DSN`
- `SENTRY_API_TOKEN`
- `SENTRY_API_KEY`

### Internal services

- `LOG_SERVER_AUTH`
- `API_GENERATE_AUTH`
- `INTERNAL_API_KEY`
- `COOKIE_API_AUTH`
- `ERM_API_AUTH`

### Dashboard/OAuth

- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DASHBOARD_PUBLIC_ORIGIN`
- `DASHBOARD_BACKEND_ORIGIN`
- `DISCORD_REDIRECT_URI`
- `DASHBOARD_SECRET_KEY`
- `DASHBOARD_ENV`
- `DASHBOARD_STAGING_ACCESS_ROLE_ID`

### Recommended local development values

```env
DASHBOARD_PUBLIC_ORIGIN=http://127.0.0.1:3000
DASHBOARD_BACKEND_ORIGIN=http://127.0.0.1:4000
DISCORD_REDIRECT_URI=http://127.0.0.1:3000/api/auth/callback
```

## Running the Project

There are two practical ways to run the repo, depending on whether you want the full application or only the dashboard.

### Full application: bot + Flask + Next.js

This is the main path used by the repo.

First build the Next.js app:

```bash
npm run build
```

Then start the bot:

```bash
python3 bot.py
```

This will:

- launch the Next.js production server through `npm run start`
- launch the Flask backend on port `4000`
- connect the Discord bot

### Dashboard-only mode

If you want to run the web stack without connecting the bot entry point directly:

```bash
npm run build
python3 server.py
```

Note that many dashboard actions still depend on a live Discord bot being attached. `server.py` is mainly useful when working on the dashboard stack itself, not as a full replacement for `bot.py`.

### Frontend development workflow

`server.py` starts both Flask and the production Next server, so do not use it together with `npm run dev`.

For frontend iteration, run only the Flask backend in one terminal:

```bash
python3 -c "from dashboard_web import app; app.run(port=4000, debug=False)"
```

Then run the Next.js development server in another:

```bash
npm run dev
```

If you use this workflow, confirm your env values still point the frontend proxy at the Flask backend on `4000`.

## Default Ports

- Next.js dashboard: `3000`
- Flask backend: `4000`

These can be influenced by environment variables such as:

- `NEXT_DASHBOARD_HOST`
- `NEXT_DASHBOARD_PORT`
- `DASHBOARD_PUBLIC_ORIGIN`
- `DASHBOARD_BACKEND_ORIGIN`

## Discord Command Model

The bot uses:

- prefix commands with `-`
- hybrid commands that also register as slash commands
- grouped commands for areas like `api`, `training`, `erlc`, `embed`, `hit`, and `hostage`

## Cog Overview

The following cogs are loaded by default from [`bot_app.py`](./bot_app.py):

- `cogs.moderation`
- `cogs.erlc`
- `cogs.sessions`
- `cogs.training`
- `cogs.fun`
- `cogs.music`
- `cogs.utility`
- `cogs.embed_creator`
- `cogs.admin`
- `cogs.hits`
- `cogs.events`
- `cogs.settings`
- `cogs.staffmgmt`

### Notable command groups

- `moderation`: modlogs, warn, kick, ban, unban, mute, unmute, infract, lookup
- `utility`: ping, uptime, help, dashboard, serverinfo, userinfo, docker-exec, codex, sales, sentry, partnership
- `staff management`: retire, reinstate, demote, staff feedback flows
- `training`: pass/fail commands and training result workflows
- `music`: basic YouTube queue and playback controls
- `admin`: blacklist management for command/report usage

## Dashboard Routes

### User-facing routes

- `/`
- `/dashboard`
- `/evidence/[code]`
- `/evidence-request/[code]`

### Backend-auth routes

- `/login`
- `/auth/callback`
- `/logout`

### API routes

- `/api/session`
- `/api/dashboard`
- `/api/themes`
- `/api/evidence`
- `/api/evidence/<evidence_id>`
- `/api/evidence-requests/<request_id>`
- `/api/evidence-requests/<request_id>/submit`
- `/actions/<action>`

## Permissions and Access Control

Permissions are controlled through a mix of:

- Discord role IDs and user IDs defined in [`config.py`](./config.py)
- dashboard access configuration in `dashboard_permissions.json`
- guild-specific settings stored in `guild_settings.json`

The dashboard also supports:

- full access roles
- feature-level access control
- optional staging-only access via `DASHBOARD_ENV=staging`

## Jishaku and Console Tooling

On startup, the bot attempts to load `jishaku`. If available, it registers extra subcommands including:

- `jsk restart`
- `jsk console`

The custom console view allows an authorized operator to run shell commands from Discord in an interactive PTY session. Treat this as highly privileged functionality.

## Logging and Observability

- Sentry is initialized in [`bot_app.py`](./bot_app.py)
- bot logs are written to `log.txt`
- dashboard/internal log endpoints also reference `logs.txt`
- several features rely on persisted JSON/SQLite state for auditability and staff workflows

## Deployment Notes

This repo appears structured for a long-running Linux host with PM2 or a similar process manager.

The included [`update.sh`](./update.sh) does:

```bash
git pull
npm run build
pm2 restart bot
```

That implies a typical deployment flow of:

1. Install Python and Node dependencies on the host.
2. Build the Next.js app.
3. Run the bot under PM2 or another supervisor.
4. Expose the Next dashboard publicly.
5. Keep the Flask backend reachable by the dashboard proxy.

## Security Notes

- Never commit a real `.env`.
- `APIKeys.txt` contains live API keys and should stay local.
- The dashboard secret key must be set to a strong value outside development.
- Discord OAuth redirect URIs must exactly match your deployment URL.
- The Discord console/Jishaku features should be restricted tightly.
- This repo stores operational data locally; back up the relevant JSON, SQLite, and upload directories if the deployment matters.

## Troubleshooting

### `npm was not found`

The dashboard launcher in `dashboard_web.py` calls `npm` directly. Install Node.js and make sure `npm` is on `PATH`.

### OAuth login redirects incorrectly

Check:

- `DASHBOARD_PUBLIC_ORIGIN`
- `DISCORD_REDIRECT_URI`
- the redirect URL configured in the Discord developer portal

### Dashboard loads but actions fail

Common causes:

- the bot is not running or not attached
- missing Discord OAuth env vars
- missing internal API tokens
- insufficient dashboard feature permissions

### Frontend starts but API calls return `503`

The Next app could not reach the Flask backend. Verify:

- Flask is running on `4000`
- `NEXT_PUBLIC_BACKEND_ORIGIN` or `DASHBOARD_BACKEND_ORIGIN` is correct
- no proxy or firewall rule is blocking local access

## Current Gaps and Cleanup Opportunities

This repo currently includes large runtime artifacts and local state in the working tree outside the ignore rules you would normally expect for a cleaner app repo. If you plan to maintain or publish it more broadly, worthwhile follow-up work includes:

- separating runtime data from source code
- documenting every required external API dependency
- adding a proper process manager config
- adding automated tests
- standardizing development vs production startup commands

## License

No license file is currently present in this repository. If this project is meant to be shared outside the current organization, add an explicit license.
