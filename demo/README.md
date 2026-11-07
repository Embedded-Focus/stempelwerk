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
automatically on clock updates; you create them from this panel.

Follow service logs with:

```bash
make demo-logs
```
