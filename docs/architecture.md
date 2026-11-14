# Architecture

Stempelwerk has three main boundaries:

- `org_reader`: semantic traversal of configured Org files.
- `org_writer`: lossless byte-preserving edits to individual `CLOCK:` lines and heading titles.
- `caldav_reader`: read-only fetching of events from explicitly configured remote CalDAV servers.
- `api`: local FastAPI endpoints consumed by the browser frontend.

The frontend is intentionally small: Vite, TypeScript, and FullCalendar provide
calendar rendering and interaction while the backend remains the source of
truth for configured files, revisions, and mutations.

The browser talks only to the local API. The `caldav_reader` runs inside the
backend and fetches read-only events from remote CalDAV servers over verified
HTTPS; the browser never contacts CalDAV servers directly. The reader exposes
no mutation operation, requires certificate verification, and does not support
OAuth or insecure TLS bypass in this version.

