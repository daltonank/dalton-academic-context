# Installation Manifest

## Copy into the Academic Context repository

- `.github/workflows/canvas-sync.yml`
- `integrations/__init__.py`
- `integrations/canvas/__init__.py`
- `integrations/canvas/sync_calendar.py`
- `integrations/canvas/requirements.txt`
- `integrations/canvas/.env.example`
- `integrations/canvas/tests/sample.ics`
- `integrations/canvas/tests/test_sync_calendar.py`
- `canvas/.gitkeep`
- `ACADEMIC_CONTEXT_MCP.md`
- `CONFIGURATION.md`
- `README.md`

Merge the supplied `.gitignore` entries into an existing repository `.gitignore` rather than replacing unrelated rules.

## GitHub Actions secret

- `CANVAS_CALENDAR_FEED_URL` = newly generated private Canvas iCal feed URL

## Optional GitHub Actions variable

- `CANVAS_COURSE_ALIASES_JSON` = JSON object mapping Canvas course IDs to friendly labels, for example `{"12345":"ISYS-481"}`

## First-run acceptance checks

- Workflow completes successfully.
- `canvas/sync_status.json` reports `status: ok`.
- `last_synced` is current and in `America/Chicago`.
- Several `calendar.json` / `upcoming.json` dates match Canvas.
- `ACADEMIC_CONTEXT.md` contains the expected upcoming workload.
- No feed URL appears in any committed file.
