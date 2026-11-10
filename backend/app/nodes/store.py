"""Paired sensor nodes; pairing keys are encrypted with the device's local key."""

import sqlite3
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken

from app.nodes.signing import display_key, normalize_key
from app.storage.cameras import CameraSecretError, CameraStore
from app.storage.database import Database
from app.storage.jobs import now

DEFAULT_PORT = 8780


def normalize_address(value: str) -> str:
    """Accept an IP address, 'falcon-node.local' or 'http://host:port'; return http://host:port."""
    text = value.strip()
    if not text or len(text) > 200 or any(ord(char) < 33 for char in text):
        raise ValueError("Enter the sensor node's address: its IP address or a name such as falcon-node.local")
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port or DEFAULT_PORT
    except ValueError:
        raise ValueError("Enter a valid sensor node address and port") from None
    if (
        parts.scheme != "http" or not parts.hostname or parts.username or parts.password
        or parts.path not in {"", "/"} or parts.query or parts.fragment
    ):
        raise ValueError("Enter only the node's host name or IP address (and port, if not 8780)")
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"http://{host}:{port}"


@dataclass(frozen=True)
class PairedNode:
    node_id: str
    name: str
    address: str
    audio_analysis: bool
    created_at: str
    updated_at: str
    # "node": the node's own camera. "ip": the saved IP camera (Sensors → IP camera)
    # supplies the picture while sound and sensors still come from this node.
    video_source: str = "node"

    @property
    def host(self) -> str:
        return urlsplit(self.address).hostname or ""


class NodeStore:
    def __init__(self, database: Database, cameras: CameraStore):
        self.database, self.cameras = database, cameras
        with database.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sensor_nodes (node_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                "address TEXT NOT NULL, key_ciphertext BLOB NOT NULL, audio_analysis INTEGER NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sensor_nodes)")}
            if "video_source" not in columns:
                connection.execute("ALTER TABLE sensor_nodes ADD COLUMN video_source TEXT NOT NULL DEFAULT 'node'")

    @staticmethod
    def _node(row: sqlite3.Row) -> PairedNode:
        return PairedNode(
            row["node_id"], row["name"], row["address"], bool(row["audio_analysis"]),
            row["created_at"], row["updated_at"], row["video_source"] or "node",
        )

    _COLUMNS = "node_id,name,address,audio_analysis,created_at,updated_at,video_source"

    def list(self) -> list[PairedNode]:
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT {self._COLUMNS} FROM sensor_nodes ORDER BY created_at"
            ).fetchall()
        return [self._node(row) for row in rows]

    def get(self, node_id: str) -> PairedNode:
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT {self._COLUMNS} FROM sensor_nodes WHERE node_id=?",
                (node_id,),
            ).fetchone()
        if row is None:
            raise KeyError(node_id)
        return self._node(row)

    def key(self, node_id: str) -> str:
        with self.database.connection() as connection:
            row = connection.execute("SELECT key_ciphertext FROM sensor_nodes WHERE node_id=?", (node_id,)).fetchone()
        if row is None:
            raise KeyError(node_id)
        try:
            return self.cameras.cipher().decrypt(row["key_ciphertext"]).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise CameraSecretError("The saved pairing key could not be unlocked. Pair the node again.") from exc

    def save(self, node_id: str, name: str, address: str, key: str, audio_analysis: bool = True) -> PairedNode:
        normalize_key(key)
        ciphertext = self.cameras.cipher(create=True).encrypt(display_key(key).encode())
        moment = now()
        with self.database.connection() as connection:
            previous = connection.execute("SELECT created_at FROM sensor_nodes WHERE node_id=?", (node_id,)).fetchone()
            source = connection.execute(
                "SELECT video_source FROM sensor_nodes WHERE node_id=?", (node_id,),
            ).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO sensor_nodes (node_id,name,address,key_ciphertext,audio_analysis,"
                "created_at,updated_at,video_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (node_id, name[:80], address, ciphertext, int(audio_analysis),
                 previous["created_at"] if previous else moment, moment,
                 source["video_source"] if source else "node"),
            )
        return self.get(node_id)

    def update(
        self, node_id: str, *, name: str | None = None, audio_analysis: bool | None = None,
        video_source: str | None = None,
    ) -> PairedNode:
        node = self.get(node_id)
        if video_source is not None and video_source not in {"node", "ip"}:
            raise ValueError("Video source must be the node camera or the IP camera")
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE sensor_nodes SET name=?, audio_analysis=?, video_source=?, updated_at=? WHERE node_id=?",
                (
                    (name.strip()[:80] or node.name) if name is not None else node.name,
                    int(node.audio_analysis if audio_analysis is None else audio_analysis),
                    video_source or node.video_source, now(), node_id,
                ),
            )
        return self.get(node_id)

    def delete(self, node_id: str) -> None:
        with self.database.connection() as connection:
            if connection.execute("DELETE FROM sensor_nodes WHERE node_id=?", (node_id,)).rowcount == 0:
                raise KeyError(node_id)
        with self.database.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
