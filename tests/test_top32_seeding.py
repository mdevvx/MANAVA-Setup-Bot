"""Seeding: #1 v #32, #2 v #31, ... #16 v #17 — generated generically off
however many squads actually got a seed, not hard-coded to 32."""

from __future__ import annotations

from uuid import uuid4

from src.models.season import QualificationEntry, QualificationEntryStatus
from src.services.top32_service import generate_seed_pairings


def _entry(*, rank: int, seed: int | None) -> QualificationEntry:
    return QualificationEntry(
        season_id=uuid4(),
        squad_id=uuid4(),
        squad_name=f"Squad{rank}",
        rank=rank,
        season_xp_snapshot=0,
        lifetime_xp_snapshot=0,
        status=QualificationEntryStatus.QUALIFIED,
        seed=seed,
        decided_by=None,
        decided_at=None,
        decided_reason=None,
    )


def test_full_32_pairs_1v32_through_16v17() -> None:
    entries = [_entry(rank=i, seed=i) for i in range(1, 33)]

    pairings = generate_seed_pairings(entries)

    assert len(pairings) == 16
    assert (pairings[0].seed_a, pairings[0].seed_b) == (1, 32)
    assert (pairings[1].seed_a, pairings[1].seed_b) == (2, 31)
    assert (pairings[-1].seed_a, pairings[-1].seed_b) == (16, 17)


def test_pairs_the_right_squads_not_just_the_right_numbers() -> None:
    entries = [_entry(rank=i, seed=i) for i in range(1, 33)]
    by_seed = {e.seed: e for e in entries}

    pairings = generate_seed_pairings(entries)

    first = pairings[0]
    assert first.squad_a_id == by_seed[1].squad_id
    assert first.squad_b_id == by_seed[32].squad_id


def test_fewer_than_32_qualified_still_pairs_correctly() -> None:
    """If only 20 squads exist, seeding should pair #1v#20 ... #10v#11 — not
    assume a fixed 32-slot bracket."""
    entries = [_entry(rank=i, seed=i) for i in range(1, 21)]

    pairings = generate_seed_pairings(entries)

    assert len(pairings) == 10
    assert (pairings[0].seed_a, pairings[0].seed_b) == (1, 20)
    assert (pairings[-1].seed_a, pairings[-1].seed_b) == (10, 11)


def test_unseeded_entries_are_ignored() -> None:
    """Before /season publish-top32 runs, no entry has a seed yet — pairing
    generation should return nothing rather than crash."""
    entries = [_entry(rank=i, seed=None) for i in range(1, 33)]

    assert generate_seed_pairings(entries) == []


def test_odd_count_drops_the_unpaired_middle_seed() -> None:
    entries = [_entry(rank=i, seed=i) for i in range(1, 4)]  # seeds 1, 2, 3

    pairings = generate_seed_pairings(entries)

    assert len(pairings) == 1
    assert (pairings[0].seed_a, pairings[0].seed_b) == (1, 3)
