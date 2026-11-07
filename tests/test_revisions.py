from stempelwerk.revisions import revision_for_bytes


def test_revision_for_bytes_has_sha256_prefix() -> None:
    revision = revision_for_bytes(b"example")

    assert revision.startswith("sha256:")
    assert len(revision) == 71
