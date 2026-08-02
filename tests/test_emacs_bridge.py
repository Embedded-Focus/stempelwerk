from stempelwerk.emacs_bridge import EmacsBridge


def test_emacs_bridge_reports_boolean_availability() -> None:
    assert isinstance(EmacsBridge().available(), bool)

