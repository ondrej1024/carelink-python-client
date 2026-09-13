"""Durable storage for responses returned by the CareLink display API."""

import hashlib
import json
import logging as log
import os
import tempfile
from datetime import datetime, timezone

import duckdb


class CareLinkStorage:
    """Store complete API responses and their time-series/history entries."""

    def __init__(self, database_file):
        self.database_file = os.path.abspath(database_file)
        parent = os.path.dirname(self.database_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._create_schema()

    def _connect(self):
        return duckdb.connect(self.database_file)

    def _create_schema(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS carelink_snapshots (
                    device_id VARCHAR NOT NULL,
                    source_updated_at_ms BIGINT NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL,
                    payload JSON NOT NULL,
                    PRIMARY KEY (device_id, source_updated_at_ms)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS carelink_history (
                    device_id VARCHAR NOT NULL,
                    record_type VARCHAR NOT NULL,
                    event_time VARCHAR,
                    record_hash VARCHAR NOT NULL,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    payload JSON NOT NULL,
                    PRIMARY KEY (device_id, record_type, record_hash)
                )
            """)

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _device_id(patient_data):
        return (patient_data.get("medicalDeviceInformation") or {}).get(
            "deviceSerialNumber"
        ) or patient_data.get("conduitSerialNumber") or "unknown"

    @staticmethod
    def _event_time(value):
        return value.get("timestamp") or value.get("dateTime") or value.get("datetime")

    def _history_records(self, patient_data):
        for name in ("sgs", "markers", "limits"):
            for value in patient_data.get(name) or []:
                if isinstance(value, dict):
                    yield name, value

        notifications = patient_data.get("notificationHistory") or {}
        if isinstance(notifications, dict):
            for name, values in notifications.items():
                for value in values or []:
                    if isinstance(value, dict):
                        yield "notification_" + name, value

        # These are current-state objects rather than arrays, but retaining them
        # lets the database capture records that may disappear from a later 24h window.
        for name in ("lastSG", "lastAlarm", "activeInsulin", "basal"):
            value = patient_data.get(name)
            if isinstance(value, dict):
                yield name, value

    def save(self, data):
        """Persist one complete response and every history item it contains.

        Repeated polls are idempotent: snapshots are keyed by the device update
        time, and history entries by a stable hash of their complete payload.
        """
        if not isinstance(data, dict) or not isinstance(data.get("patientData"), dict):
            raise ValueError("CareLink response has no patientData object")

        patient_data = data["patientData"]
        device_id = self._device_id(patient_data)
        # This is supplied by CareLink and changes when new pump data is available.
        source_updated_at_ms = patient_data.get("lastConduitUpdateServerDateTime")
        if source_updated_at_ms is None:
            source_updated_at_ms = patient_data.get("currentServerTime")
        if source_updated_at_ms is None:
            source_updated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        source_updated_at_ms = int(source_updated_at_ms)

        now = datetime.now(timezone.utc)
        payload = self._json(data)
        history = []
        for record_type, value in self._history_records(patient_data):
            record_payload = self._json(value)
            history.append((
                device_id,
                record_type,
                self._event_time(value),
                hashlib.sha256(record_payload.encode("utf-8")).hexdigest(),
                now,
                now,
                record_payload,
            ))

        with self._connect() as con:
            con.execute("""
                INSERT INTO carelink_snapshots
                    (device_id, source_updated_at_ms, fetched_at, payload)
                VALUES (?, ?, ?, ?::JSON)
                ON CONFLICT (device_id, source_updated_at_ms) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    payload = excluded.payload
            """, [device_id, source_updated_at_ms, now, payload])
            if history:
                con.executemany("""
                    INSERT INTO carelink_history
                        (device_id, record_type, event_time, record_hash,
                         first_seen_at, last_seen_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?::JSON)
                    ON CONFLICT (device_id, record_type, record_hash) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                """, history)
        log.info("Saved CareLink response to %s (%d history records)",
                 self.database_file, len(history))

    @staticmethod
    def _sql_string(value):
        """Quote a string for SQL statements which cannot use parameters."""
        return "'" + value.replace("'", "''") + "'"

    @staticmethod
    def _apply_file_metadata(filename, existing):
        if existing is not None:
            os.chmod(filename, existing.st_mode & 0o777)
            os.chown(filename, existing.st_uid, existing.st_gid)

    def _create_replica_catalog(self, filename, data_file):
        """Create the stable DuckDB catalog whose views read live Parquet data."""
        quoted_data_file = self._sql_string(data_file)
        with duckdb.connect(filename) as con:
            con.execute("""
                CREATE TABLE carelink_replica_metadata (
                    format_version INTEGER NOT NULL,
                    data_file VARCHAR NOT NULL
                )
            """)
            con.execute(
                "INSERT INTO carelink_replica_metadata VALUES (1, ?)",
                [data_file],
            )
            con.execute("""
                CREATE VIEW carelink_snapshots AS
                SELECT device_id, source_updated_at_ms, fetched_at,
                       payload::JSON AS payload
                FROM read_parquet(%s)
                WHERE dataset = 'snapshots'
            """ % quoted_data_file)
            con.execute("""
                CREATE VIEW carelink_history AS
                SELECT device_id, record_type, event_time, record_hash,
                       first_seen_at, last_seen_at, payload::JSON AS payload
                FROM read_parquet(%s)
                WHERE dataset = 'history'
            """ % quoted_data_file)

    def publish_replica(self, replica_file):
        """Publish data for Grafana without replacing its open DuckDB catalog.

        Grafana keeps its DuckDB connection open, so replacing the database file
        leaves it reading the old inode forever. The database at ``replica_file``
        is therefore a stable catalog containing views. Each publication instead
        atomically replaces one Parquet file, which DuckDB opens for every query.
        """
        replica_file = os.path.abspath(replica_file)
        replica_dir = os.path.dirname(replica_file)
        if not os.path.isdir(replica_dir):
            raise ValueError("replica directory does not exist: %s" % replica_dir)
        data_file = replica_file + ".parquet"

        try:
            catalog_metadata = os.stat(replica_file)
        except FileNotFoundError:
            catalog_metadata = None
        try:
            data_metadata = os.stat(data_file)
        except FileNotFoundError:
            data_metadata = catalog_metadata

        # Export both logical tables into one file so every Grafana query sees a
        # self-consistent generation. COPY requires a path rather than a bound
        # parameter, hence the narrowly scoped SQL string quoting helper.
        fd, temporary_data = tempfile.mkstemp(
            prefix=".%s." % os.path.basename(data_file),
            suffix=".tmp",
            dir=replica_dir,
        )
        os.close(fd)
        os.unlink(temporary_data)
        try:
            with duckdb.connect(self.database_file, read_only=True) as con:
                con.execute("""
                    COPY (
                        SELECT 'snapshots' AS dataset, device_id,
                               source_updated_at_ms, fetched_at,
                               NULL::VARCHAR AS record_type,
                               NULL::VARCHAR AS event_time,
                               NULL::VARCHAR AS record_hash,
                               NULL::TIMESTAMPTZ AS first_seen_at,
                               NULL::TIMESTAMPTZ AS last_seen_at,
                               payload::VARCHAR AS payload
                        FROM carelink_snapshots
                        UNION ALL
                        SELECT 'history', device_id, NULL::BIGINT,
                               NULL::TIMESTAMPTZ, record_type, event_time,
                               record_hash, first_seen_at, last_seen_at,
                               payload::VARCHAR
                        FROM carelink_history
                    ) TO %s (FORMAT PARQUET, COMPRESSION ZSTD)
                """ % self._sql_string(temporary_data))
            with open(temporary_data, "rb") as published:
                os.fsync(published.fileno())
            self._apply_file_metadata(temporary_data, data_metadata)
            os.replace(temporary_data, data_file)
        except Exception:
            try:
                os.unlink(temporary_data)
            except FileNotFoundError:
                pass
            raise

        # Migrate the former full-copy replica once. Thereafter this catalog is
        # deliberately never replaced, so Grafana's long-lived handle stays valid.
        catalog_is_current = False
        if catalog_metadata is not None:
            try:
                with duckdb.connect(replica_file, read_only=True) as con:
                    row = con.execute("""
                        SELECT format_version, data_file
                        FROM carelink_replica_metadata
                    """).fetchone()
                    catalog_is_current = row == (1, data_file)
            except duckdb.Error:
                pass

        if not catalog_is_current:
            fd, temporary_catalog = tempfile.mkstemp(
                prefix=".%s." % os.path.basename(replica_file),
                suffix=".tmp",
                dir=replica_dir,
            )
            os.close(fd)
            os.unlink(temporary_catalog)
            try:
                self._create_replica_catalog(temporary_catalog, data_file)
                with open(temporary_catalog, "rb") as published:
                    os.fsync(published.fileno())
                self._apply_file_metadata(temporary_catalog, catalog_metadata)
                os.replace(temporary_catalog, replica_file)
                log.warning(
                    "Migrated Grafana replica catalog; restart Grafana once to "
                    "release the former database file"
                )
            except Exception:
                try:
                    os.unlink(temporary_catalog)
                except FileNotFoundError:
                    pass
                raise

        log.info("Published Grafana replica data to %s", data_file)
