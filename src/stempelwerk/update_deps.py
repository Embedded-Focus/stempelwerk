"""Refresh the pinned dependencies of the project.

Covers three dependency groups:

- The two Dockerfiles of the Compose demo (``demo/backend.Dockerfile``,
  ``demo/frontend.Dockerfile``). Each one pins its base image as
  ``image:tag@sha256:...``; the updater looks up the tag's current multi-arch
  manifest-list digest from its registry (Docker Hub or GHCR) and rewrites
  the digest in place. The tags themselves are never bumped automatically:
  the Python minor in the uv image tag and the Node major in the node image
  tag are deliberate manual choices (each can change interpreter or
  toolchain behaviour).
- The Python dependencies pinned by ``uv.lock``. The dry run reports what
  ``uv lock --upgrade`` would change; ``--apply`` runs ``uv lock --upgrade``
  followed by ``uv sync``.
- The frontend dependencies pinned by ``frontend/package-lock.json`` within
  the semver ranges of ``frontend/package.json``. The dry run reports what
  ``npm outdated`` sees; ``--apply`` runs ``npm update``, which moves the
  lockfile to the newest in-range version of each package. Major bumps that
  leave a declared range still need a manual ``package.json`` edit; the
  report shows the ``latest`` column so those are visible.

Installed as its own console script (``stempelwerk-update-deps``), separate
from the ``stempelwerk`` CLI, since it edits project *source* files rather
than acting on a running calendar.

Shortcomings: the project directories are derived from this module's own
file location, so they only resolve to the real sources when run against an
editable/source checkout (e.g. via ``uv run``). Running it from an installed
wheel would edit the installed copy, not the repository.
"""

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEMO_DIR = PROJECT_DIR / "demo"
FRONTEND_DIR = PROJECT_DIR / "frontend"

BACKEND_DOCKERFILE = DEMO_DIR / "backend.Dockerfile"
FRONTEND_DOCKERFILE = DEMO_DIR / "frontend.Dockerfile"


@dataclass(frozen=True)
class ImagePin:
    """A single digest-pinned base image and the file that pins it.

    :param name: Human-readable component name.
    :param file: Dockerfile containing the pinned digest.
    :param pattern: Regex whose first capture group spans exactly the
        digest substring (including its ``sha256:`` prefix) to read/replace.
        The tag stays part of the surrounding pattern so the updater can
        never rewrite it.
    :param image: Full image reference including registry host
        (``docker.io/library/node``, ``ghcr.io/astral-sh/uv``).
    :param tag: Fixed tag whose digest is resolved.
    """

    name: str
    file: Path
    pattern: re.Pattern[str]
    image: str
    tag: str


PINS: list[ImagePin] = [
    ImagePin(
        name="uv backend image",
        file=BACKEND_DOCKERFILE,
        pattern=re.compile(
            r"ghcr\.io/astral-sh/uv:python3\.14-bookworm-slim@(sha256:[0-9a-f]{64})"
        ),
        image="ghcr.io/astral-sh/uv",
        tag="python3.14-bookworm-slim",
    ),
    # The node major tag (24-slim) is never bumped automatically; bumping a
    # major is a deliberate manual act.
    ImagePin(
        name="node frontend image",
        file=FRONTEND_DOCKERFILE,
        pattern=re.compile(r"node:24-bookworm-slim@(sha256:[0-9a-f]{64})"),
        image="docker.io/library/node",
        tag="24-bookworm-slim",
    ),
]


# Manifest media types requested in preference order; the first two are
# multi-arch manifest lists/indices, so the returned Docker-Content-Digest is
# the multi-arch digest suitable for digest-pinned FROM lines.
_MANIFEST_MEDIA_TYPES = (
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
)


