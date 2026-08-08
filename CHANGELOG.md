# Changelog

## Unreleased

- Fix BFS unknown-token handling, stale metadata precedence, merged auth scanning, and CLI config loading; include BFS tests in release checks.
- Add **JWT `bfs` claim detection**: register/OAuth path inspects access_token (and SSO) for the `bfs` key; flagged accounts go to `accounts/sso_bfs_flagged.txt` and CPA records get `bfs` / `bfs_value` metadata.
- Panel **BFS 检测** card + `/api/bfs` / `/api/bfs/scan` / `/api/bfs/check`; batch CLI `scripts/check_bfs.py` and `sso_to_auth_json.py --check-bfs-dir`.
- Config knobs: `bfs_check`, `bfs_skip_cpa`, `bfs_disable_cpa` (see `config.example.json`).
- Supervise headless batches and automatically resume remaining task slots after a Playwright/Camoufox driver crash or stall.
- Persist batch slot progress atomically so completed accounts are not repeated during recovery.
- Make panel process management and batch launch platform-aware: `psutil` discovery, Linux auto-Xvfb, macOS direct launch, Windows virtualenv paths, and actionable missing-procfs errors.

## 0.2.0 - 2026-07-30

- Redesign the live panel with responsive light and dark themes.
- Add a dedicated usage and troubleshooting view.
- Add pending SSO and account-file recovery with success dequeue.
- Move learned ASN rules from Python source into locked JSON state.
- Scope process discovery and termination to one project root.
- Require monitor authentication for operational read and write APIs.
- Add security headers, bounded request bodies, and redacted log output.
- Create runtime credentials, account data, logs, state, and PID files owner-only.
- Add release tests, CI, a systemd service template, and deployment checks.
