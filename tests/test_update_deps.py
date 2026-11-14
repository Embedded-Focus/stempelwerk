"""Tests for the stempelwerk-update-deps maintainer script."""

import json
import re
import shutil
import subprocess
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stempelwerk.update_deps import (
    BACKEND_DOCKERFILE,
    FRONTEND_DOCKERFILE,
    PINS,
    ImagePin,
    PinResult,
    apply_changes,
    apply_digest,
    build_report,
    fetch_latest_digest,
    format_report,
    main,
    read_current_digest,
    report_frontend_dependencies,
    report_python_dependencies,
    update_frontend_dependencies,
    update_python_dependencies,
)


@pytest.mark.parametrize("pin", PINS, ids=[pin.name for pin in PINS])
def test_read_current_digest_matches_real_dockerfile(pin: ImagePin) -> None:
    content = pin.file.read_text()
    digest = read_current_digest(content, pin)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)


def test_pins_cover_both_demo_dockerfiles() -> None:
    # Each demo Dockerfile's base image is tracked; the parametrized
    # read/apply tests above verify the patterns actually match the files.
    assert {pin.file for pin in PINS} == {BACKEND_DOCKERFILE, FRONTEND_DOCKERFILE}
    assert [pin.name for pin in PINS] == ["uv backend image", "node frontend image"]


def test_pins_keep_the_tag_outside_the_capture_group() -> None:
    # The updater may only rewrite the digest; the tag (Python minor, Node
    # major) is a deliberate manual choice, so it must be part of the
    # surrounding pattern, not of group 1.
    for pin in PINS:
        match = pin.pattern.search(pin.file.read_text())
        assert match is not None
        assert match.group(0).startswith(match.group(0).replace(match.group(1), ""))
        assert "sha256:" not in match.group(0).replace(match.group(1), "")


def _flip_last_hex(digest: str) -> str:
    """Return *digest* with its last hex digit changed.

    The result still satisfies every pin's pattern, so it can stand in for a
    registry-offered new digest.
    """
    assert digest[-1] in "0123456789abcdef"
    flipped = "0" if digest[-1] != "0" else "1"
    return digest[:-1] + flipped


def test_apply_digest_round_trips_without_other_changes() -> None:
    for pin in PINS:
        content = pin.file.read_text()
        current = read_current_digest(content, pin)
        new_digest = _flip_last_hex(current)

        updated = apply_digest(content, pin, new_digest)

        matches = list(pin.pattern.finditer(content))
        updated_matches = list(pin.pattern.finditer(updated))
        assert len(updated_matches) == len(matches) > 0
        assert [m.group(1) for m in updated_matches] == [new_digest] * len(matches)
        # The tag and everything else outside the digest span is untouched.
        assert content.replace(current, "") == updated.replace(new_digest, "")


def test_apply_digest_raises_when_pattern_missing() -> None:
    pin = PINS[0]
    with pytest.raises(ValueError, match=pin.name):
        apply_digest("no digest here", pin, "sha256:" + "a" * 64)


def test_read_current_digest_raises_when_pattern_missing() -> None:
    pin = PINS[0]
    with pytest.raises(ValueError, match=pin.name):
        read_current_digest("no digest here", pin)


def test_fetch_latest_digest_returns_hub_api_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"digest": "sha256:' + b"a" * 64 + b'"}'
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr("stempelwerk.update_deps.urllib.request.urlopen", urlopen)

    digest = fetch_latest_digest("docker.io/library/node", "24-bookworm-slim")

    assert digest == "sha256:" + "a" * 64
    url = urlopen.call_args.args[0]
    assert url == "https://hub.docker.com/v2/repositories/library/node/tags/24-bookworm-slim"


def test_fetch_latest_digest_raises_without_hub_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"tag": "24-bookworm-slim"}'
    urlopen = MagicMock(return_value=response)
    monkeypatch.setattr("stempelwerk.update_deps.urllib.request.urlopen", urlopen)

    with pytest.raises(ValueError, match="no digest"):
        fetch_latest_digest("docker.io/library/node", "24-bookworm-slim")


