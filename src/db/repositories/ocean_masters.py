from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from src.errors import MatchNotFoundError, OceanMastersStateError
from src.models.ocean_masters import MatchStatus, OceanMasters, OceanMastersMatch, OceanMastersMode, OceanMastersStatus


def _row_to_tournament(row: asyncpg.Record) -> OceanMasters:
    return OceanMasters(
        id=row["id"],
        season_id=row["season_id"],
        mode=OceanMastersMode(row["mode"]),
        games=tuple(row["games"]),
        min_squads_required=row["min_squads_required"],
        status=OceanMastersStatus(row["status"]),
        launched_at=row["launched_at"],
        launched_by=row["launched_by"],
        completed_at=row["completed_at"],
        winner_squad_id=row["winner_squad_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _row_to_match(row: asyncpg.Record) -> OceanMastersMatch:
    raw_results = row["per_discipline_results"]
    results = json.loads(raw_results) if isinstance(raw_results, str) else (raw_results or {})
    return OceanMastersMatch(
        id=row["id"],
        tournament_id=row["tournament_id"],
        round=row["round"],
        seed_a=row["seed_a"],
        seed_b=row["seed_b"],
        squad_a_id=row["squad_a_id"],
        squad_b_id=row["squad_b_id"],
        squad_a_name=row["squad_a_name"],
        squad_b_name=row["squad_b_name"],
        per_discipline_results=dict(results),
        winner_squad_id=row["winner_squad_id"],
        status=MatchStatus(row["status"]),
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        decided_reason=row["decided_reason"],
    )


async def create_tournament(
    conn: asyncpg.Connection,
    *,
    season_id: UUID,
    mode: OceanMastersMode,
    games: list[str],
    min_squads_required: int | None,
    created_by: int,
) -> OceanMasters:
    try:
        row = await conn.fetchrow(
            """
            insert into ocean_masters (season_id, mode, games, min_squads_required, created_by)
            values ($1, $2, $3, $4, $5)
            returning *
            """,
            season_id,
            mode.value,
            games,
            min_squads_required,
            created_by,
        )
    except asyncpg.UniqueViolationError as exc:
        raise OceanMastersStateError("This season already has an Ocean Masters tournament.") from exc
    assert row is not None
    return _row_to_tournament(row)


async def get_by_season(conn: asyncpg.Connection, season_id: UUID) -> OceanMasters | None:
    row = await conn.fetchrow("select * from ocean_masters where season_id = $1", season_id)
    return _row_to_tournament(row) if row else None


async def get_by_id(conn: asyncpg.Connection, tournament_id: UUID) -> OceanMasters:
    row = await conn.fetchrow("select * from ocean_masters where id = $1", tournament_id)
    if row is None:
        raise OceanMastersStateError("That tournament doesn't exist.")
    return _row_to_tournament(row)


async def launch(conn: asyncpg.Connection, tournament_id: UUID, *, actor_id: int) -> OceanMasters:
    row = await conn.fetchrow(
        """
        update ocean_masters
        set status = 'launched', launched_at = now(), launched_by = $2
        where id = $1 and status = 'draft'
        returning *
        """,
        tournament_id,
        actor_id,
    )
    if row is None:
        raise OceanMastersStateError("This tournament isn't in draft, so it can't be launched.")
    return _row_to_tournament(row)


async def mark_completed(conn: asyncpg.Connection, tournament_id: UUID, *, winner_squad_id: UUID) -> OceanMasters:
    row = await conn.fetchrow(
        """
        update ocean_masters
        set status = 'completed', completed_at = now(), winner_squad_id = $2
        where id = $1
        returning *
        """,
        tournament_id,
        winner_squad_id,
    )
    assert row is not None
    return _row_to_tournament(row)


async def set_champion(conn: asyncpg.Connection, tournament_id: UUID, *, winner_squad_id: UUID) -> OceanMasters:
    """Result correction on an already-completed final: swaps the champion,
    keeping the original completed_at."""
    row = await conn.fetchrow(
        """
        update ocean_masters
        set winner_squad_id = $2
        where id = $1 and status = 'completed'
        returning *
        """,
        tournament_id,
        winner_squad_id,
    )
    if row is None:
        raise OceanMastersStateError("This tournament isn't completed, so there's no champion to correct.")
    return _row_to_tournament(row)


async def replace_match_squad(
    conn: asyncpg.Connection, match_id: UUID, *, old_squad_id: UUID, new_squad_id: UUID, new_seed: int
) -> OceanMastersMatch:
    """Result correction: puts the corrected winner into the next-round match
    in place of the squad that wrongly advanced. Only touches a match that
    hasn't been played yet."""
    row = await conn.fetchrow(
        """
        update ocean_masters_matches
        set squad_a_id = case when squad_a_id = $2 then $3 else squad_a_id end,
            seed_a     = case when squad_a_id = $2 then $4 else seed_a end,
            squad_b_id = case when squad_b_id = $2 then $3 else squad_b_id end,
            seed_b     = case when squad_b_id = $2 then $4 else seed_b end
        where id = $1 and status = 'pending' and per_discipline_results = '{}'::jsonb
          and (squad_a_id = $2 or squad_b_id = $2)
        returning id
        """,
        match_id,
        old_squad_id,
        new_squad_id,
        new_seed,
    )
    if row is None:
        raise OceanMastersStateError(
            "The next-round match changed while correcting this result — check /oceanmasters bracket and retry."
        )
    return await get_match(conn, match_id)


async def insert_round(
    conn: asyncpg.Connection,
    tournament_id: UUID,
    round_number: int,
    pairings: list[tuple[int, int, UUID | None, UUID | None]],
) -> int:
    """`pairings` is (seed_a, seed_b, squad_a_id, squad_b_id) tuples, already
    in bracket order. Returns how many matches were created."""
    rows = await conn.fetch(
        """
        insert into ocean_masters_matches (tournament_id, round, seed_a, seed_b, squad_a_id, squad_b_id)
        select $1, $2, x.seed_a, x.seed_b, x.squad_a_id, x.squad_b_id
        from unnest($3::int[], $4::int[], $5::uuid[], $6::uuid[]) as x(seed_a, seed_b, squad_a_id, squad_b_id)
        returning id
        """,
        tournament_id,
        round_number,
        [p[0] for p in pairings],
        [p[1] for p in pairings],
        [p[2] for p in pairings],
        [p[3] for p in pairings],
    )
    return len(rows)


_MATCH_SELECT = """
    select m.*, sa.name as squad_a_name, sb.name as squad_b_name
    from ocean_masters_matches m
    left join squads sa on sa.id = m.squad_a_id
    left join squads sb on sb.id = m.squad_b_id
"""


async def get_match(conn: asyncpg.Connection, match_id: UUID) -> OceanMastersMatch:
    row = await conn.fetchrow(f"{_MATCH_SELECT} where m.id = $1", match_id)
    if row is None:
        raise MatchNotFoundError()
    return _row_to_match(row)


async def get_round_matches(conn: asyncpg.Connection, tournament_id: UUID, round_number: int) -> list[OceanMastersMatch]:
    rows = await conn.fetch(
        f"{_MATCH_SELECT} where m.tournament_id = $1 and m.round = $2 order by m.seed_a", tournament_id, round_number
    )
    return [_row_to_match(r) for r in rows]


async def get_bracket(conn: asyncpg.Connection, tournament_id: UUID) -> list[OceanMastersMatch]:
    rows = await conn.fetch(
        f"{_MATCH_SELECT} where m.tournament_id = $1 order by m.round, m.seed_a", tournament_id
    )
    return [_row_to_match(r) for r in rows]


async def find_match_ids_by_prefix(conn: asyncpg.Connection, tournament_id: UUID, prefix: str) -> list[UUID]:
    """Resolves the short match code shown in /oceanmasters bracket (the
    first characters of the match UUID) within one tournament. Callers treat
    more than one hit as ambiguous."""
    rows = await conn.fetch(
        "select id from ocean_masters_matches where tournament_id = $1 and id::text like $2 || '%' limit 2",
        tournament_id,
        prefix.lower(),
    )
    return [r["id"] for r in rows]


async def set_discipline_result(
    conn: asyncpg.Connection, match_id: UUID, game: str, winner_squad_id: UUID
) -> OceanMastersMatch:
    row = await conn.fetchrow(
        """
        update ocean_masters_matches
        set per_discipline_results = per_discipline_results || jsonb_build_object($2::text, $3::text)
        where id = $1 and status = 'pending'
        returning id
        """,
        match_id,
        game,
        str(winner_squad_id),
    )
    if row is None:
        raise MatchNotFoundError()
    return await get_match(conn, match_id)


async def decide_match(
    conn: asyncpg.Connection,
    match_id: UUID,
    *,
    winner_squad_id: UUID,
    status: MatchStatus,
    decided_by: int,
    reason: str | None,
) -> OceanMastersMatch:
    row = await conn.fetchrow(
        """
        update ocean_masters_matches
        set winner_squad_id = $2, status = $3, decided_by = $4, decided_at = now(), decided_reason = $5
        where id = $1 and status = 'pending'
        returning id
        """,
        match_id,
        winner_squad_id,
        status.value,
        decided_by,
        reason,
    )
    if row is None:
        raise OceanMastersStateError("That match is already decided, or doesn't exist.")
    return await get_match(conn, match_id)


async def correct_match(
    conn: asyncpg.Connection,
    match_id: UUID,
    *,
    winner_squad_id: UUID,
    decided_by: int,
    reason: str,
) -> OceanMastersMatch:
    """The 'result correction' / 'integration-failure override' path: fixes
    an ALREADY-decided match. Deliberately the mirror image of decide_match's
    WHERE clause — only ever touches a row that isn't still 'pending'."""
    row = await conn.fetchrow(
        """
        update ocean_masters_matches
        set winner_squad_id = $2, status = 'completed', decided_by = $3, decided_at = now(), decided_reason = $4
        where id = $1 and status != 'pending'
        returning id
        """,
        match_id,
        winner_squad_id,
        decided_by,
        reason,
    )
    if row is None:
        raise OceanMastersStateError("That match hasn't been decided yet — use set-result first.")
    return await get_match(conn, match_id)
