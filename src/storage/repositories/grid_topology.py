"""
GridTopologyRepository — CRUD for the grid_topology table.

Stores and retrieves ``RawGridTopology`` (consequence-of-failure data)
per asset.  ``critical_facility_names`` is stored as a JSON array string.
"""

from __future__ import annotations

import sqlite3

from data.raw_types import RawGridTopology
from storage.serialisation import decode_str_list, encode_str_list


class GridTopologyRepository:
    """
    CRUD operations for the ``grid_topology`` table.

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

    def upsert(self, asset_id: str, topology: RawGridTopology) -> None:
        """
        Insert or replace the grid topology record for *asset_id*.

        Parameters
        ----------
        asset_id:
            The asset this topology record belongs to.
        topology:
            ``RawGridTopology`` describing consequence-of-failure data.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO grid_topology (
                asset_id, customers_served, critical_facility_count,
                critical_facility_names_json, peak_load_mw,
                downstream_asset_count, has_n1_redundancy
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                topology.customers_served,
                topology.critical_facility_count,
                encode_str_list(topology.critical_facility_names),
                topology.peak_load_mw,
                topology.downstream_asset_count,
                int(topology.has_n1_redundancy),
            ),
        )
        self._conn.commit()

    def delete(self, asset_id: str) -> None:
        """Delete the topology record for *asset_id*."""
        self._conn.execute(
            "DELETE FROM grid_topology WHERE asset_id = ?", (asset_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> RawGridTopology | None:
        """Return the ``RawGridTopology`` for *asset_id*, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM grid_topology WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_topology(row)

    def list_all(self) -> list[tuple[str, RawGridTopology]]:
        """Return all topology records as ``(asset_id, RawGridTopology)`` pairs."""
        rows = self._conn.execute(
            "SELECT * FROM grid_topology ORDER BY asset_id"
        ).fetchall()
        return [(r["asset_id"], _row_to_topology(r)) for r in rows]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_topology(row: sqlite3.Row) -> RawGridTopology:
    return RawGridTopology(
        customers_served=row["customers_served"],
        critical_facility_count=row["critical_facility_count"],
        critical_facility_names=decode_str_list(row["critical_facility_names_json"]),
        peak_load_mw=row["peak_load_mw"],
        downstream_asset_count=row["downstream_asset_count"],
        has_n1_redundancy=bool(row["has_n1_redundancy"]),
    )