def test_fetch_latest_digest_returns_multiarch_ghcr_content_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_response = MagicMock()
    token_response.__enter__.return_value = token_response
    token_response.read.return_value = b'{"token": "tok-123"}'
    manifest_response = MagicMock()
    manifest_response.__enter__.return_value = manifest_response
    manifest_response.headers.get.return_value = "sha256:" + "a" * 64
    urlopen = MagicMock(side_effect=[token_response, manifest_response])
    monkeypatch.setattr("stempelwerk.update_deps.urllib.request.urlopen", urlopen)

    digest = fetch_latest_digest("ghcr.io/astral-sh/uv", "python3.14-bookworm-slim")

    assert digest == "sha256:" + "a" * 64
    token_url = urlopen.call_args_list[0].args[0]
    assert token_url.startswith("https://ghcr.io/token?")
    assert "repository%3Aastral-sh%2Fuv%3Apull" in token_url
    manifest_request = urlopen.call_args_list[1].args[0]
    assert (
        manifest_request.full_url
        == "https://ghcr.io/v2/astral-sh/uv/manifests/python3.14-bookworm-slim"
    )
    assert manifest_request.headers["Authorization"] == "Bearer tok-123"
    assert (
        "application/vnd.docker.distribution.manifest.list.v2+json"
        in manifest_request.headers["Accept"]
    )


def test_fetch_latest_digest_raises_without_ghcr_digest_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_response = MagicMock()
    token_response.__enter__.return_value = token_response
    token_response.read.return_value = b'{"token": "tok-123"}'
    manifest_response = MagicMock()
    manifest_response.__enter__.return_value = manifest_response
    manifest_response.headers.get.return_value = None
    urlopen = MagicMock(side_effect=[token_response, manifest_response])
    monkeypatch.setattr("stempelwerk.update_deps.urllib.request.urlopen", urlopen)

    with pytest.raises(ValueError, match="no digest"):
        fetch_latest_digest("ghcr.io/astral-sh/uv", "python3.14-bookworm-slim")


def test_fetch_latest_digest_rejects_unsupported_registry() -> None:
    with pytest.raises(ValueError, match="Unsupported registry"):
        fetch_latest_digest("quay.io/example/image", "latest")


def test_build_report_records_error_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_fetch(image: str, tag: str) -> str:
        calls.append(image)
        if image == PINS[0].image:
            raise urllib.error.URLError("connection failed")
        return "sha256:" + "b" * 64

    monkeypatch.setattr("stempelwerk.update_deps.fetch_latest_digest", fake_fetch)

    results = build_report(PINS)

    assert len(results) == len(PINS)
    assert len(calls) == len(PINS)

    failed = results[0]
    assert failed.error is not None
    assert failed.latest is None
    assert not failed.outdated

    succeeded = results[1]
    assert succeeded.error is None
    assert succeeded.latest == "sha256:" + "b" * 64
    assert succeeded.outdated or succeeded.current == "sha256:" + "b" * 64


def test_build_report_flags_matching_digest_as_up_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = read_current_digest(PINS[0].file.read_text(), PINS[0])
    monkeypatch.setattr(
        "stempelwerk.update_deps.fetch_latest_digest",
        MagicMock(return_value=current),
    )

    results = build_report(PINS[:1])

    assert results[0].error is None
    assert not results[0].outdated


