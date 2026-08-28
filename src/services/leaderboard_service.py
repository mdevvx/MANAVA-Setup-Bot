from __future__ import annotations

from uuid import UUID

import asyncpg

from src.db.repositories import memberships as memberships_repo
from src.db.repositories import squad_xp as squad_xp_repo
from src.models.xp import GlobalLeaderboardEntry, SquadMemberLeaderboardEntry


async def get_global_squad_leaderboard(conn: asyncpg.Connection, limit: int = 100) -> list[GlobalLeaderboardEntry]:
    rows = await squad_xp_repo.get_global_leaderboard(conn, limit)
    return [
        GlobalLeaderboardEntry(
            rank=row["rank"],
            squad_id=row["squad_id"],
            squad_name=row["squad_name"],
            season_xp=row["season_xp"],
            lifetime_xp=row["lifetime_xp"],
        )
        for row in rows
    ]


async def get_squad_member_leaderboard(conn: asyncpg.Connection, squad_id: UUID) -> list[SquadMemberLeaderboardEntry]:
    rows = await memberships_repo.get_member_leaderboard(conn, squad_id)
    return [
        SquadMemberLeaderboardEntry(
            rank=row["rank"],
            discord_user_id=row["discord_user_id"],
            squad_role=row["squad_role"],
            personal_lifetime_xp=row["personal_lifetime_xp"],
            personal_season_xp=row["personal_season_xp"],
            contributed_xp=row["contributed_xp"],
        )
        for row in rows
    ]
