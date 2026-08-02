"""Show hashing used for duplicate-notification prevention (PRD §14)."""

import hashlib

from app.schemas import Show


def show_hash(show: Show) -> str:
    """SHA256 over the identifying fields of a show.

    movie + theatre + date + time + format, normalized so cosmetic
    differences (case, stray spaces) don't produce new hashes.
    """
    parts = [
        show.movie,
        show.theatre,
        show.date.isoformat(),
        show.time,
        show.format,
    ]
    normalized = "|".join(" ".join(p.split()).lower() for p in (str(x) for x in parts))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
