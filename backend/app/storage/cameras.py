"""One remembered RTSP profile; password ciphertext never leaves this module."""

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.schemas_live import CameraProfile, CameraProfileWrite, LiveStart
from app.storage.database import Database
from app.storage.jobs import now


class CameraSecretError(ValueError):
    """Safe error message suitable for the local UI."""


class CameraStore:
    def __init__(self, database: Database, key_path: Path):
        self.database = database
        self.key_path = key_path

    def _cipher(self, create: bool = False) -> Fernet:
        if not self.key_path.exists():
            if not create:
                raise CameraSecretError(
                    "The local camera key is missing. Enter and save the camera password again."
                )
            self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.key_path.parent.chmod(0o700)
            try:
                descriptor = os.open(
                    self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as file:
                    file.write(Fernet.generate_key())
                    file.flush()
                    os.fsync(file.fileno())
        # Never follow a replacement link or accept a key visible to other local users.
        information = self.key_path.lstat()
        if not stat.S_ISREG(information.st_mode) or information.st_uid != os.getuid():
            raise CameraSecretError("The local camera key is not a private regular file.")
        self.key_path.chmod(0o600)
        self.key_path.parent.chmod(0o700)
        try:
            return Fernet(self.key_path.read_bytes())
        except (ValueError, OSError) as exc:
            raise CameraSecretError("The local camera key could not be opened.") from exc

    def public(self) -> CameraProfile:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT name,url,username,password_ciphertext,audio_enabled,updated_at "
                "FROM camera_profiles WHERE profile_id='default'"
            ).fetchone()
        if row is None:
            return CameraProfile()
        return CameraProfile(
            saved=True,
            name=row["name"],
            url=row["url"],
            username=row["username"],
            has_password=bool(row["password_ciphertext"]),
            audio_enabled=bool(row["audio_enabled"]),
            updated_at=row["updated_at"],
        )

    def save(self, request: CameraProfileWrite) -> CameraProfile:
        url = request.url.get_secret_value()
        username = request.username.get_secret_value() if request.username else ""
        with self.database.connection() as connection:
            previous = connection.execute(
                "SELECT url,username,password_ciphertext FROM camera_profiles WHERE profile_id='default'"
            ).fetchone()
            ciphertext: bytes | None = None
            if request.password is not None:
                raw = request.password.get_secret_value()
                if raw:
                    ciphertext = self._cipher(create=True).encrypt(raw.encode())
            elif previous and previous["url"] == url and previous["username"] == username:
                ciphertext = previous["password_ciphertext"]
            connection.execute(
                "INSERT OR REPLACE INTO camera_profiles VALUES ('default', ?, ?, ?, ?, ?, ?)",
                (request.name, url, username, ciphertext, int(request.audio_enabled), now()),
            )
        return self.public()

    def resolve(self, request: LiveStart) -> LiveStart:
        if not request.use_saved_credentials:
            return request
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT url,username,password_ciphertext FROM camera_profiles WHERE profile_id='default'"
            ).fetchone()
        username = request.username.get_secret_value() if request.username else ""
        if row is None or row["url"] != request.url.get_secret_value():
            raise CameraSecretError("No saved credentials match this camera address.")
        if username and username != row["username"]:
            raise CameraSecretError("The camera username differs from the saved profile.")
        password: SecretStr | None = None
        if row["password_ciphertext"]:
            try:
                password = SecretStr(self._cipher().decrypt(row["password_ciphertext"]).decode())
            except (InvalidToken, UnicodeDecodeError) as exc:
                raise CameraSecretError(
                    "The saved camera password could not be unlocked. Enter it again."
                ) from exc
        return request.model_copy(
            update={
                "username": SecretStr(row["username"]) if row["username"] else None,
                "password": password,
            }
        )

    def delete(self) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM camera_profiles WHERE profile_id='default'")
            # TRUNCATE removes old encrypted pages from the WAL after a forgotten profile.
        with self.database.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
