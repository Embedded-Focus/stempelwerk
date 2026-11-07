from hashlib import sha256
from pathlib import Path


def revision_for_bytes(raw: bytes) -> str:
    return f"sha256:{sha256(raw).hexdigest()}"


def revision_for_file(path: Path) -> str:
    return revision_for_bytes(path.read_bytes())
