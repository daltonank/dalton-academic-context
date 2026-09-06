# Configuration

## Required

| Name | GitHub type | Value |
|---|---|---|
| `CANVAS_CALENDAR_FEED_URL` | Actions secret | Private Canvas `.ics` subscription URL |

## Optional

| Name | Default | Purpose |
|---|---:|---|
| `CANVAS_TIMEZONE` | `America/Chicago` | Normalized timestamp timezone |
| `CANVAS_UPCOMING_DAYS` | `30` | AI planning window |
| `CANVAS_PAST_DAYS` | `30` | Historical calendar coverage |
| `CANVAS_FUTURE_DAYS` | `366` | Future calendar coverage |
| `CANVAS_OUTPUT_DIR` | `canvas` | Output directory |
| `CANVAS_COURSE_ALIASES_JSON` | `{}` | Course ID → friendly course code mapping |

The GitHub workflow sets all normal values directly and reads `CANVAS_COURSE_ALIASES_JSON` from repository variables.
