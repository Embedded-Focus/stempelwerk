from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from stempelwerk.app import create_app
from stempelwerk.config import CalDAVCalendarConfig
from stempelwerk.domain import CalDAVEvent
from stempelwerk.revisions import revision_for_file


def _write_config(tmp_path: Path, content: str, monkeypatch) -> Path:
    config_file = tmp_path / "config.toml"
    config_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("STEMPELWERK_CONFIG", str(config_file))
    return config_file


def test_status_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_clocks_endpoint_returns_entries_parsed_from_org_file(tmp_path: Path, monkeypatch) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(
        """
* Client Work :billable:
** TODO Implementation :backend:
CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 10:45] =>  1:30
** Review
CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30
""".lstrip(),
        encoding="utf-8",
    )
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"

[[files]]
id = "work"
path = "{org_file}"
color = "#2563eb"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/clocks",
        params={
            "start": "2026-07-31T00:00:00+02:00",
            "end": "2026-08-01T00:00:00+02:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["revisions"]) == {"work"}
    assert [
        (
            clock["file_id"],
            clock["heading_title"],
            clock["outline"],
            clock["start"],
            clock["end"],
            clock["duration_minutes"],
        )
        for clock in body["clocks"]
    ] == [
        (
            "work",
            "Implementation",
            ["Client Work", "Implementation"],
            "2026-07-31T09:15:00+02:00",
            "2026-07-31T10:45:00+02:00",
            90,
        ),
        (
            "work",
            "Review",
            ["Client Work", "Review"],
            "2026-07-31T11:00:00+02:00",
            "2026-07-31T11:30:00+02:00",
            30,
        ),
    ]
    assert all(clock["revision"] == body["revisions"]["work"] for clock in body["clocks"])


def test_clocks_endpoint_filters_repeated_file_ids(tmp_path: Path, monkeypatch) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text(
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        encoding="utf-8",
    )
    other_file = tmp_path / "other.org"
    other_file.write_text(
        "* Other\nCLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n",
        encoding="utf-8",
    )
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"

[[files]]
id = "work"
path = "{work_file}"
color = "#2563eb"

[[files]]
id = "other"
path = "{other_file}"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/clocks",
        params=[
            ("start", "2026-07-31T00:00:00+02:00"),
            ("end", "2026-08-01T00:00:00+02:00"),
            ("file_id", "other"),
        ],
    )

    assert response.status_code == 200
    assert [clock["file_id"] for clock in response.json()["clocks"]] == ["other"]


def test_headings_endpoint_returns_headings_parsed_from_org_file(
    tmp_path: Path, monkeypatch
) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text(
        """
* Client Work :billable:
** TODO Implementation :backend:
** WAITING Support :customer:
""".lstrip(),
        encoding="utf-8",
    )
    other_file = tmp_path / "other.org"
    other_file.write_text(
        """
* Internal
** Planning :meeting:
""".lstrip(),
        encoding="utf-8",
    )
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"

[[files]]
id = "work"
path = "{work_file}"

[[files]]
id = "other"
path = "{other_file}"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get("/api/v1/headings")

    assert response.status_code == 200
    assert [
        (
            heading["file_id"],
            heading["title"],
            heading["outline"],
            heading["todo"],
            heading["tags"],
            heading["stable"],
        )
        for heading in response.json()
    ] == [
        ("work", "Client Work", ["Client Work"], None, ["billable"], False),
        ("work", "Implementation", ["Client Work", "Implementation"], "TODO", ["backend"], False),
        ("work", "Support", ["Client Work", "Support"], "WAITING", ["customer"], False),
        ("other", "Internal", ["Internal"], None, [], False),
        ("other", "Planning", ["Internal", "Planning"], None, ["meeting"], False),
    ]