def test_apply_changes_only_writes_outdated_files(tmp_path: Path) -> None:
    shutil.copytree(BACKEND_DOCKERFILE.parent, tmp_path / "demo")
    backend = tmp_path / "demo" / "backend.Dockerfile"
    frontend = tmp_path / "demo" / "frontend.Dockerfile"

    backend_pin = replace(PINS[0], file=backend)
    frontend_pin = replace(PINS[1], file=frontend)

    current_backend = read_current_digest(backend.read_text(), backend_pin)
    current_frontend = read_current_digest(frontend.read_text(), frontend_pin)

    results = [
        PinResult(
            pin=backend_pin,
            current=current_backend,
            latest=_flip_last_hex(current_backend),
        ),  # outdated
        PinResult(pin=frontend_pin, current=current_frontend, latest=current_frontend),  # unchanged
    ]

    changed = apply_changes(results)

    assert changed == [backend]
    assert read_current_digest(backend.read_text(), backend_pin) == _flip_last_hex(current_backend)
    assert read_current_digest(frontend.read_text(), frontend_pin) == current_frontend


def test_format_report_renders_aligned_columns() -> None:
    pin = PINS[0]
    results = [PinResult(pin=pin, current="sha256:" + "a" * 64, latest=None, error="boom")]

    report = format_report(results)

    assert pin.name in report
    assert "sha256:" + "a" * 64 in report
    assert "boom" in report


def test_report_python_dependencies_runs_dry_run_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_mock = MagicMock(return_value=MagicMock(stdout="plan", stderr=""))
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", run_mock)

    output = report_python_dependencies()

    assert output == "plan"
    args, kwargs = run_mock.call_args
    assert args[0] == ["uv", "lock", "--upgrade", "--dry-run"]
    assert kwargs["check"] is True


def test_update_python_dependencies_runs_lock_upgrade_and_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", run_mock)

    update_python_dependencies()

    assert run_mock.call_count == 2
    assert run_mock.call_args_list[0].args[0] == ["uv", "lock", "--upgrade"]
    assert run_mock.call_args_list[1].args[0] == ["uv", "sync"]


def test_update_python_dependencies_strips_ambient_project_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A dev shell for this repo (e.g. devenv) commonly exports one of these
    # pointing at a foreign venv. Strip them so uv only operates on this
    # project.
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/somewhere/foreign/venv")
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/foreign/venv")
    run_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", run_mock)

    update_python_dependencies()

    for call in run_mock.call_args_list:
        passed_env = call.kwargs["env"]
        assert "UV_PROJECT_ENVIRONMENT" not in passed_env
        assert "VIRTUAL_ENV" not in passed_env


def test_report_frontend_dependencies_renders_outdated_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = MagicMock(
        returncode=1,
        stdout=json.dumps(
            {
                "vite": {
                    "current": "7.0.0",
                    "wanted": "7.1.11",
                    "latest": "8.0.0",
                }
            }
        ),
    )
    run_mock = MagicMock(return_value=process)
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", run_mock)

    report = report_frontend_dependencies()

    assert "package" in report
    assert "current" in report
    assert "vite" in report
    assert "8.0.0" in report
    args, kwargs = run_mock.call_args
    assert args[0] == ["npm", "outdated", "--json"]
    assert kwargs["check"] is False


def test_report_frontend_dependencies_handles_up_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = MagicMock(returncode=0, stdout="{}")
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", MagicMock(return_value=process))

    assert "up to date" in report_frontend_dependencies()


def test_report_frontend_dependencies_raises_on_unexpected_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # npm signals "outdated packages exist" with exit code 1; anything else
    # is a real failure.
    process = MagicMock(returncode=2, stdout="")
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", MagicMock(return_value=process))

    with pytest.raises(subprocess.CalledProcessError):
        report_frontend_dependencies()


def test_update_frontend_dependencies_runs_npm_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.subprocess.run", run_mock)

    update_frontend_dependencies()

    args, _ = run_mock.call_args
    assert args[0] == ["npm", "update"]


def test_main_dryrun_prints_all_sections_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin = PINS[0]
    current = read_current_digest(pin.file.read_text(), pin)
    results = [PinResult(pin=p, current=current, latest=current) for p in PINS]
    monkeypatch.setattr("stempelwerk.update_deps.build_report", lambda pins: results)
    monkeypatch.setattr(
        "stempelwerk.update_deps.report_python_dependencies",
        lambda: "No required updates",
    )
    monkeypatch.setattr(
        "stempelwerk.update_deps.report_frontend_dependencies",
        lambda: "all frontend packages up to date (within their ranges)",
    )
    apply_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.apply_changes", apply_mock)

    exit_code = main([])

    assert exit_code == 0
    apply_mock.assert_not_called()
    output = capsys.readouterr().out
    assert "Demo base images:" in output
    assert "Python dependencies" in output
    assert "Frontend dependencies" in output


