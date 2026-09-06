# Academic Context MCP read contract

The Canvas calendar integration writes normalized academic scheduling state to `canvas/`.

## Read order

1. Read `canvas/sync_status.json` first and inspect `last_synced`.
2. Read `canvas/ACADEMIC_CONTEXT.md` for ordinary planning and scheduling questions.
3. Read `canvas/upcoming.json` when exact upcoming event metadata is needed.
4. Read `canvas/calendar.json` only for wider historical/future calendar queries.

## Source authority

- Canvas is authoritative for assignment and event dates represented in the iCal feed.
- The normalized repository snapshot is derivative data and must carry its freshness timestamp.
- Do not infer submission, grade, To-Do, or module-completion state from the iCal snapshot.
- If `sync_status.json` is stale or reports an error, state that limitation before making deadline-sensitive claims.

## Planning behavior

When combining Academic Context with Google Calendar:

- Canvas answers **what is due and when**.
- Google Calendar answers **when the learner is occupied or available**.
- ChatGPT may propose work blocks, priorities, and reminders, but must not claim an assignment is complete unless a later authoritative source confirms it.
