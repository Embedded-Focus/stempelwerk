from pathlib import Path

from fastapi.testclient import TestClient

from stempelwerk.app import create_app


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


def test_clocks_endpoint_returns_entries_parsed_from_org_file(
    tmp_path: Path, monkeypatch
) -> None:
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
