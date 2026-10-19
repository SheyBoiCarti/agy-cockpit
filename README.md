<div align="center">

# Antigravity Cockpit

**See what your agents are doing. Review their actions. Bring in a council.**

A local web interface for Antigravity, with streaming conversations, tool approvals, file diffs, and multi-agent deliberation.

[Quick start](#quick-start) · [AI Council](#ai-council) · [Configuration](#configuration) · [Development](#development)

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
[![Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)

</div>

## Why Cockpit?

Agent work spans conversations, commands, file edits, and decisions that need your input. Cockpit brings those activities into one view: follow a run as it happens, inspect its output, and respond when a tool needs approval.

When a problem needs several perspectives, open the **AI Council**. Members analyze a topic independently, critique each other's proposals, and pass their findings to a synthesizer for a final assessment.

The application runs on your machine. Agent requests use your configured Antigravity runtime and account.

> **Bring your own Antigravity access.** This is an independent project. It does not provide model access, credentials, or API quota. Local application storage does not make model inference offline.

## Features

| Capability | What it gives you |
| --- | --- |
| **Live execution timeline** | Streamed responses, reasoning when emitted by the runtime, tool calls, and run status |
| **Tool approvals** | Approve or reject actions under policies that request confirmation; pending approvals expire after five minutes |
| **Workspace conversations** | Project conversations backed by SQLite metadata and persisted agent sessions |
| **Inspection drawer** | File diffs, terminal output, subagent activity, and generated artifacts alongside the conversation |
| **Context and attachments** | Workspace file mentions with `@` and supported attachment uploads |
| **Account model catalog** | Model selection populated by your authenticated Antigravity CLI |
| **AI Council** | Broadcasts, individual member questions, roll-call votes, and staged deliberation |
| **Reconnect support** | Event replay and state synchronization after a disconnected browser session |

## Requirements

| Requirement | Purpose |
| --- | --- |
| Python 3.11 or newer | Run the backend and command-line tools |
| Antigravity CLI (`agy`) on your `PATH` | Account model discovery, CLI execution, and Council execution |
| Authenticated Antigravity account with model access | Run live agent requests |
| `google-antigravity==0.1.16` | Python SDK dependency, installed with this project |
| Node.js and npm | Rebuild the frontend when changing its source |
| Git | Clone the repository and inspect Git-based diffs |

Built frontend assets are included in `agy_cockpit/backend/static/`, so Node.js is not required for a normal launch from this checkout.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/SheyBoiCarti/Antigravity.git
cd Antigravity
```

### 2. Create a virtual environment

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Use Python 3.11 or newer for either command.

### 3. Install the application

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

### 4. Check your Antigravity account

With the Antigravity CLI installed and authenticated, confirm that it can list your models:

```bash
agy models
```

The browser uses this catalog to validate model selections before starting a run. If discovery fails, check your CLI installation and login, then use **Refresh models** in the cockpit.

### 5. Launch

```bash
agy-cockpit --workspace .
```

The server starts at `http://127.0.0.1:8080` and opens your browser with an authenticated launch URL. To work on another project, pass its directory:

```bash
agy-cockpit --workspace /path/to/your/project
```

You can also use the repository launchers: `start.bat` in Windows Command Prompt, `.\start.ps1` in PowerShell, or `bash start.sh` on macOS/Linux. Pass `--workspace` explicitly when you want a project other than this repository.

## Using the cockpit

1. Open or select a workspace and create a conversation.
2. Select a model from the discovered account catalog and choose a tool policy.
3. Enter a prompt, optionally adding file mentions or attachments.
4. Follow the live timeline and respond to approval requests as needed.
5. Use the side drawer to inspect diffs, command output, subagents, artifacts, or the Council.

Council members in the browser use the selected conversation model and tool policy. Deliberation gathers independent perspectives, asks members to critique those perspectives, and produces a final synthesis.

## AI Council

Use the Council to examine architecture decisions, compare implementation approaches, or review a proposal from several roles. Personas include an Architect, Security reviewer, and Pragmatist, with additional roles available for larger councils.

A deliberation has three stages:

```text
Your topic
    │
    ▼
Independent perspectives → Peer critique → Final synthesis
```

In the browser, open the Council in the side drawer. Members use the current conversation's model and tool policy. You can also broadcast a question, address one member, or request a roll-call vote.

### Terminal usage

The package also installs `agy-council` for terminal-based Council sessions:

```bash
# Start an interactive council with three members
agy-council --agents 3

# Deliberate on a topic and exit
agy-council --agents 3 --topic "Review the tradeoffs of this architecture"

# Vote on a motion and exit
agy-council --vote "Add a caching layer to this service"
```

Use `--model` to select a model slug available to your account and `--workspace` to set project context. Run `agy-council --help` for all options.

Interactive commands include `/members`, `/all <message>`, `/deliberate <topic>`, `/vote <motion>`, `@<Member> <message>`, and `/exit`.

## Configuration

```bash
# Use a different port without opening a browser
agy-cockpit --workspace . --port 9090 --no-open

# Store application data in a custom directory
agy-cockpit --workspace . --data-dir /path/to/cockpit-data
```

| Option | Default | Description |
| --- | --- | --- |
| `-w`, `--workspace` | Workspace picker | Initial project directory |
| `-p`, `--port` | `8080` | Local server port |
| `--host` | `127.0.0.1` | Loopback interface; also accepts `localhost` or `::1` |
| `--data-dir` | `~/.agy-cockpit` | Database, sessions, attachments, and logs |
| `--no-open` | Disabled | Print the launch URL without opening a browser |
| `--token` | Randomly generated | Set an explicit session authentication token |
| `-v`, `--version` | — | Print the application version |

### Execution adapters

The backend automatically selects CLI execution when `agy` is available and either CLI OAuth credentials are present or `GEMINI_API_KEY` is unset. Otherwise, it selects the Python SDK adapter. A failed CLI turn may fall back to the SDK when `GEMINI_API_KEY` is set.

Set `AGY_COCKPIT_ADAPTER` to `cli` or `sdk` to override this selection. SDK execution uses `GEMINI_API_KEY`; browser model discovery and Council execution still require the CLI.

## Local data and security

The cockpit binds to a loopback interface and authenticates browser connections with a launch token. Its backend includes WebSocket origin checks, workspace path validation, and sandboxed artifact previews.

By default, local state lives in `~/.agy-cockpit/`:

```text
~/.agy-cockpit/
├── cockpit.db    # Application metadata and event history
├── sessions/     # Persisted agent sessions
├── attachments/ # Uploaded context
└── logs/         # Application logs
```

Keep launch URLs and tokens private: they grant access to a local control surface that can operate on your workspace. Local storage does not make model inference offline; prompts and context are sent through your configured model runtime.

## How it fits together

```text
Browser · React + TypeScript + Tailwind CSS
                     │
              HTTP + WebSocket
                     │
Local server · FastAPI + SQLite
                     │
        Antigravity CLI / Python SDK
                     │
        Your configured model service
```

The backend manages conversations, run events, approvals, and workspace access. The CLI and SDK adapters perform model execution; Council members execute through the CLI.

## Development

Install the development dependencies from the repository root:

```bash
python -m pip install -e ".[dev]"
```

Rebuild the frontend after changing its source:

```bash
cd agy_cockpit/frontend
npm ci
npm run build
```

The build checks TypeScript and writes the production bundle to `agy_cockpit/backend/static/`. Restart the cockpit and reload the browser to use the rebuilt interface.

Run the Python test suite from the repository root:

```bash
python -m pytest tests/ -v
```

For browser tests, install the optional dependencies and Chromium:

```bash
python -m pip install -e ".[dev,test-browser]"
python -m playwright install chromium
python -m pytest tests/e2e/ -v
```

The tests cover backend behavior, transport and security, CLI integration, Council execution, and browser scenarios. Live model access depends on your own runtime and account; automated tests are not a guarantee of account compatibility.

### Repository layout

```text
agy_cockpit/
├── cli.py              # Cockpit launcher
├── backend/            # FastAPI, WebSocket transport, services, and SQLite storage
│   └── static/         # Built browser assets
├── council/            # Council orchestration, personas, and terminal interface
└── frontend/           # React, TypeScript, Vite, and Tailwind CSS source
tests/                  # Backend, protocol, integration, Council, and browser tests
spikes/sdk_contract/    # SDK contract exploration scripts
```

## Troubleshooting

- **Models are unavailable:** Run `agy models` in the same environment as the server. Resolve CLI or account errors, then refresh models in the UI.
- **The default port is busy:** Launch with `--port 9090` or another free local port.
- **The browser cannot authenticate:** Open the full token-bearing URL printed by the current server process.
- **The interface is missing or outdated:** Run `npm ci` and `npm run build` in `agy_cockpit/frontend`, then restart and reload.
- **An agent cannot execute:** Check CLI authentication, model availability, and the selected tool policy. For SDK execution, also check `GEMINI_API_KEY`.

## Contributing

Bug reports and focused pull requests are welcome. Include reproduction steps, your operating system, Python version, and the relevant error output. Remove credentials, launch tokens, and private workspace content before sharing logs.

For code changes, describe the resulting behavior and run the checks relevant to the affected area. Rebuild the frontend when changing the browser interface.

## License

Licensed under the [Apache License 2.0](LICENSE).
