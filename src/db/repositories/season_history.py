from __future__ import annotations

from uuid import UUID

import asyncpg

from src.models.season import SeasonHistoryEntry


def _row_to_entry(row: asyncpg.Record) -> SeasonHistoryEntry:
    return SeasonHistoryEntry(
        season_id=row["season_id"],
        squad_id=row["squad_id"],
        squad_name=row["squad_name"],
        final_rank=row["final_rank"],
        final_season_xp=row["final_season_xp"],
        lifetime_xp_at_completion=row["lifetime_xp_at_completion"],
        qualified_top32=row["qualified_top32"],
        ocean_masters_final_standing=row["ocean_masters_final_standing"],
    )


async def snapshot_all_active_squads(conn: asyncpg.Connection, season_id: UUID) -> int:
    """Season Complete: persists the final Squad Leaderboard for every
    currently active squad — full standings, not only the top 32 (client
    confirmed 2026-09-23). `qualified_top32` is cross-referenced against
    season_qualifications for this season, if a Lock ever happened; if the
    season never locked, every squad is simply recorded as not-qualified.
    Returns how many squads were recorded."""
    rows = await conn.fetch(
        """
        insert into season_history (
            season_id, squad_id, final_rank, final_season_xp,
            lifetime_xp_at_completion, qualified_top32
        )
        select
            $1,
            s.id,
            row_number() over (
                order by coalesce(sx.season_xp, 0) desc, coalesce(sx.lifetime_xp, 0) desc, s.created_at asc
            ),
            coalesce(sx.season_xp, 0),
            coalesce(sx.lifetime_xp, 0),
            coalesce(sq.status = 'qualified' and sq.rank <= 32, false)
        from squads s
        left join squad_xp sx on sx.squad_id = s.id
        left join season_qualifications sq on sq.squad_id = s.id and sq.season_id = $1
        where s.status = 'active'
        returning squad_id
        """,
        season_id,
    )
    await refresh_ocean_masters_standings(conn, season_id)
    return len(rows)


async def refresh_ocean_masters_standings(conn: asyncpg.Connection, season_id: UUID) -> None:
    """Populates `ocean_masters_final_standing` for every squad that appears
    in this season's Ocean Masters bracket, if one ran. A squad's furthest
    round is exactly max(round) across the matches it appears in — it keeps
    appearing in every later round until eliminated (or wins the final).
    No-ops (leaves the column null) if no tournament exists for this season.
    Also re-run after an Ocean Masters result correction, so a season that
    was already completed shows the corrected standings."""
    await conn.execute(
        """
        with t as (
            select id from ocean_masters where season_id = $1
        ),
        participants as (
            select m.tournament_id, m.round, m.winner_squad_id, m.squad_a_id as squad_id
            from ocean_masters_matches m join t on t.id = m.tournament_id
            where m.squad_a_id is not null
            union all
            select m.tournament_id, m.round, m.winner_squad_id, m.squad_b_id as squad_id
            from ocean_masters_matches m join t on t.id = m.tournament_id
            where m.squad_b_id is not null
        ),
        furthest as (
            select squad_id, max(round) as last_round
            from participants
            group by squad_id
        ),
        standings as (
            select
                p.squad_id,
                case
                    when p.winner_squad_id = p.squad_id
                         and not exists (
                             select 1 from ocean_masters_matches nm
                             where nm.tournament_id = p.tournament_id and nm.round = p.round + 1
                         )
                        then 'Champion'
                    when p.winner_squad_id is not null and p.winner_squad_id != p.squad_id
                         and not exists (
                             select 1 from ocean_masters_matches nm
                             where nm.tournament_id = p.tournament_id and nm.round = p.round + 1
                         )
                        then 'Runner-up'
                    else 'Eliminated — Round ' || p.round
                end as standing
            from participants p
            join furthest f on f.squad_id = p.squad_id and f.last_round = p.round
        )
        update season_history sh
        set ocean_masters_final_standing = st.standing
        from standings st
        where sh.season_id = $1 and sh.squad_id = st.squad_id
        """,
        season_id,
    )


async def get_for_season(conn: asyncpg.Connection, season_id: UUID) -> list[SeasonHistoryEntry]:
    rows = await conn.fetch(
        """
        select sh.*, s.name as squad_name
        from season_history sh
        join squads s on s.id = sh.squad_id
        where sh.season_id = $1
        order by sh.final_rank
        """,
        season_id,
    )
    return [_row_to_entry(r) for r in rows]
