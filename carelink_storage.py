"""Durable storage for responses returned by the CareLink display API."""

import hashlib
import json
import logging as log
import os
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
