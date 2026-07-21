# KeirstinLink Design Document

## Purpose

KeirstinLink is a **LAN-first file sync and transfer tool** for Android, Windows, and Linux. A single **master** device acts as the source of truth; **client** devices pull from it automatically and may propose changes that the master must approve before they are applied.

This document also preserves the original remote-Hermes-bridge idea as a later phase, but the first milestone is safe, simple file sync across home devices.

## Core concepts

### Master

The master is the authoritative device (usually the main home PC). It:

- Keeps the canonical copy of synced folders.
- Serves a file index and accepts pull/propose requests over HTTP.
- Requires explicit approval before applying any change proposed by a client.
- Keeps version snapshots of files so changes can be rolled back.
- Never auto-approves destructive actions.

### Client

A client is any other device (phone, laptop, handheld, Linux box). It:

- Discovers the master on the LAN via UDP broadcast and/or mDNS.
- Pulls missing or changed files from master automatically on startup/schedule.
- Can propose a changeset to master; the changes land in a `pending-review/` queue.
- Never pushes changes to master directly.

### Remote Hermes bridge mode (Phase 2)

After the sync layer is solid, the same secure device-to-device tunnel can carry Hermes API calls so a travel device can proxy agent commands back to the home PC. See `DESIGN.md` history or the `cross-device-file-sync` skill for the original bridge design.

## Message flow

```
User -> Master Hermes
         |
         | 1. Decide to delegate
         v
   +-----------+
   |  Master   | --(task JSON)--> Slave A (local or remote)
   |  Hub      | --(task JSON)--> Slave B (remote bridge)
   +-----------+
         ^
         | 2. Summary / artifact returned
         v
   Master Hermes -> User
```

### Task payload (v1 schema)

```json
{
  "task_id": "kl-<uuid>",
  "role": "slave",
  "goal": "Describe the task in one paragraph.",
  "context": {
    "workspace": "C:\\Users\\cbaxt\\git\\KeirstinLink",
    "input_file": null,
    "expected_output": "path/to/result.md"
  },
  "toolsets": ["terminal", "file", "search"],
  "constraints": {
    "max_turns": 30,
    "allow_destructive": false,
    "auto_approve": false,
    "timeout_seconds": 600
  },
  "callback_url": "http://master-host:7788/callback"
}
```

### Result payload (v1 schema)

```json
{
  "task_id": "kl-<uuid>",
  "status": "success | partial | failure | cancelled",
  "summary": "Plain-language outcome.",
  "artifacts": ["path/to/result.md"],
  "logs": "...
}
```

## Safety rules

These rules are non-negotiable. They override any default "helpful agent" behavior.

### 1. No silent auto-approval

Slaves run with `auto_approve: false` and `allow_destructive: false` by default. If a slave hits an approval boundary, it stops and reports back. The master may ask the user, but never approves on its own.

### 2. Slaves do not inherit master memory

Slaves receive only the `context` block in the task payload. They cannot read `~/.hermes`, session stores, or user profile files. This prevents a remote slave from mimicking the master or leaking continuity.

### 3. Secrets stay on the master

- API keys, tokens, and `.env` values live only on the master (or in user-managed files).
- Task payloads must not include secrets.
- If a slave needs credentials, the master provides short-lived, scoped tokens or instructs the user to run the step locally.

### 4. One task, one slave, one lifetime

A slave process is created for a single task and exits when done. Long-lived daemons are opt-in only and documented in `DESIGN.md` / the launcher script.

### 5. Remote bridge must authenticate

Any bridge server must:

- Use a pre-shared key or mTLS.
- Listen on a host/port that is not exposed to the public internet by default.
- Log every connection and task dispatch.
- Reject payloads that do not match the v1 schema.

### 6. Master must announce destructive actions

When the master plans to restart a slave, delete a workspace, or run a destructive command, it states the action and waits for user confirmation. This mirrors the "announce before executing" rule from Keirstin's collaboration conventions.

### 7. Verify before acting on stale notifications

When running across multiple processes, completion notifications can arrive out of order or from dead sessions. The master always checks live state (process list, file timestamps, bridge heartbeat) before treating a notification as current.

## Windows-specific notes

- Launcher scripts use **cmd** and **git-bash** conventions. The repository avoids PowerShell-specific syntax.
- Paths in payloads use forward slashes or escaped backslashes; the bridge normalizes them.
- The `terminal` tool on this host runs through bash (MSYS/git-bash), not PowerShell.

## Relationship to Keirstin's existing systems

- **keirstin-collaboration**: The "slow down, listen, ask before building" rules still apply. KeirstinLink is a tool; the master should not use it to bypass collaboration boundaries.
- **keirstin-continuity**: Memory, identity verification, and backup rules live on the master only. Slaves do not participate in continuity.
- **hermes-agent**: Native delegation and spawning patterns from the `hermes-agent` skill are the preferred first implementation before adding the custom bridge.

## Open questions / next iteration

1. Do we want a persistent SQLite task queue or ephemeral JSONL logs?
2. Should the bridge support bidirectional chat, or only request/response?
3. Which Hermes toolsets should be allowed for slaves by default?
4. How do we surface slave approval prompts back to the user without the master auto-answering?
5. Do we need a heartbeat / liveness check for long-running remote slaves?