def test_headings_endpoint_filters_by_file_and_query(tmp_path: Path, monkeypatch) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text(
        """
* Client Work :billable:
** TODO Implementation :backend:
** Support :customer:
""".lstrip(),
        encoding="utf-8",
    )
    other_file = tmp_path / "other.org"
    other_file.write_text("* Backend Notes :backend:\n", encoding="utf-8")
    _write_config(
        tmp_path,
        f"""
[[files]]
id = "work"
path = "{work_file}"

[[files]]
id = "other"
path = "{other_file}"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/headings",
        params=[
            ("file_id", "work"),
            ("query", "backend"),
        ],
    )

    assert response.status_code == 200
    assert [(heading["file_id"], heading["title"]) for heading in response.json()] == [
        ("work", "Implementation")
    ]


def test_status_endpoint_returns_file_colors(tmp_path: Path, monkeypatch) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text("* Work\n", encoding="utf-8")
    _write_config(
        tmp_path,
        f"""
[[files]]
id = "work"
path = "{work_file}"
color = "#2563eb"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["file_colors"] == {"work": "#2563eb"}


def test_status_endpoint_lists_org_and_caldav_sources(tmp_path: Path, monkeypatch) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text("* Work\n", encoding="utf-8")
    home_file = tmp_path / "home.org"
    home_file.write_text("* Home\n", encoding="utf-8")
    _write_config(
        tmp_path,
        f"""
[[files]]
id = "work"
path = "{work_file}"
color = "#2563eb"

[[files]]
id = "home"
path = "{home_file}"

[[caldav_calendars]]
id = "personal"
name = "Personal Calendar"
url = "https://example.com/dav/personal"
username_env = "CALDAV_USER"
password_env = "CALDAV_PASSWORD"
color = "#16a34a"

[[caldav_calendars]]
id = "team"
name = "Team Calendar"
url = "https://example.com/dav/team"
username_env = "CALDAV_USER"
password_env = "CALDAV_PASSWORD"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["sources"] == [
        {
            "id": "work",
            "name": "work",
            "kind": "org",
            "color": "#2563eb",
            "editable": True,
        },
        {
            "id": "home",
            "name": "home",
            "kind": "org",
            "color": None,
            "editable": True,
        },
        {
            "id": "personal",
            "name": "Personal Calendar",
            "kind": "caldav",
            "color": "#16a34a",
            "editable": False,
        },
        {
            "id": "team",
            "name": "Team Calendar",
            "kind": "caldav",
            "color": None,
            "editable": False,
        },
    ]


@pytest.mark.parametrize("write_mode", ["read-only", "emacs"])
def test_status_endpoint_marks_org_sources_not_editable(
    tmp_path: Path, monkeypatch, write_mode: str
) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text("* Work\n", encoding="utf-8")
    _write_config(
        tmp_path,
        f"""
write_mode = "{write_mode}"
[[files]]
id = "work"
path = "{work_file}"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["sources"] == [
        {
            "id": "work",
            "name": "work",
            "kind": "org",
            "color": None,
            "editable": False,
        }
    ]


def test_status_endpoint_has_no_sources_without_configuration(monkeypatch, tmp_path: Path) -> None:
    _write_config(tmp_path, "", monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["sources"] == []


def _configure_work_file(
    tmp_path: Path, monkeypatch, org_text: str, *, write_mode: str | None = None
) -> Path:
    org_file = tmp_path / "work.org"
    org_file.write_text(org_text, encoding="utf-8")
    write_mode_line = f'write_mode = "{write_mode}"\n' if write_mode else ""
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"
{write_mode_line}
[[files]]
id = "work"
path = "{org_file}"
""",
        monkeypatch,
    )
    return org_file


def test_patch_clock_updates_line_preserves_unrelated_content_and_indentation(
    tmp_path: Path, monkeypatch
) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Client Work :billable:\n"
        "** Implementation\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 10:45] =>  1:30\n"
        "** Review\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}

    before = client.get("/api/v1/clocks", params=window).json()
    implementation = next(c for c in before["clocks"] if c["heading_title"] == "Implementation")

    patch_response = client.patch(
        f"/api/v1/clocks/{implementation['id']}",
        json={
            "start": "2026-07-31T09:30:00+02:00",
            "end": "2026-07-31T10:45:00+02:00",
            "expected_revision": implementation["revision"],
        },
    )

    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["start"] == "2026-07-31T09:30:00+02:00"
    assert body["end"] == "2026-07-31T10:45:00+02:00"
    assert body["duration_minutes"] == 75
    assert body["id"] != implementation["id"]
    assert body["revision"] != implementation["revision"]

    updated_text = org_file.read_text(encoding="utf-8")
    assert updated_text == (
        "* Client Work :billable:\n"
        "** Implementation\n"
        "  CLOCK: [2026-07-31 Fri 09:30]--[2026-07-31 Fri 10:45] =>  1:15\n"
        "** Review\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30\n"
    )

    after = client.get("/api/v1/clocks", params=window).json()
    updated = next(c for c in after["clocks"] if c["heading_title"] == "Implementation")
    review = next(c for c in after["clocks"] if c["heading_title"] == "Review")

    assert updated["start"] == "2026-07-31T09:30:00+02:00"
    assert updated["end"] == "2026-07-31T10:45:00+02:00"
    assert updated["duration_minutes"] == 75
    assert updated["id"] == body["id"]
    assert updated["revision"] == body["revision"]
    assert review["start"] == "2026-07-31T11:00:00+02:00"
    assert review["end"] == "2026-07-31T11:30:00+02:00"


def test_patch_clock_rejects_stale_revision(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}

    before = client.get("/api/v1/clocks", params=window).json()
    clock = before["clocks"][0]

    org_file.write_text(
        "* Work :urgent:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        encoding="utf-8",
    )

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T09:30:00+02:00",
            "end": "2026-07-31T10:45:00+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_conflict"


def test_patch_clock_unknown_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())

    response = client.patch(
        "/api/v1/clocks/clock:work:doesnotexist",
        json={
            "start": "2026-07-31T09:30:00+02:00",
            "end": "2026-07-31T10:45:00+02:00",
            "expected_revision": revision_for_file(org_file),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_clock_id"


def test_patch_clock_invalid_time_range_returns_422(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T10:45:00+02:00",
            "end": "2026-07-31T09:30:00+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_time_range"


def test_patch_clock_rejects_when_read_only(tmp_path: Path, monkeypatch, caplog) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        write_mode="read-only",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    with caplog.at_level("WARNING", logger="stempelwerk.api.routes"):
        response = client.patch(
            f"/api/v1/clocks/{clock['id']}",
            json={
                "start": "2026-07-31T09:30:00+02:00",
                "end": "2026-07-31T10:45:00+02:00",
                "expected_revision": clock["revision"],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "read_only"
    assert any("read-only" in record.message for record in caplog.records)


def test_patch_clock_rejects_when_emacs_write_mode(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        write_mode="emacs",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T09:30:00+02:00",
            "end": "2026-07-31T10:45:00+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "emacs_not_supported"


def _configure_backup_file(tmp_path: Path, monkeypatch) -> Path:
    org_file = tmp_path / "work.org"
    org_file.write_text(
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        encoding="utf-8",
    )
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"

[[files]]
id = "work"
path = "{org_file}"
""",
        monkeypatch,
    )
    return org_file


def test_backup_endpoint_creates_backup_of_current_contents(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_backup_file(tmp_path, monkeypatch)
    original_text = org_file.read_text(encoding="utf-8")
    client = TestClient(create_app())

    response = client.post("/api/v1/files/work/backups")

    assert response.status_code == 201
    body = response.json()
    assert body["file_id"] == "work"
    assert body["filename"].startswith("work.org.bak.")
    assert body["created_at"]

    backup_path = tmp_path / body["filename"]
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original_text


def test_backup_endpoint_lists_created_backups_oldest_first(tmp_path: Path, monkeypatch) -> None:
    _configure_backup_file(tmp_path, monkeypatch)
    (tmp_path / "work.org.bak.20260101T120000000000").write_text("old", encoding="utf-8")
    client = TestClient(create_app())

    created = client.post("/api/v1/files/work/backups")
    assert created.status_code == 201

    response = client.get("/api/v1/files/work/backups")

    assert response.status_code == 200
    body = response.json()
    filenames = [backup["filename"] for backup in body["backups"]]
    assert filenames == ["work.org.bak.20260101T120000000000", created.json()["filename"]]
    assert body["backups"][0]["created_at"].startswith("2026-01-01T12:00:00")
    assert all(backup["file_id"] == "work" for backup in body["backups"])


def test_backup_endpoint_returns_empty_list_without_backups(tmp_path: Path, monkeypatch) -> None:
    _configure_backup_file(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/v1/files/work/backups")

    assert response.status_code == 200
    assert response.json() == {"backups": []}


def test_backup_endpoint_ignores_files_without_valid_timestamp(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_backup_file(tmp_path, monkeypatch)
    (org_file.parent / "work.org.bak.manual-copy").write_text("stray", encoding="utf-8")
    client = TestClient(create_app())

    response = client.get("/api/v1/files/work/backups")

    assert response.status_code == 200
    assert response.json() == {"backups": []}


def test_backup_endpoint_unknown_file_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    _configure_backup_file(tmp_path, monkeypatch)
    client = TestClient(create_app())

    post_response = client.post("/api/v1/files/other/backups")
    get_response = client.get("/api/v1/files/other/backups")

    assert post_response.status_code == 404
    assert post_response.json()["detail"]["code"] == "unknown_file_id"
    assert get_response.status_code == 404
    assert get_response.json()["detail"]["code"] == "unknown_file_id"


def test_backup_endpoint_missing_file_returns_422(tmp_path: Path, monkeypatch) -> None:
    _configure_backup_file(tmp_path, monkeypatch)
    missing = tmp_path / "work.org"
    missing.unlink()
    client = TestClient(create_app())

    response = client.post("/api/v1/files/work/backups")

    assert response.status_code == 422


def test_backup_endpoint_works_in_read_only_mode(tmp_path: Path, monkeypatch) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        encoding="utf-8",
    )
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"
write_mode = "read-only"

[[files]]
id = "work"
path = "{org_file}"
""",
        monkeypatch,
    )
    client = TestClient(create_app())

    response = client.post("/api/v1/files/work/backups")

    assert response.status_code == 201


def _work_heading_id(client: TestClient, outline: list[str]) -> str:
    headings = client.get("/api/v1/headings").json()
    return next(h["id"] for h in headings if h["outline"] == outline)


def _work_revision(client: TestClient, window: dict[str, str]) -> str:
    return client.get("/api/v1/clocks", params=window).json()["revisions"]["work"]


def test_rename_heading_updates_one_line_and_the_calendar(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Acme\n"
        "** TODO Implementation :backend:\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 10:45] =>  1:30\n"
        "** Review\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    heading_id = _work_heading_id(client, ["Acme", "Implementation"])
    revision = _work_revision(client, window)

    response = client.patch(
        f"/api/v1/files/work/headings/{heading_id}",
        json={"title": "Coding", "expected_revision": revision},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert org_file.read_text(encoding="utf-8") == (
        "* Acme\n"
        "** TODO Coding :backend:\n"
        "  CLOCK: [2026-07-31 Fri 09:15]--[2026-07-31 Fri 10:45] =>  1:30\n"
        "** Review\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30\n"
    )

    clocks = client.get("/api/v1/clocks", params=window).json()["clocks"]
    titles = {clock["heading_title"] for clock in clocks}
    assert titles == {"Coding", "Review"}


def test_rename_heading_rejects_stale_revision(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    heading_id = _work_heading_id(client, ["Work"])
    before = org_file.read_bytes()

    response = client.patch(
        f"/api/v1/files/work/headings/{heading_id}",
        json={"title": "New", "expected_revision": "sha256:stale"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_conflict"
    assert org_file.read_bytes() == before


def test_rename_heading_unknown_heading_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    revision = _work_revision(
        client, {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    )

    response = client.patch(
        "/api/v1/files/work/headings/heading:doesnotexist",
        json={"title": "New", "expected_revision": revision},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_heading_id"


def test_rename_heading_unknown_file_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    heading_id = _work_heading_id(client, ["Work"])

    response = client.patch(
        f"/api/v1/files/other/headings/{heading_id}",
        json={"title": "New", "expected_revision": "sha256:stale"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_file_id"


def test_rename_heading_empty_title_returns_422(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    heading_id = _work_heading_id(client, ["Work"])
    revision = _work_revision(
        client, {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    )

    response = client.patch(
        f"/api/v1/files/work/headings/{heading_id}",
        json={"title": "   ", "expected_revision": revision},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_title"


def test_rename_heading_rejects_when_read_only(tmp_path: Path, monkeypatch, caplog) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        write_mode="read-only",
    )
    client = TestClient(create_app())
    heading_id = _work_heading_id(client, ["Work"])

    with caplog.at_level("WARNING", logger="stempelwerk.api.routes"):
        response = client.patch(
            f"/api/v1/files/work/headings/{heading_id}",
            json={"title": "New", "expected_revision": "sha256:stale"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "read_only"
    assert any("read-only" in record.message for record in caplog.records)


def test_rename_heading_rejects_when_emacs_write_mode(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        write_mode="emacs",
    )
    client = TestClient(create_app())
    heading_id = _work_heading_id(client, ["Work"])

    response = client.patch(
        f"/api/v1/files/work/headings/{heading_id}",
        json={"title": "New", "expected_revision": "sha256:stale"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "emacs_not_supported"


def test_patch_clock_ignores_seconds(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T09:30:45+02:00",
            "end": "2026-07-31T10:45:59+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 200
    assert org_file.read_text(encoding="utf-8") == (
        "* Work\nCLOCK: [2026-07-31 Fri 09:30]--[2026-07-31 Fri 10:45] =>  1:15\n"
    )


def test_patch_clock_rejects_range_shorter_than_a_minute(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]
    before = org_file.read_bytes()

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T09:00:10+02:00",
            "end": "2026-07-31T09:00:50+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_time_range"
    assert org_file.read_bytes() == before


def test_patch_clock_allows_overlapping_entries(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* First\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        "* Second\nCLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 12:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clocks = client.get("/api/v1/clocks", params=window).json()["clocks"]
    second = next(c for c in clocks if c["heading_title"] == "Second")

    response = client.patch(
        f"/api/v1/clocks/{second['id']}",
        json={
            "start": "2026-07-31T09:30:00+02:00",
            "end": "2026-07-31T10:30:00+02:00",
            "expected_revision": second["revision"],
        },
    )

    assert response.status_code == 200
    after = client.get("/api/v1/clocks", params=window).json()["clocks"]
    assert len(after) == 2
    assert org_file.read_text(encoding="utf-8") == (
        "* First\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        "* Second\nCLOCK: [2026-07-31 Fri 09:30]--[2026-07-31 Fri 10:30] =>  1:00\n"
    )


def test_patch_clock_then_rename_with_returned_revision(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    update_response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T09:30:00+02:00",
            "end": "2026-07-31T10:30:00+02:00",
            "expected_revision": clock["revision"],
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()

    heading_id = next(
        h["id"] for h in client.get("/api/v1/headings").json() if h["outline"] == ["Work"]
    )
    rename_response = client.patch(
        f"/api/v1/files/work/headings/{heading_id}",
        json={"title": "Renamed", "expected_revision": updated["revision"]},
    )

    assert rename_response.status_code == 204


def _heading_id_by_outline(client: TestClient, file_id: str, outline: list[str]) -> str:
    return next(
        h["id"]
        for h in client.get("/api/v1/headings").json()
        if h["outline"] == outline and h["file_id"] == file_id
    )


def test_patch_clock_with_heading_id_moves_the_entry(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]
    target_id = _heading_id_by_outline(client, "work", ["Target"])

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": clock["start"],
            "end": clock["end"],
            "expected_revision": clock["revision"],
            "heading_id": target_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["heading_title"] == "Target"
    assert body["outline"] == ["Target"]
    assert org_file.read_text(encoding="utf-8") == (
        "* Source\n"
        "* Target\n"
        ":LOGBOOK:\n"
        "CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n"
        ":END:\n"
    )

    after = client.get("/api/v1/clocks", params=window).json()["clocks"]
    assert len(after) == 1
    assert after[0]["id"] == body["id"]
    assert after[0]["revision"] == body["revision"]
    assert after[0]["heading_title"] == "Target"


def test_patch_clock_with_heading_id_and_new_times(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]
    target_id = _heading_id_by_outline(client, "work", ["Target"])

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": "2026-07-31T11:30:00+02:00",
            "end": "2026-07-31T12:45:00+02:00",
            "expected_revision": clock["revision"],
            "heading_id": target_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["heading_title"] == "Target"
    assert body["start"] == "2026-07-31T11:30:00+02:00"
    assert body["duration_minutes"] == 75


def test_patch_clock_rejects_heading_of_another_file(tmp_path: Path, monkeypatch) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text(
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n",
        encoding="utf-8",
    )
    other_file = tmp_path / "other.org"
    other_file.write_text("* Other target\n", encoding="utf-8")
    _write_config(
        tmp_path,
        f"""
timezone = "Europe/Vienna"

[[files]]
id = "work"
path = "{work_file}"

[[files]]
id = "other"
path = "{other_file}"
""",
        monkeypatch,
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]
    other_target_id = _heading_id_by_outline(client, "other", ["Other target"])
    work_before = work_file.read_bytes()
    other_before = other_file.read_bytes()

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": clock["start"],
            "end": clock["end"],
            "expected_revision": clock["revision"],
            "heading_id": other_target_id,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_heading_id"
    assert work_file.read_bytes() == work_before
    assert other_file.read_bytes() == other_before


def test_patch_clock_rejects_unknown_heading_id(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": clock["start"],
            "end": clock["end"],
            "expected_revision": clock["revision"],
            "heading_id": "heading:missing",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_heading_id"


def test_patch_clock_move_rejects_stale_revision(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]
    target_id = _heading_id_by_outline(client, "work", ["Target"])

    response = client.patch(
        f"/api/v1/clocks/{clock['id']}",
        json={
            "start": clock["start"],
            "end": clock["end"],
            "expected_revision": "sha256:stale",
            "heading_id": target_id,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_conflict"


def test_patch_clock_move_rejects_when_read_only(tmp_path: Path, monkeypatch, caplog) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Source\n:LOGBOOK:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n:END:\n* Target\n",
        write_mode="read-only",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]
    target_id = _heading_id_by_outline(client, "work", ["Target"])

    with caplog.at_level("WARNING", logger="stempelwerk.api.routes"):
        response = client.patch(
            f"/api/v1/clocks/{clock['id']}",
            json={
                "start": clock["start"],
                "end": clock["end"],
                "expected_revision": clock["revision"],
                "heading_id": target_id,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "read_only"
    assert any("read-only" in record.message for record in caplog.records)


def test_post_clock_split_writes_two_lines_and_returns_both_entries(
    tmp_path: Path, monkeypatch
) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Client Work :billable:\n"
        "** Implementation\n"
        "  CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:45] =>  1:45\n"
        "** Review\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}

    before = client.get("/api/v1/clocks", params=window).json()
    implementation = next(c for c in before["clocks"] if c["heading_title"] == "Implementation")

    response = client.post(
        f"/api/v1/clocks/{implementation['id']}/split",
        json={
            "split_at": "2026-07-31T09:30:00+02:00",
            "expected_revision": implementation["revision"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    first, second = body["clocks"]
    assert first["start"] == "2026-07-31T09:00:00+02:00"
    assert first["end"] == "2026-07-31T09:30:00+02:00"
    assert first["duration_minutes"] == 30
    assert second["start"] == "2026-07-31T09:30:00+02:00"
    assert second["end"] == "2026-07-31T10:45:00+02:00"
    assert second["duration_minutes"] == 75
    assert first["heading_id"] == second["heading_id"] == implementation["heading_id"]
    assert first["id"] != second["id"] != implementation["id"]
    assert first["revision"] == second["revision"]
    assert first["revision"] != implementation["revision"]

    assert org_file.read_text(encoding="utf-8") == (
        "* Client Work :billable:\n"
        "** Implementation\n"
        "  CLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 09:30] =>  0:30\n"
        "  CLOCK: [2026-07-31 Fri 09:30]--[2026-07-31 Fri 10:45] =>  1:15\n"
        "** Review\n"
        "CLOCK: [2026-07-31 Fri 11:00]--[2026-07-31 Fri 11:30] =>  0:30\n"
    )

    after = client.get("/api/v1/clocks", params=window).json()
    split_entries = [c for c in after["clocks"] if c["heading_title"] == "Implementation"]
    assert [(c["id"], c["duration_minutes"]) for c in split_entries] == [
        (first["id"], 30),
        (second["id"], 75),
    ]
    review = next(c for c in after["clocks"] if c["heading_title"] == "Review")
    assert review["start"] == "2026-07-31T11:00:00+02:00"


def test_post_clock_split_ignores_seconds(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.post(
        f"/api/v1/clocks/{clock['id']}/split",
        json={
            "split_at": "2026-07-31T09:29:59+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 200
    first, second = response.json()["clocks"]
    assert first["end"] == "2026-07-31T09:29:00+02:00"
    assert second["start"] == "2026-07-31T09:29:00+02:00"


@pytest.mark.parametrize(
    "split_at",
    [
        "2026-07-31T09:00:00+02:00",
        "2026-07-31T10:00:00+02:00",
        "2026-07-31T08:30:00+02:00",
        "2026-07-31T10:30:00+02:00",
    ],
)
def test_post_clock_split_outside_the_entry_returns_422(
    tmp_path: Path, monkeypatch, split_at: str
) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.post(
        f"/api/v1/clocks/{clock['id']}/split",
        json={"split_at": split_at, "expected_revision": clock["revision"]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_time_range"


def test_post_clock_split_rejects_stale_revision(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    org_file.write_text(
        "* Work :urgent:\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        encoding="utf-8",
    )

    response = client.post(
        f"/api/v1/clocks/{clock['id']}/split",
        json={
            "split_at": "2026-07-31T09:30:00+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_conflict"


def test_post_clock_split_unknown_id_returns_404(tmp_path: Path, monkeypatch) -> None:
    org_file = _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/clocks/clock:work:doesnotexist/split",
        json={
            "split_at": "2026-07-31T09:30:00+02:00",
            "expected_revision": revision_for_file(org_file),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_clock_id"


def test_post_clock_split_rejects_when_read_only(tmp_path: Path, monkeypatch, caplog) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        write_mode="read-only",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    with caplog.at_level("WARNING", logger="stempelwerk.api.routes"):
        response = client.post(
            f"/api/v1/clocks/{clock['id']}/split",
            json={
                "split_at": "2026-07-31T09:30:00+02:00",
                "expected_revision": clock["revision"],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "read_only"
    assert any("read-only" in record.message for record in caplog.records)


def test_post_clock_split_rejects_when_emacs_write_mode(tmp_path: Path, monkeypatch) -> None:
    _configure_work_file(
        tmp_path,
        monkeypatch,
        "* Work\nCLOCK: [2026-07-31 Fri 09:00]--[2026-07-31 Fri 10:00] =>  1:00\n",
        write_mode="emacs",
    )
    client = TestClient(create_app())
    window = {"start": "2026-07-31T00:00:00+02:00", "end": "2026-08-01T00:00:00+02:00"}
    clock = client.get("/api/v1/clocks", params=window).json()["clocks"][0]

    response = client.post(
        f"/api/v1/clocks/{clock['id']}/split",
        json={
            "split_at": "2026-07-31T09:30:00+02:00",
            "expected_revision": clock["revision"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "emacs_not_supported"


# --- CalDAV events endpoint ---


class FakeCalDAVReader:
    """Stand-in for CalDAVReader that records calls and returns canned results.

    The class variable ``behavior`` maps calendar ids to either a list of
    CalDAVEvent objects or an exception instance to raise for that calendar.
    """

    behavior: ClassVar[dict[str, list[CalDAVEvent] | Exception]] = {}
    calls: ClassVar[list[tuple[str, str, str, bool]]] = []
    init_kwargs: ClassVar[list[dict[str, object]]] = []

    def __init__(
        self,
        calendars: list[CalDAVCalendarConfig],
        *,
        timeout_seconds: int = 10,
        cache_seconds: int = 60,
        **kwargs: object,
    ) -> None:
        self.calendars = calendars
        self.init_kwargs.append(
            {
                "calendar_ids": [calendar.id for calendar in calendars],
                "timeout_seconds": timeout_seconds,
                "cache_seconds": cache_seconds,
            }
        )

    def read_events(
        self,
        calendar_id: str,
        start: datetime,
        end: datetime,
        *,
        refresh: bool = False,
    ) -> list[CalDAVEvent]:
        FakeCalDAVReader.calls.append((calendar_id, start.isoformat(), end.isoformat(), refresh))
        outcome = FakeCalDAVReader.behavior[calendar_id]
        if isinstance(outcome, Exception):
            raise outcome
        return list(outcome)


def _caldav_event(calendar_id: str, event_id: str, title: str = "Event") -> CalDAVEvent:
    start = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    end = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    return CalDAVEvent(
        id=event_id,
        calendar_id=calendar_id,
        calendar_name=calendar_id,
        title=title,
        start=start,
        end=end,
        all_day=False,
    )


def _write_caldav_config(tmp_path: Path, monkeypatch, *, timeout: int = 7, cache: int = 42):
    _write_config(
        tmp_path,
        f"""
caldav_timeout_seconds = {timeout}
caldav_cache_seconds = {cache}

[[caldav_calendars]]
id = "home"
name = "Home"
url = "https://caldav.example.invalid/home/"
username_env = "CALDAV_HOME_USER"
password_env = "CALDAV_HOME_PASS"

[[caldav_calendars]]
id = "work"
name = "Work"
url = "https://caldav.example.invalid/work/"
username_env = "CALDAV_WORK_USER"
password_env = "CALDAV_WORK_PASS"
""",
        monkeypatch,
    )


@pytest.fixture()
def fake_caldav_reader(monkeypatch):
    from stempelwerk.api import routes as routes_module

    FakeCalDAVReader.behavior = {}
    FakeCalDAVReader.calls = []
    FakeCalDAVReader.init_kwargs = []
    monkeypatch.setattr(routes_module, "CalDAVReader", FakeCalDAVReader)
    return FakeCalDAVReader


def test_caldav_events_without_calendars_returns_empty(monkeypatch, tmp_path) -> None:
    _write_config(tmp_path, "", monkeypatch)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params={"start": "2026-08-03T00:00:00+00:00", "end": "2026-08-04T00:00:00+00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["events"] == []
    assert body["errors"] == []


def test_caldav_events_without_ids_loads_all_calendars(
    fake_caldav_reader, tmp_path, monkeypatch
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    fake_caldav_reader.behavior = {
        "home": [_caldav_event("home", "caldav:home:1")],
        "work": [_caldav_event("work", "caldav:work:1")],
    }
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params={"start": "2026-08-03T00:00:00+00:00", "end": "2026-08-04T00:00:00+00:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [event["calendar_id"] for event in body["events"]] == ["home", "work"]
    assert [(call[0], call[3]) for call in fake_caldav_reader.calls] == [
        ("home", False),
        ("work", False),
    ]


def test_caldav_events_repeated_ids_keep_first_order_and_skip_duplicates(
    fake_caldav_reader, tmp_path, monkeypatch
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    fake_caldav_reader.behavior = {
        "home": [_caldav_event("home", "caldav:home:1")],
        "work": [_caldav_event("work", "caldav:work:1")],
    }
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params=[
            ("start", "2026-08-03T00:00:00+00:00"),
            ("end", "2026-08-04T00:00:00+00:00"),
            ("calendar_id", "work"),
            ("calendar_id", "home"),
            ("calendar_id", "work"),
        ],
    )

    assert response.status_code == 200
    # Combined events are sorted deterministically, the selection order shows
    # up in the reader calls instead.
    assert [event["calendar_id"] for event in response.json()["events"]] == ["home", "work"]
    assert [call[0] for call in fake_caldav_reader.calls] == ["work", "home"]


def test_caldav_events_unknown_ids_return_422_without_querying(
    fake_caldav_reader, tmp_path, monkeypatch
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params=[
            ("start", "2026-08-03T00:00:00+00:00"),
            ("end", "2026-08-04T00:00:00+00:00"),
            ("calendar_id", "zebra"),
            ("calendar_id", "home"),
            ("calendar_id", "alpaca"),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "unknown_calendar_id",
        "calendars": ["alpaca", "zebra"],
    }
    assert fake_caldav_reader.calls == []


def test_caldav_events_rejects_end_before_start(fake_caldav_reader, tmp_path, monkeypatch) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params={"start": "2026-08-04T00:00:00+00:00", "end": "2026-08-03T00:00:00+00:00"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "invalid_time_range"}
    assert fake_caldav_reader.calls == []


@pytest.mark.parametrize("naive_field", ["start", "end"])
def test_caldav_events_rejects_naive_datetimes(
    fake_caldav_reader, tmp_path, monkeypatch, naive_field
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    client = TestClient(create_app())

    params = {"start": "2026-08-03T00:00:00+00:00", "end": "2026-08-04T00:00:00+00:00"}
    params[naive_field] = "2026-08-03T00:00:00"

    response = client.get("/api/v1/caldav/events", params=params)

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "timezone_required"}
    assert fake_caldav_reader.calls == []


def test_caldav_events_failed_calendar_returns_error_and_keeps_events(
    fake_caldav_reader, tmp_path, monkeypatch, caplog
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    fake_caldav_reader.behavior = {
        "home": [_caldav_event("home", "caldav:home:1")],
        "work": RuntimeError("connect failed with secret-token-abc to /etc/passwd"),
    }
    client = TestClient(create_app())

    with caplog.at_level("WARNING", logger="stempelwerk.api.routes"):
        response = client.get(
            "/api/v1/caldav/events",
            params={"start": "2026-08-03T00:00:00+00:00", "end": "2026-08-04T00:00:00+00:00"},
        )

    assert response.status_code == 200
    body = response.json()
    assert [event["calendar_id"] for event in body["events"]] == ["home"]
    assert body["errors"] == [
        {
            "calendar_id": "work",
            "code": "unavailable",
            "message": "Calendar is unavailable",
        }
    ]
    assert "secret-token-abc" not in caplog.text
    assert "/etc/passwd" not in caplog.text
    warnings = [record for record in caplog.records if "work" in record.getMessage()]
    assert any("RuntimeError" in record.getMessage() for record in warnings)


def test_caldav_events_sort_events_deterministically(
    fake_caldav_reader, tmp_path, monkeypatch
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    fake_caldav_reader.behavior = {
        # Same start/end as the other calendars so ties are broken by
        # calendar_id, then event id.
        "work": [
            _caldav_event("work", "caldav:work:b"),
            _caldav_event("work", "caldav:work:a"),
        ],
        "home": [_caldav_event("home", "caldav:home:1")],
    }
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params={"start": "2026-08-03T00:00:00+00:00", "end": "2026-08-04T00:00:00+00:00"},
    )

    assert response.status_code == 200
    assert [(event["calendar_id"], event["id"]) for event in response.json()["events"]] == [
        ("home", "caldav:home:1"),
        ("work", "caldav:work:a"),
        ("work", "caldav:work:b"),
    ]


def test_caldav_events_forwards_refresh_flag(fake_caldav_reader, tmp_path, monkeypatch) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    fake_caldav_reader.behavior = {"home": [], "work": []}
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params={
            "start": "2026-08-03T00:00:00+00:00",
            "end": "2026-08-04T00:00:00+00:00",
            "refresh": "true",
        },
    )

    assert response.status_code == 200
    assert [(call[0], call[3]) for call in fake_caldav_reader.calls] == [
        ("home", True),
        ("work", True),
    ]


def test_caldav_events_forwards_configured_timeout_and_cache(
    fake_caldav_reader, tmp_path, monkeypatch
) -> None:
    _write_caldav_config(tmp_path, monkeypatch, timeout=13, cache=77)
    fake_caldav_reader.behavior = {"home": [], "work": []}
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/caldav/events",
        params={"start": "2026-08-03T00:00:00+00:00", "end": "2026-08-04T00:00:00+00:00"},
    )

    assert response.status_code == 200
    assert fake_caldav_reader.init_kwargs == [
        {
            "calendar_ids": ["home", "work"],
            "timeout_seconds": 13,
            "cache_seconds": 77,
        }
    ]


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
def test_caldav_events_rejects_write_methods(
    tmp_path, monkeypatch, fake_caldav_reader, method
) -> None:
    _write_caldav_config(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = getattr(client, method)("/api/v1/caldav/events")

    assert response.status_code == 405
