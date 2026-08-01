# Architecture

Org Clock Calendar has three main boundaries:

- `org_reader`: semantic traversal of configured Org files.
- `org_writer`: lossless byte-preserving edits to individual `CLOCK:` lines.
- `api`: local FastAPI endpoints consumed by the browser frontend.

The frontend is intentionally small: Vite, TypeScript, and FullCalendar provide
calendar rendering and interaction while the backend remains the source of
truth for configured files, revisions, and mutations.

