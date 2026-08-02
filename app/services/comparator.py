"""State comparison: which shows are new since the last check (PRD §11, FR6).

Only added shows trigger notifications; removed hashes are reported for
observability but intentionally kept in history so a show that disappears
and reappears doesn't re-notify.
"""

from dataclasses import dataclass, field

from app.schemas import Show
from app.utils.hashing import show_hash


@dataclass
class ShowDiff:
    added: list[Show] = field(default_factory=list)
    removed_hashes: set[str] = field(default_factory=set)


def diff(known_hashes: set[str], current_shows: list[Show]) -> ShowDiff:
    current_by_hash: dict[str, Show] = {}
    for show in current_shows:
        current_by_hash.setdefault(show_hash(show), show)

    added = [show for h, show in current_by_hash.items() if h not in known_hashes]
    removed = known_hashes - set(current_by_hash)
    return ShowDiff(added=added, removed_hashes=removed)