def _fetch_docker_hub_digest(repo: str, tag: str) -> str:
    """Resolve the digest of a Docker Hub image tag via the public Hub API.

    Used for ``docker.io`` images instead of the registry token dance: the
    Hub REST API is anonymous and returns the tag's multi-arch manifest-list
    digest directly.

    :param repo: Hub repository path (``library/node``).
    :param tag: Tag to resolve.
    :returns: Digest string (``sha256:...``).
    :raises ValueError: If the API response carries no digest.
    :raises urllib.error.URLError: If the request fails (including HTTP
        errors such as a tag that does not exist).
    """
    url = f"https://hub.docker.com/v2/repositories/{repo}/tags/{tag}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read())
    digest = data.get("digest")
    if not isinstance(digest, str) or not digest:
        raise ValueError(f"Docker Hub returned no digest for {repo}:{tag}")
    return digest


def _fetch_ghcr_digest(repo: str, tag: str) -> str:
    """Resolve the digest of a GHCR image tag via the registry API.

    Performs an anonymous pull-scoped token exchange and requests the tag's
    manifest with manifest-list/OCI-index media types so the returned
    ``Docker-Content-Digest`` header is the multi-arch manifest-list digest.

    :param repo: GHCR repository path (``astral-sh/uv``).
    :param tag: Tag to resolve.
    :returns: Digest string (``sha256:...``).
    :raises ValueError: If the registry response carries no digest header.
    :raises urllib.error.URLError: If a registry request fails (including
        HTTP errors such as a tag that does not exist).
    """
    scope = urllib.parse.urlencode({"scope": f"repository:{repo}:pull"})
    with urllib.request.urlopen(f"https://ghcr.io/token?{scope}", timeout=30) as response:
        token = json.loads(response.read())["token"]

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": ", ".join(_MANIFEST_MEDIA_TYPES),
    }
    request = urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{tag}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        digest = response.headers.get("Docker-Content-Digest")
    if not digest:
        raise ValueError(f"GHCR returned no digest for {repo}:{tag}")
    return digest


def fetch_latest_digest(image: str, tag: str) -> str:
    """Resolve the multi-arch digest of *image:tag* from its registry.

    :param image: Full image reference including registry host
        (``docker.io/library/node``, ``ghcr.io/astral-sh/uv``).
    :param tag: Tag to resolve.
    :returns: Digest string (``sha256:...``).
    :raises ValueError: If the registry is unsupported or the response
        carries no digest.
    :raises urllib.error.URLError: If a registry request fails (including
        HTTP errors such as a tag that does not exist).
    """
    registry_host, _, repo = image.partition("/")
    if registry_host == "docker.io":
        return _fetch_docker_hub_digest(repo, tag)
    if registry_host == "ghcr.io":
        return _fetch_ghcr_digest(repo, tag)
    raise ValueError(f"Unsupported registry for image {image!r}")


def read_current_digest(content: str, pin: ImagePin) -> str:
    """Extract the currently pinned digest from file content.

    :param content: Full text of :attr:`ImagePin.file`.
    :param pin: Pin whose pattern locates the digest.
    :returns: Currently pinned digest string (``sha256:...``).
    :raises ValueError: If the pattern does not match *content*.
    """
    match = pin.pattern.search(content)
    if match is None:
        raise ValueError(f"Could not locate current digest for {pin.name!r} in {pin.file}")
    return match.group(1)


def apply_digest(content: str, pin: ImagePin, new_digest: str) -> str:
    """Return *content* with the pinned digest replaced.

    :param content: Full text of :attr:`ImagePin.file`.
    :param pin: Pin whose pattern locates the digest.
    :param new_digest: Replacement digest string (``sha256:...``).
    :returns: Updated file content.
    :raises ValueError: If the pattern does not match *content*.
    """
    if pin.pattern.search(content) is None:
        raise ValueError(f"Could not locate current digest for {pin.name!r} in {pin.file}")

    def _replace(match: re.Match[str]) -> str:
        start, end = match.span(1)
        return (
            match.group(0)[: start - match.start()]
            + new_digest
            + match.group(0)[end - match.start() :]
        )

    return pin.pattern.sub(_replace, content)


