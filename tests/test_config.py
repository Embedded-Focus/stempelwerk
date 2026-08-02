from pathlib import Path

from stempelwerk.config import load_config


def test_load_config_from_toml(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Work\n", encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"""
timezone = "Europe/Vienna"

[[files]]
id = "work"
path = "{org_file}"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.timezone == "Europe/Vienna"
    assert config.files[0].id == "work"
    assert config.files[0].path == org_file


def test_load_config_accepts_file_color(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Work\n", encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"""
[[files]]
id = "work"
path = "{org_file}"
color = "#2563eb"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.files[0].color == "#2563eb"
