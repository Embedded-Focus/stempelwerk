from dataclasses import dataclass
from shutil import which


@dataclass(frozen=True)
class EmacsBridge:
    emacsclient: str = "emacsclient"

    def available(self) -> bool:
        return which(self.emacsclient) is not None