@dataclass
class PinResult:
    """Outcome of checking one :class:`ImagePin` against its registry.

    :param pin: The pin that was checked.
    :param current: Digest currently pinned in the Dockerfile.
    :param latest: Latest digest available, or ``None`` on lookup failure.
    :param error: Error message from a failed lookup, if any.
    """

    pin: ImagePin
    current: str
    latest: str | None
    error: str | None = None

    @property
    def outdated(self) -> bool:
        """Whether the registry offers a different digest.

        :returns: ``True`` if the lookup succeeded and differs from current.
        """
        return self.latest is not None and self.latest != self.current


def build_report(pins: list[ImagePin]) -> list[PinResult]:
    """Check every pin's current vs. latest digest.

    Lookup failures for one pin do not prevent the others from being
    checked; they are recorded on the resulting :attr:`PinResult.error`.

    :param pins: Pins to check.
    :returns: One :class:`PinResult` per pin, in the same order.
    """
    results: list[PinResult] = []
    for pin in pins:
        content = pin.file.read_text()
        current = read_current_digest(content, pin)
        try:
            latest = fetch_latest_digest(pin.image, pin.tag)
        except (urllib.error.URLError, ValueError) as e:
            results.append(PinResult(pin=pin, current=current, latest=None, error=str(e)))
            continue
        results.append(PinResult(pin=pin, current=current, latest=latest))
    return results


def apply_changes(results: list[PinResult]) -> list[Path]:
    """Write outdated pins' latest digests to their Dockerfiles.

    :param results: Report produced by :func:`build_report`.
    :returns: Paths of files actually modified, one entry per file.
    """
    outdated = [result for result in results if result.outdated]

    changed: list[Path] = []
    for file in dict.fromkeys(result.pin.file for result in outdated):
        content = file.read_text()
        for result in outdated:
            if result.pin.file != file:
                continue
            assert result.latest is not None
            content = apply_digest(content, result.pin, result.latest)
        file.write_text(content)
        changed.append(file)
    return changed


def format_report(results: list[PinResult]) -> str:
    """Render a plain-text table of current vs. latest digests.

    :param results: Report produced by :func:`build_report`.
    :returns: Aligned multi-line table.
    """
    name_width = max(len(r.pin.name) for r in results)
    digest_width = max(len(r.current) for r in results)
    lines = []
    for r in results:
        status = r.error or ("update available" if r.outdated else "up to date")
        latest = r.latest if r.latest is not None else "?"
        lines.append(
            f"{r.pin.name:<{name_width}}  {r.current:<{digest_width}}  "
            f"{latest:<{digest_width}}  {status}"
        )
    return "\n".join(lines)


