# KeirstinLink — Feature & Quality Backlog

*Living list of improvements, features, and known issues as we test and use the app.*

## In Progress / Just Added

- [x] **Open sync/master folder from Settings** — Open buttons
- [x] **Real folder picker for Browse buttons** — replaced `prompt()` with Tauri dialog plugin
- [x] **Per-device shared folders** — device add/edit modal with folder picker + relative paths
- [x] **Device add/edit modal** — create and update devices, set host/port/kind/shared folders

## UI / UX

- [ ] Real folder browser dialog instead of `prompt()` for Browse buttons
- [ ] Show device connection status (online/offline/last seen)
- [ ] Inline toast / notification when Propose/Approve completes
- [ ] Confirm before approving overwrites (show old vs new checksum, size, mtime)
- [ ] Show diff/preview for pending file changes
- [ ] Empty-state guidance: "Add a device → create a file → Propose → Approve"
- [ ] Dark/light theme toggle
- [ ] System tray icon + menu

## Core Sync

- [ ] Two-process / two-device LAN end-to-end test (one master, one client)
- [ ] Verify LAN discovery works across devices
- [ ] Conflict resolution UI when same file changed on both sides
- [ ] Delete handling (propose `delete` action, approve removes master file)
- [ ] Rename/move detection (not just create/update)
- [ ] Folder-level sync progress / transfer stats
- [ ] Resume interrupted uploads
- [ ] Binary-safe large file streaming (already using multipart, but verify >100 MB)

## Security / Safety

- [ ] Path traversal audit on all endpoints
- [ ] Approval timeout / auto-reject old pending changes
- [ ] Device pairing with PIN or token (prevent rogue device registration)
- [ ] Encrypt transfers over LAN (TLS or noise protocol)

## Platforms

- [ ] Android client UI/build
- [ ] Linux test
- [ ] Windows installer signing / SmartScreen friendliness
- [ ] Auto-start with OS option

## Quality / Dev

- [ ] GitHub Actions CI for pytest + cargo check + tauri build
- [ ] End-to-end automated UI test via Tauri driver or desktop automation
- [ ] Health check endpoint for runtime diagnostics
- [ ] Structured logging instead of print/ureq errors

## Notes

- Chris requested feature list be maintained while testing.
- Updated: 2026-07-21
