import errno
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from PIL import Image

from app.media.probe import EXTENSIONS, probe
from app.schemas import Video, VideoCatalog
from app.services.review_names import resolve_review_names

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/upload", response_model=Video, status_code=201)
def upload_media(file: UploadFile, request: Request) -> Video:
    name = Path((file.filename or "upload").replace("\\", "/")).name
    name = re.sub(r"[^\w.() -]", "_", name)[:180]
    suffix = Path(name).suffix.lower()
    if suffix not in EXTENSIONS:
        raise HTTPException(
            415, "Upload a supported video, audio recording, or JPG, PNG or WebP image"
        )
    directory = request.app.state.library.directory
    directory.mkdir(parents=True, exist_ok=True)
    # Keep partial uploads outside the scanned catalog.
    temporary = request.app.state.config.data_dir / "temp" / f"upload-{uuid4().hex}{suffix}"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    limit = request.app.state.config.upload_limit_bytes
    size = 0
    try:
        with temporary.open("xb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if limit is not None and size > limit:
                    raise HTTPException(
                        413, f"Upload exceeds the configured limit of {limit:,} bytes."
                    )
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        try:
            media = probe(temporary)
        except (
            subprocess.SubprocessError,
            ValueError,
            KeyError,
            StopIteration,
            OSError,
            Image.DecompressionBombError,
        ) as exc:
            raise HTTPException(
                422, "The uploaded file could not be decoded as supported media"
            ) from exc
        library = request.app.state.library
        library.scan()
        if media.source_id in library.paths:
            return library.get(media.source_id)[1]
        target = directory / name
        # link() is atomic and refuses to overwrite any existing original, even in a race.
        while True:
            try:
                os.link(temporary, target)
                break
            except FileExistsError:
                target = directory / f"{Path(name).stem}-{uuid4().hex[:8]}{suffix}"
        return library.metadata(target)
    except OSError as exc:
        if exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise HTTPException(507, "Not enough disk space to save this upload.") from None
        raise HTTPException(500, "The uploaded file could not be saved locally.") from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            file.file.close()


@router.get("", response_model=VideoCatalog)
def list_videos(request: Request) -> VideoCatalog:
    return request.app.state.library.scan()


@router.get("/{source_id}", response_model=Video)
def get_video(source_id: str, request: Request) -> Video:
    try:
        return request.app.state.library.get(source_id)[1]
    except KeyError as exc:
        raise HTTPException(404, "Video not found") from exc


@router.get("/{source_id}/file")
def video_file(source_id: str, request: Request) -> FileResponse:
    try:
        path, video = request.app.state.library.get(source_id)
    except KeyError as exc:
        raise HTTPException(404, "Video not found") from exc
    return FileResponse(path, filename=video.filename, content_disposition_type="inline")


@router.get("/{source_id}/log", response_class=PlainTextResponse)
def video_log(source_id: str, request: Request) -> PlainTextResponse:
    get_video(source_id, request)
    events = resolve_review_names(request.app.state.events.read(source_id), request.app.state.taxa)
    return PlainTextResponse(
        "".join(e.model_dump_json() + "\n" for e in events), media_type="application/x-ndjson"
    )


@router.get("/{source_id}/log/download", response_class=PlainTextResponse)
def download_log(source_id: str, request: Request) -> PlainTextResponse:
    response = video_log(source_id, request)
    response.headers["Content-Disposition"] = f'attachment; filename="{source_id}.jsonl"'
    return response