def test_main_apply_updates_all_dependency_groups(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin = PINS[0]
    results = [PinResult(pin=pin, current="sha256:" + "a" * 64, latest="sha256:" + "b" * 64)]
    monkeypatch.setattr("stempelwerk.update_deps.build_report", lambda pins: results)
    monkeypatch.setattr("stempelwerk.update_deps.report_python_dependencies", lambda: "plan")
    monkeypatch.setattr("stempelwerk.update_deps.report_frontend_dependencies", lambda: "table")
    apply_mock = MagicMock(return_value=[pin.file])
    monkeypatch.setattr("stempelwerk.update_deps.apply_changes", apply_mock)
    python_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.update_python_dependencies", python_mock)
    frontend_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.update_frontend_dependencies", frontend_mock)

    exit_code = main(["--apply"])

    assert exit_code == 0
    apply_mock.assert_called_once_with(results)
    python_mock.assert_called_once_with()
    frontend_mock.assert_called_once_with()
    output = capsys.readouterr().out
    assert "Updated 1 demo Dockerfile(s)." in output


def test_main_returns_error_when_image_lookup_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin = PINS[0]
    results = [PinResult(pin=pin, current="sha256:" + "a" * 64, latest=None, error="boom")]
    monkeypatch.setattr("stempelwerk.update_deps.build_report", lambda pins: results)
    monkeypatch.setattr("stempelwerk.update_deps.report_python_dependencies", lambda: "plan")
    monkeypatch.setattr("stempelwerk.update_deps.report_frontend_dependencies", lambda: "table")
    python_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.update_python_dependencies", python_mock)
    frontend_mock = MagicMock()
    monkeypatch.setattr("stempelwerk.update_deps.update_frontend_dependencies", frontend_mock)

    exit_code = main(["--apply"])

    assert exit_code == 1
    python_mock.assert_called_once_with()
    frontend_mock.assert_called_once_with()
    assert "boom" in capsys.readouterr().out


def test_main_returns_error_when_report_command_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = [PinResult(pin=PINS[0], current="sha256:" + "a" * 64, latest="sha256:" + "a" * 64)]
    monkeypatch.setattr("stempelwerk.update_deps.build_report", lambda pins: results)

    def failing_report() -> str:
        raise subprocess.CalledProcessError(returncode=2, cmd=["npm", "outdated"])

    monkeypatch.setattr("stempelwerk.update_deps.report_frontend_dependencies", failing_report)

    exit_code = main([])

    assert exit_code == 1
    assert "report failed" in capsys.readouterr().out.lower()


def test_main_returns_error_when_apply_command_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pin = PINS[0]
    results = [PinResult(pin=pin, current="sha256:" + "a" * 64, latest="sha256:" + "b" * 64)]
    monkeypatch.setattr("stempelwerk.update_deps.build_report", lambda pins: results)
    monkeypatch.setattr("stempelwerk.update_deps.report_python_dependencies", lambda: "plan")
    monkeypatch.setattr("stempelwerk.update_deps.report_frontend_dependencies", lambda: "table")
    monkeypatch.setattr("stempelwerk.update_deps.apply_changes", MagicMock(return_value=[pin.file]))

    def failing_update() -> None:
        raise subprocess.CalledProcessError(returncode=1, cmd=["uv", "sync"])

    monkeypatch.setattr("stempelwerk.update_deps.update_python_dependencies", failing_update)

    exit_code = main(["--apply"])

    assert exit_code == 1
    assert "update failed" in capsys.readouterr().out.lower()
