"""
AssetRepository — CRUD for the assets table.

Stores and retrieves ``AssetMetadata`` + ``AssetLocation`` from the
``assets`` table.  This is the master registry; all other tables reference
``asset_id`` from here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict

from data.raw_types import AssetLocation, AssetMetadata


class AssetRepository:
    """
    CRUD operations for the ``assets`` table.

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

    def upsert(self, metadata: AssetMetadata) -> None:
        """
        Insert or replace an asset registry record.

        Uses ``INSERT OR REPLACE`` so calling this on an existing asset_id
        updates all fields in place.

        Parameters
        ----------
        metadata:
            The ``AssetMetadata`` (with embedded ``AssetLocation``) to persist.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO assets (
                asset_id, asset_type, rated_kva, rated_voltage_kv,
                rated_lifespan_years, commissioned_year,
                latitude, longitude, substation_name, region, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.asset_id,
                metadata.asset_type,
                metadata.rated_kva,
                metadata.rated_voltage_kv,
                metadata.rated_lifespan_years,
                metadata.commissioned_year,
                metadata.location.latitude,
                metadata.location.longitude,
                metadata.location.substation_name,
                metadata.location.region,
                metadata.notes,
            ),
        )
        self._conn.commit()

    def delete(self, asset_id: str) -> None:
        """Delete the asset registry row for *asset_id*."""
        self._conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> AssetMetadata | None:
        """
        Return the ``AssetMetadata`` for *asset_id*, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_metadata(row)

    def list_all(self) -> list[AssetMetadata]:
        """Return all asset registry records, ordered by asset_id."""
        rows = self._conn.execute(
            "SELECT * FROM assets ORDER BY asset_id"
        ).fetchall()
        return [_row_to_metadata(r) for r in rows]

    def exists(self, asset_id: str) -> bool:
        """Return ``True`` if an asset with *asset_id* is registered."""
        row = self._conn.execute(
            "SELECT 1 FROM assets WHERE asset_id = ? LIMIT 1", (asset_id,)
        ).fetchone()
        return row is not None

    def count(self) -> int:
        """Return the total number of registered assets."""
        row = self._conn.execute("SELECT COUNT(*) FROM assets").fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_metadata(row: sqlite3.Row) -> AssetMetadata:
    return AssetMetadata(
        asset_id=row["asset_id"],
        asset_type=row["asset_type"],
        rated_kva=row["rated_kva"],
        rated_voltage_kv=row["rated_voltage_kv"],
        rated_lifespan_years=row["rated_lifespan_years"],
        commissioned_year=row["commissioned_year"],
        location=AssetLocation(
            latitude=row["latitude"],
            longitude=row["longitude"],
            substation_name=row["substation_name"],
            region=row["region"],
        ),
        notes=row["notes"],
    )
