# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Keeps paired sensor nodes in view: status, readings, clock and live streams.

Every few seconds FALCON asks each node for its status and collects queued
weather readings. All connections go from FALCON to the node, so the node
never needs to reach this computer (which stays loopback-only), and the node
clock is corrected from this computer's clock when the node has no internet.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlunsplit

from pydantic import SecretStr, ValidationError

from app.nodes.client import NodeClient, NodeError
from app.nodes.signing import RTSP_USER, rtsp_password
from app.nodes.store import NodeStore, PairedNode, normalize_address
from app.schemas import AnalysisSettings
from app.schemas_live import LiveStart
from app.schemas_sensors import SensorReadingWrite
from app.services.clock_check import ClockRate
from app.storage.sensors import SensorReplayConflict

log = logging.getLogger("falcon.nodes")
ACTIVE = {"connecting", "live", "reconnecting"}


@dataclass
class Snapshot:
    status: dict[str, Any] | None = None
    error: str | None = None
    checked_at: str | None = None
    last_seen: str | None = None
    readings_collected: int = 0


class NodeManager:
    def __init__(
        self, store: NodeStore, ingest: Callable[[SensorReadingWrite], object] | None,
        live_state: Callable[[], Any] | None = None, *, interval: float = 5.0,
        client_factory: Callable[[str, str], NodeClient] = NodeClient,
    ):
        self.store, self.ingest, self.live_state = store, ingest, live_state
        self.interval, self.client_factory = interval, client_factory
        self._snapshots: dict[str, Snapshot] = {}
        self._clock_rates: dict[str, ClockRate] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.observing: str | None = None

    # --- background polling ---
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="falcon-nodes")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                nodes = self.store.list()
            except Exception:
                log.exception("Paired sensor nodes could not be read")
                nodes = []
            for node in nodes:
                if self._stop.is_set():
                    break
                try:
                    self.refresh(node)
                except Exception:
                    log.exception("Sensor node %s could not be refreshed", node.node_id)
            self._stop.wait(max(0.5, self.interval - (time.monotonic() - started)))

    def client(self, node_id: str) -> NodeClient:
        node = self.store.get(node_id)
        return self.client_factory(node.address, self.store.key(node_id))

    def _snapshot(self, node_id: str) -> Snapshot:
        with self._lock:
            return self._snapshots.setdefault(node_id, Snapshot())

    def restart_observed_stream(self) -> None:
        """Restart the observed node's sound (used when its sound track goes silent).

        A node with the microphone on its own path restarts only the microphone, so the
        picture is not touched; an older node restarts its single stream."""
        if self.observing:
            with self._lock:
                status = self._snapshots.get(self.observing, Snapshot()).status or {}
            separate = bool((status.get("stream") or {}).get("audio_path"))
            self.client(self.observing).stream("restart_microphone" if separate else "restart")

    def restart_observed_camera(self) -> None:
        """Restart only the observed node's camera (picture self-heal)."""
        if self.observing:
            self.client(self.observing).stream("restart_camera")

    def temperature(self) -> float | None:
        """The observed node's CPU temperature from its last status, for the night log."""
        node_id = self.observing
        if node_id is None:
            return None
        with self._lock:
            status = self._snapshots.get(node_id, Snapshot()).status or {}
        value = (status.get("system") or {}).get("cpu_temperature_c")
        return float(value) if isinstance(value, (int, float)) else None

    def night_mode(self) -> str | None:
        """The night-picture mode FALCON applies for the observed node, if that node
        passes its webcam's frames through (it then leaves the night picture to FALCON)."""
        node_id = self.observing
        if node_id is None:
            return None
        with self._lock:
            status = self._snapshots.get(node_id, Snapshot()).status or {}
        night = (status.get("stream") or {}).get("night") or {}
        mode = night.get("mode")
        if night.get("applied_by") == "falcon" and mode in {"auto", "colour", "mono"}:
            return str(mode)
        return None

    def _record(self, node_id: str, status: dict[str, Any] | None, error: str | None) -> None:
        moment = datetime.now(UTC).isoformat()
        with self._lock:
            snapshot = self._snapshot(node_id)
            snapshot.checked_at, snapshot.error = moment, error
            if status is not None:
                # This computer's clock speed against the node's uptime (see clock_check).
                uptime = (status.get("system") or {}).get("uptime_seconds")
                if isinstance(uptime, (int, float)) and not isinstance(uptime, bool):
                    rate = self._clock_rates.setdefault(node_id, ClockRate())
                    rate.observe(float(uptime))
                    status = {**status, "falcon_clock": rate.report()}
                snapshot.status, snapshot.last_seen = status, moment

    def refresh(self, node: PairedNode) -> dict[str, Any] | None:
        try:
            client = self.client(node.node_id)
            status = client.status()
        except (NodeError, ValueError) as exc:
            self._record(node.node_id, None, str(exc))
            return None
        self._record(node.node_id, status, None)
        if status.get("readings_queued"):
            try:
                self.collect(node.node_id, client)
            except NodeError as exc:
                log.warning("Readings from %s could not be collected: %s", node.node_id, exc)
        return status

    def collect(self, node_id: str, client: NodeClient, *, batches: int = 10) -> int:
        """Pull queued readings, store them, then acknowledge so the node can delete them."""
        if self.ingest is None:
            return 0
        acknowledged: list[str] = []
        stored = 0
        for _ in range(batches):
            result = client.pull(acknowledged, 200)
            acknowledged = []
            readings = result.get("readings") or []
            for raw in readings:
                reading_id = raw.get("reading_id") if isinstance(raw, dict) else None
                try:
                    self.ingest(SensorReadingWrite.model_validate(raw))
                    stored += 1
                except (ValidationError, SensorReplayConflict, ValueError) as exc:
                    # Retrying cannot fix an invalid or conflicting reading. Drop it from the node's queue.
                    log.warning("Reading %s from %s was rejected (%s)", reading_id, node_id, type(exc).__name__)
                if isinstance(reading_id, str):
                    acknowledged.append(reading_id)
            if not readings:
                break
        if acknowledged:
            client.pull(acknowledged, 1)
        with self._lock:
            self._snapshot(node_id).readings_collected += stored
        return stored

    # --- views ---
    def summary(self, node: PairedNode) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshots.get(node.node_id, Snapshot())
            status = snapshot.status
        live = self.live_state() if self.live_state else None
        observing = bool(
            self.observing == node.node_id and live is not None and live.status in ACTIVE | {"stopping"}
        )
        return {
            "node_id": node.node_id, "name": node.name, "address": node.address,
            "audio_analysis": node.audio_analysis, "created_at": node.created_at, "updated_at": node.updated_at,
            "video_source": node.video_source,
            "online": snapshot.error is None and status is not None,
            "checked_at": snapshot.checked_at, "last_seen": snapshot.last_seen, "error": snapshot.error,
            "readings_collected": snapshot.readings_collected, "observing": observing, "status": status,
        }

    def summaries(self) -> list[dict[str, Any]]:
        return [self.summary(node) for node in self.store.list()]

    def preferred_sensor_id(self) -> str | None:
        """The node whose weather readings belong to current detections."""
        live = self.live_state() if self.live_state else None
        if self.observing and live is not None and live.status in ACTIVE:
            return self.observing
        nodes = self.store.list()
        return nodes[0].node_id if len(nodes) == 1 else None

    # --- actions ---
    def pair(self, address: str, key: str, name: str | None = None) -> dict[str, Any]:
        address = normalize_address(address)
        status = self.client_factory(address, key).status()
        node = self.store.save(status["node_id"], (name or status.get("name") or status["node_id"]).strip(), address, key)
        self._record(node.node_id, status, None)
        return self.summary(node)

    def control(self, node_id: str, action: Callable[[NodeClient], dict[str, Any]]) -> dict[str, Any]:
        client = self.client(node_id)
        try:
            status = action(client)
        except NodeError as exc:
            if exc.status is None:
                self._record(node_id, None, str(exc))
            raise
        if isinstance(status, dict) and status.get("software") == "falcon-node":
            self._record(node_id, status, None)
        return self.summary(self.store.get(node_id))

    def ensure_streaming(self, node_id: str, timeout: float = 20) -> dict[str, Any]:
        client = self.client(node_id)
        status = client.status()
        if status["stream"]["state"] == "off":
            status = client.stream("start")
        deadline = time.monotonic() + timeout
        while status["stream"]["state"] != "streaming" and time.monotonic() < deadline:
            if status["stream"]["state"] == "no sources":
                raise NodeError("This node has no camera or microphone switched on to stream.")
            time.sleep(1)
            status = client.status()
        self._record(node_id, status, None)
        if status["stream"]["state"] != "streaming":
            raise NodeError(status["stream"].get("error") or "The node's stream did not start. Check its camera and microphone.")
        return status

    def live_request(self, node_id: str, config: AnalysisSettings, status: dict[str, Any] | None = None) -> LiveStart:
        node = self.store.get(node_id)
        key = self.store.key(node_id)
        status = status or self._snapshot(node_id).status or self.client(node_id).status()
        stream = status["stream"]
        host = f"[{node.host}]" if ":" in node.host else node.host
        url = urlunsplit(("rtsp", f"{host}:{int(stream['rtsp_port'])}", "/" + str(stream["rtsp_path"]), "", ""))
        node_request = LiveStart(
            name=node.name, url=SecretStr(url),
            username=SecretStr(RTSP_USER), password=SecretStr(rtsp_password(key)),
            config=config.model_copy(update={"audio_enabled": node.audio_analysis and bool(stream.get("audio"))}),
            use_saved_credentials=False, save_profile=False,
        )
        # A node with the microphone on its own path (14 Nov 2026): sound is read from
        # there, so the picture never holds it back. Older nodes keep one path.
        sound_request = node_request
        if stream.get("audio_path"):
            sound_url = urlunsplit(("rtsp", f"{host}:{int(stream['rtsp_port'])}", "/" + str(stream["audio_path"]), "", ""))
            sound_request = node_request.model_copy(update={"url": SecretStr(sound_url)})
            node_request = node_request.model_copy(update={"audio_url": SecretStr(sound_request.connection_url())})
        if node.video_source != "ip":
            return node_request
        # The saved IP camera supplies the picture; this node still supplies the sound.
        profile = self.store.cameras.public()
        if not profile.saved:
            raise NodeError("Video source is the IP camera, but no IP camera is saved under Sensors.")
        camera = self.store.cameras.resolve(LiveStart(
            name=node.name, url=SecretStr(profile.url),
            username=SecretStr(profile.username) if profile.username else None,
            config=node_request.config, use_saved_credentials=True, save_profile=False,
        ))
        return camera.model_copy(update={"audio_url": SecretStr(sound_request.connection_url())})

    def forget(self, node_id: str) -> None:
        self.store.delete(node_id)
        with self._lock:
            self._snapshots.pop(node_id, None)
        if self.observing == node_id:
            self.observing = None
