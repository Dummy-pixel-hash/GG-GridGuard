"""
RiskResultRepository — CRUD for the risk_results table.

Stores timestamped ``RiskResult`` snapshots.  Multiple results per asset
are retained (one per scoring run) to enable score-trend analysis.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from risk_engine.models import ComponentScores, RiskLevel, RiskResult


class RiskResultRepository:
    """
    CRUD operations for the ``risk_results`` table.

    Parameters
    ----------
    conn:
        Open SQLite connection from ``storage.get_connection()``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def insert(self, result: RiskResult, scored_at: datetime | None = None) -> int:
        """
        Append a new risk result row and return its auto-generated ``id``.

        Parameters
        ----------
        result:
            The ``RiskResult`` to persist.
        scored_at:
            Timestamp for this result; defaults to the current UTC time if
            ``None``.

        Returns
        -------
        int
            The ``rowid`` of the newly inserted row.
        """
        if scored_at is None:
            scored_at = datetime.now(tz=timezone.utc)
        ts = scored_at.isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO risk_results (
                asset_id, scored_at, overall_risk, risk_level,
                component_sensor, component_weather, component_history,
                component_degradation, component_grid_impact, dominant_factor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.asset_id,
                ts,
                result.overall_risk,
                result.risk_level.value,
                result.components.sensor_health,
                result.components.weather_risk,
                result.components.historical_failure,
                result.components.asset_degradation,
                result.components.grid_impact,
                result.dominant_factor,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def delete_for_asset(self, asset_id: str) -> int:
        """
        Delete all risk result rows for *asset_id*.

        Returns the number of rows deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM risk_results WHERE asset_id = ?", (asset_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_latest(self, asset_id: str) -> RiskResult | None:
        """
        Return the most recent ``RiskResult`` for *asset_id*, or ``None``.

        "Most recent" is determined by the ``scored_at`` timestamp.
        """
        row = self._conn.execute(
            """
            SELECT * FROM risk_results
            WHERE asset_id = ?
            ORDER BY scored_at DESC
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_result(row)

    def list_for_asset(self, asset_id: str) -> list[RiskResult]:
        """
        Return all risk results for *asset_id*, ordered oldest → newest.
        """
        rows = self._conn.execute(
            """
            SELECT * FROM risk_results
            WHERE asset_id = ?
            ORDER BY scored_at ASC
            """,
            (asset_id,),
        ).fetchall()
        return [_row_to_result(r) for r in rows]

    def list_latest_all(self) -> list[RiskResult]:
        """
        Return the most recent result for every asset in the table.

        Useful for a full-fleet risk snapshot.  Results are ordered by
        ``overall_risk`` descending (highest risk first).
        """
        rows = self._conn.execute(
            """
            SELECT r.*
            FROM risk_results r
            INNER JOIN (
                SELECT asset_id, MAX(scored_at) AS max_ts
                FROM risk_results
                GROUP BY asset_id
            ) latest ON r.asset_id = latest.asset_id
                     AND r.scored_at = latest.max_ts
            ORDER BY r.overall_risk DESC
            """
        ).fetchall()
        return [_row_to_result(r) for r in rows]

    def count(self) -> int:
        """Return the total number of risk result rows."""
        row = self._conn.execute("SELECT COUNT(*) FROM risk_results").fetchone()
        return int(row[0])

    def count_for_asset(self, asset_id: str) -> int:
        """Return the number of risk result rows for *asset_id*."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM risk_results WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_result(row: sqlite3.Row) -> RiskResult:
    return RiskResult(
        asset_id=row["asset_id"],
        overall_risk=row["overall_risk"],
        risk_level=RiskLevel(row["risk_level"]),
        components=ComponentScores(
            sensor_health=row["component_sensor"],
            weather_risk=row["component_weather"],
            historical_failure=row["component_history"],
            asset_degradation=row["component_degradation"],
            grid_impact=row["component_grid_impact"],
        ),
        dominant_factor=row["dominant_factor"],
    )
