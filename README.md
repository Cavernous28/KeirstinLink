# KeirstinLink

A lightweight bridge and launcher system for running coordinated, multi-instance Hermes Agent sessions. KeirstinLink lets a **master** Hermes instance delegate work to one or more **slave** Hermes instances — locally or on remote machines — while keeping a clear safety boundary around approvals, secrets, and state.

## What it is

- **Master/Slave coordinator**: One primary Hermes session acts as the orchestrator; slave instances receive focused tasks and return summaries.
- **Remote Hermes bridge mode**: Slaves can run on other hosts and connect back to the master via a simple HTTP/WebSocket bridge or the Hermes native delegation tools.
- **Launcher scaffolding**: Cross-platform start scripts, dependency manifests, and a design doc so the project is immediately readable and iterate-able.
- **Safety-first defaults**: No auto-approvals, no persistent background agents unless explicitly requested, and secrets stay in user-managed `.env` files.

## Repository layout

```
KeirstinLink/
├── README.md                 # This file
├── DESIGN.md                 # Architecture, master/slave model, remote bridge, safety rules
├── requirements.txt          # Python dependencies
├── package.json              # Node-side bridge dependencies (optional WebSocket/API bridge)
├── pyproject.toml            # Python project metadata
├── start.bat                 # Windows cmd launcher
├── start.sh                  # POSIX/bash launcher
├── start-master.bat          # Windows cmd: launch the master instance
├── start-slave.bat           # Windows cmd: launch a slave instance
├── .env.example              # Example environment variables (copy to .env and fill in)
└── src/
    ├── __init__.py
    ├── bridge.py             # Core bridge server/client stubs
    ├── master.py             # Master orchestrator stub
    ├── slave.py              # Slave worker stub
    └── config.py             # Shared configuration helpers
```

> **Note:** This is a skeleton. The bridge and master/slave code are intentionally thin — the goal is to establish structure, conventions, and a shared design document before filling in behavior.

## Quick start

### 1. Configure the environment

Copy `.env.example` to `.env` and fill in the values. KeirstinLink never reads credentials from anywhere else.

```bash
cp .env.example .env
# Edit .env with your API keys and host names.
```

### 2. Install dependencies

**Python:**

```bash
pip install -r requirements.txt
```

**Node bridge (only if using the optional WebSocket bridge):**

```bash
npm install
```

### 3. Launch

**Windows (cmd):**

```bat
start-master.bat
start-slave.bat
```

**POSIX / git-bash:**

```bash
./start.sh master
./start.sh slave
```

## Design and safety

See [DESIGN.md](DESIGN.md) for:

- Master/slave responsibilities and message flow
- Remote Hermes bridge mode (HTTP/WebSocket bridge vs. native `delegate_task`)
- Safety rules, approval boundaries, and how secrets are handled
- How this relates to Keirstin's existing continuity and collaboration conventions

## Contributing / iterating

This repo is meant to be edited in place. Before adding behavior:

1. Update `DESIGN.md` if the architecture changes.
2. Keep launcher scripts simple and comment any new environment variables.
3. Do not commit `.env` files — the repository ignores them by default.

## License

MIT (placeholder — update when the project matures).
