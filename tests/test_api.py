from pathlib import Path

from fastapi.testclient import TestClient

from stempelwerk.app import create_app
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
