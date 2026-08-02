from pathlib import Path

from fastapi.testclient import TestClient

from stempelwerk.app import create_app


def test_status_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
    config_file = tmp_path / "config.toml"
    config_file.write_text(
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
        encoding="utf-8",
    )
    monkeypatch.setenv("STEMPELWERK_CONFIG", str(config_file))
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


def test_status_endpoint_returns_file_colors(tmp_path: Path, monkeypatch) -> None:
    work_file = tmp_path / "work.org"
    work_file.write_text("* Work\n", encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"""
[[files]]
id = "work"
path = "{work_file}"
color = "#2563eb"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("STEMPELWERK_CONFIG", str(config_file))
    client = TestClient(create_app())

    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["file_colors"] == {"work": "#2563eb"}
