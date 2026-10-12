from hashlib import sha256
from secrets import token_bytes
from uuid import UUID

from app.game.types import RuleError, require_ids

GENERATION_VERSION = 1


def generate_seed() -> bytes:
    """Server-side entropy; persist the seed privately alongside generator v1."""
    return token_bytes(32)


def seeded_order(event_ids: tuple[UUID, ...], seed: bytes) -> tuple[UUID, ...]:
    """Generator v1: canonical UUID bytes, independent of catalog row order."""
    require_ids(event_ids, "invalid_order")
    if type(seed) is not bytes or not seed:
        raise RuleError("invalid_seed")
    return tuple(
        sorted(
            event_ids, key=lambda id_: (sha256(seed + id_.bytes).digest(), id_.bytes)
        )
    )
