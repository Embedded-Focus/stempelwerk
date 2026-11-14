# Demo Environment

This directory contains a Compose setup for local browser testing. It works
with Docker (`docker compose`) and Podman (`podman compose`); pass the engine
via `CONTAINER_ENGINE` if you do not use the Docker default.

```bash
make demo-up
```

Open the frontend at:

```text
http://127.0.0.1:5173
```

The backend API is exposed at:

```text
http://127.0.0.1:8765/api/v1/status
```

The frontend service proxies `/api` requests to the backend service inside the
Compose network.

The backend uses `demo/config.toml`, which points at the sample files in
`demo/org/`.

The demo enables the debug panel (`VITE_DEBUG_PANEL=1`), which offers a
"Create backup" button per configured file. Backups are no longer created
automatically on clock updates; you create them from this panel. The panel
starts collapsed; click "Debug" to expand it.

Follow service logs with:

```bash
make demo-logs
```

## Dependency updates

The updater covers all pinned dependencies: the demo base image digests, the
Python lockfile (`uv.lock`), and the frontend lockfile
(`package-lock.json`). It prints current vs. latest for each group:

```bash
make update-deps-dryrun
```

Write the updates with:

```bash
make update-deps
```

The updater refreshes image digests within a fixed tag and package versions
within their declared ranges. It never changes an image tag (a new Python
minor or Node major can change behavior) and never widens a semver range.
Bump a tag or a range by hand, then run the updater again.
