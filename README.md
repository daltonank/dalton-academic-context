# Canvas → Academic Context

Read-only ingestion of a private Canvas iCal subscription into a GitHub repository for use by an Academic Context MCP server and planning agents.

## What it produces

After each successful sync:

- `canvas/calendar.json` — normalized events/assignments in the configured coverage window.
- `canvas/upcoming.json` — normalized items in the near-term planning window.
- `canvas/sync_status.json` — freshness, coverage, and record counts.
- `canvas/ACADEMIC_CONTEXT.md` — compact AI-facing planning brief.

The feed URL is **never written to output files** and the raw ICS is **not persisted** by default.

## Required GitHub configuration

In **Settings → Secrets and variables → Actions**:

### Repository secret

`CANVAS_CALENDAR_FEED_URL`

Paste the private Canvas iCal subscription URL. Treat it like a password. Do not commit it.

### Optional repository variable

`CANVAS_COURSE_ALIASES_JSON`

Map Canvas numeric course IDs to readable codes. Example:

```json
{"12345":"ISYS-481","67890":"COSC-130"}
```

If omitted, the sync still works. Events will use `course <id>` where the course ID can be recovered from a Canvas URL.

## Installation

Copy the following paths into the root of the private Academic Context repository:

```text
.github/workflows/canvas-sync.yml
integrations/
canvas/.gitkeep
.gitignore                # merge with the existing ignore file if one exists
ACADEMIC_CONTEXT_MCP.md
```

If the repository already has `.gitignore`, add only the Canvas-related entries rather than replacing the file.

## First run

1. Add `CANVAS_CALENDAR_FEED_URL` as a repository secret.
2. Commit these files to the default branch.
3. Open **Actions → Sync Canvas Academic Context → Run workflow**.
4. Confirm the run succeeds.
5. Inspect `canvas/sync_status.json`.
6. Inspect `canvas/upcoming.json` and compare several dates against Canvas.
7. Add `CANVAS_COURSE_ALIASES_JSON` if friendly course labels are missing.
8. Run the workflow again.

The scheduled job subsequently runs at 06:17, 11:17, 16:17, and 21:17 America/Chicago. The non-zero minute avoids the busiest top-of-hour Actions window.

## Local test

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
python -m unittest discover -s integrations/canvas/tests -v
```

For a real local sync, set environment variables without writing the secret to source control:

```bash
export CANVAS_CALENDAR_FEED_URL='https://...private-feed...ics'
export CANVAS_TIMEZONE='America/Chicago'
python integrations/canvas/sync_calendar.py
```

## Protected branches

The workflow pushes generated context to the default branch. If branch rules reject GitHub Actions pushes, either permit the workflow identity to update the generated `canvas/` paths or change the workflow to open a pull request instead. Do not weaken unrelated branch protections just to make the sync work.

## Security model

- HTTPS feed URLs only.
- GET-only network access to the iCal feed.
- No Canvas API write operations.
- Feed URL is stored only in GitHub Actions Secrets.
- HTTP failures are reported without printing the credential-bearing URL.
- Raw feed is not committed.
- Repository should remain private because normalized academic schedules are personal data.

If the previously exposed feed URL has been shared outside trusted systems, regenerate/reset it in Canvas before adding the GitHub secret.

## Current limitations

Canvas iCal includes calendar assignments and events, but not Canvas To-Do items. It also cannot provide submission status, module progress, or grades. Those belong in a later read-only Canvas API enrichment layer.
