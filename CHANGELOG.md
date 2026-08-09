# Changelog

## Unreleased

## 0.3.0 - 2026-08-09

### Added

- Add a managed external proxy pool with single/bulk HTTP proxy import, enable/disable controls, health tests, cooldown state, and panel APIs.
- Add configurable email providers, including MoeMail, plus an authenticated provider editor and connection test in the panel.
- Add a managed email-domain pool with rotation rules, failure thresholds, reset controls, and worker integration.
- Add **JWT `bfs` claim detection** to registration and OAuth output. Flagged accounts are recorded in `accounts/sso_bfs_flagged.txt`, and CPA records receive `bfs` metadata.
- Add the panel **BFS 检测** card, `/api/bfs` endpoints, `scripts/check_bfs.py`, and the `bfs_check`, `bfs_skip_cpa`, and `bfs_disable_cpa` settings.
- Add an opt-in shared browser static-asset cache for scripts, stylesheets, fonts, and public images, with size limits, TTL handling, and private-response safeguards.
- Add a self-updating GitHub Star History chart to the project documentation.

### Changed

- Supervise headless batches and atomically persist completed slots so Playwright/Camoufox driver crashes or stalls resume only the remaining work.
- Make process discovery and batch launch platform-aware with `psutil`, Linux auto-Xvfb, macOS direct launch, Windows virtualenv paths, and actionable missing-procfs errors.
- Support external runtime roots while keeping process control scoped to the configured project.
- Move GitHub Actions to Node.js 24-compatible action versions and expand release checks for proxy, email, BFS, cache, platform, and supervisor behavior.
- Document the Tailscale self-use panel, LINUX DO community link, and related Grok2API egress project.

### Fixed

- Fix BFS unknown-token handling, stale metadata precedence, merged auth scanning, CLI config loading, and configured relative/absolute auth-directory resolution.
- Detect buffered Playwright crash markers immediately instead of waiting for the supervisor idle timeout.
- Avoid false Cloudflare email preflight failures when `/admin/new_address` uses `x-admin-auth` but `/api/domains` expects mailbox authentication.
- Preserve full success statistics and per-day jsonl results across the panel's two-second status polling.

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