def _run_checked(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    """Run *cmd* in *cwd* and return its combined output.

    :param cmd: Argument vector to execute.
    :param cwd: Working directory for the subprocess.
    :param env: Environment for the subprocess; ``None`` inherits the
        current one.
    :returns: Combined stdout and stderr.
    :raises subprocess.CalledProcessError: If the command exits non-zero.
    """
    process = subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return process.stdout + process.stderr


def report_python_dependencies() -> str:
    """Report what ``uv lock --upgrade`` would change in ``uv.lock``.

    The dry run resolves against the registries but never writes the
    lockfile.

    :returns: The dry run's combined output.
    :raises subprocess.CalledProcessError: If ``uv`` fails.
    """
    return _run_checked(["uv", "lock", "--upgrade", "--dry-run"], cwd=PROJECT_DIR)


def update_python_dependencies() -> None:
    """Upgrade ``uv.lock`` to the latest in-range versions and sync.

    ``UV_PROJECT_ENVIRONMENT``/``VIRTUAL_ENV`` are stripped from the
    subprocess environment: dev shells for this repo (e.g. devenv) commonly
    export one of these pointing at a foreign venv. Strip them so uv
    operates only on this project.

    :raises subprocess.CalledProcessError: If ``uv lock`` or ``uv sync``
        exits non-zero.
    """
    env = {
        k: v for k, v in os.environ.items() if k not in {"UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"}
    }
    _run_checked(["uv", "lock", "--upgrade"], cwd=PROJECT_DIR, env=env)
    _run_checked(["uv", "sync"], cwd=PROJECT_DIR, env=env)


def report_frontend_dependencies() -> str:
    """Report current vs. in-range vs. latest frontend package versions.

    Runs ``npm outdated --json``. npm exits non-zero when at least one
    package is outdated; that outcome is a valid report, not an error.

    :returns: Aligned multi-line table, or a note that every package is up
        to date.
    :raises subprocess.CalledProcessError: If npm fails for a reason other
        than outdated packages (npm signals those with exit code 1 only).
    """
    process = subprocess.run(
        ["npm", "outdated", "--json"],
        cwd=FRONTEND_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode not in (0, 1):
        raise subprocess.CalledProcessError(process.returncode, process.args)

    data = json.loads(process.stdout or "{}")
    if not data:
        return "all frontend packages up to date (within their ranges)"

    rows = [
        (
            name,
            str(info.get("current", "-")),
            str(info.get("wanted", "-")),
            str(info.get("latest", "-")),
        )
        for name, info in sorted(data.items())
    ]
    name_width = max(len(row[0]) for row in rows)
    version_width = max(max(len(row[i]) for row in rows) for i in (1, 2, 3))
    lines = [
        f"{row[0]:<{name_width}}  {row[1]:<{version_width}}  {row[2]:<{version_width}}  {row[3]}"
        for row in rows
    ]
    header = (
        f"{'package':<{name_width}}  "
        f"{'current':<{version_width}}  "
        f"{'in-range':<{version_width}}  latest"
    )
    return "\n".join([header, *lines])


def update_frontend_dependencies() -> None:
    """Move ``package-lock.json`` to the newest in-range package versions.

    Runs ``npm update``, which respects the semver ranges declared in
    ``package.json``. Major bumps need a manual range edit first.

    :raises subprocess.CalledProcessError: If npm exits non-zero.
    """
    _run_checked(["npm", "update"], cwd=FRONTEND_DIR)


def main(argv: list[str] | None = None) -> int:
    """Check and optionally update the project's pinned dependencies.

    :param argv: Command-line arguments; defaults to ``sys.argv[1:]``.
    :returns: Process exit code: ``0`` on success, ``1`` when an image
        lookup or an apply step failed.
    """
    parser = argparse.ArgumentParser(
        prog="stempelwerk-update-deps",
        description="Check and optionally update the project's pinned "
        "dependencies: demo base image digests, the Python lockfile, and "
        "the frontend lockfile.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the latest versions to the pinned files. Without this "
        "flag, only a report is printed.",
    )
    args = parser.parse_args(argv)

    results = build_report(PINS)
    print("Demo base images:")
    print(format_report(results))

    image_errors = any(r.error for r in results)

    try:
        print("\nPython dependencies (uv lock --upgrade --dry-run):")
        print(report_python_dependencies())
        print("Frontend dependencies (npm outdated):")
        print(report_frontend_dependencies())
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Dependency report failed: {e}")
        return 1

    if args.apply:
        try:
            changed = apply_changes(results)
            print(f"\nUpdated {len(changed)} demo Dockerfile(s).")
            print("Updating Python lockfile (uv lock --upgrade, uv sync)...")
            update_python_dependencies()
            print("Updating frontend lockfile (npm update)...")
            update_frontend_dependencies()
        except subprocess.CalledProcessError as e:
            print(f"Dependency update failed: {e}")
            return 1

    return 1 if image_errors else 0


def run() -> None:
    """Entry point for the ``stempelwerk-update-deps`` console script."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
