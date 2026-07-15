import os
import re
import requests as http_requests
import shutil
import threading
import time
import uuid
import zipfile
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .downloader import SpotifyDownloader, get_youtube_health

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = PROJECT_ROOT / "web_downloads"
CACHE_ROOT = Path(os.getenv("SPOTIFYDL_CACHE_DIR", str(PROJECT_ROOT / "web_cache"))).expanduser().resolve()
ASSETS_DIR = PROJECT_ROOT / "assets"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

MAX_LINKS = int(os.getenv("SPOTIFYDL_WEB_MAX_LINKS", "10"))
TASK_TTL_SECONDS = int(os.getenv("SPOTIFYDL_WEB_TASK_TTL_SECONDS", str(24 * 60 * 60)))
MAX_WORKERS = int(os.getenv("SPOTIFYDL_WEB_WORKERS", "2"))
WEB_PASSWORD = os.getenv("SPOTIFYDL_WEB_PASSWORD", "")
SOURCE = os.getenv("SPOTIFYDL_WEB_SOURCE", "youtubemusic")
FORMAT = os.getenv("SPOTIFYDL_WEB_FORMAT", "mp3")
QUALITY = os.getenv("SPOTIFYDL_WEB_QUALITY", "320k")
COOKIES_FILE = os.getenv("SPOTIFYDL_COOKIES_FILE")
POT_PROVIDER_URL = os.getenv("SPOTIFYDL_POT_PROVIDER_URL", "").rstrip("/")
CACHE_ENABLED = os.getenv("SPOTIFYDL_CACHE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
CACHE_TTL_SECONDS = int(os.getenv("SPOTIFYDL_CACHE_TTL_SECONDS", str(30 * 24 * 60 * 60)))
RATE_LIMIT_TRACKS = int(os.getenv("SPOTIFYDL_WEB_RATE_LIMIT_TRACKS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("SPOTIFYDL_WEB_RATE_LIMIT_WINDOW_SECONDS", "3600"))

DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
if CACHE_ENABLED:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="SpotifyDownloader Web")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
tasks: Dict[str, Dict] = {}
task_lock = threading.Lock()
cache_locks_guard = threading.Lock()
cache_locks: Dict[str, threading.Lock] = {}
rate_limit_lock = threading.Lock()
rate_limit_entries = defaultdict(deque)


class TaskCreateRequest(BaseModel):
    urls: List[str]


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _require_password(x_access_password: Optional[str] = None, access_password: Optional[str] = None):
    supplied = x_access_password or access_password
    if WEB_PASSWORD and supplied != WEB_PASSWORD:
        raise HTTPException(status_code=401, detail="访问密码错误")


def _clean_url(url: str) -> str:
    return url.strip()


def _extract_track_id(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "open.spotify.com":
        return None
    match = re.fullmatch(r"/track/([A-Za-z0-9]{22})/?", parsed.path)
    return match.group(1) if match else None


def _validate_urls(urls: List[str]) -> List[str]:
    cleaned = [_clean_url(url) for url in urls if _clean_url(url)]
    if not cleaned:
        raise HTTPException(status_code=400, detail="至少提供一个 Spotify track 链接")
    if len(cleaned) > MAX_LINKS:
        raise HTTPException(status_code=400, detail=f"一次最多支持 {MAX_LINKS} 个链接")
    invalid = [url for url in cleaned if not _extract_track_id(url)]
    if invalid:
        raise HTTPException(status_code=400, detail="链接格式有误，请输入 Spotify track 链接")
    return cleaned


def _check_rate_limit(client_key: str, track_count: int):
    if RATE_LIMIT_TRACKS <= 0:
        return
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with rate_limit_lock:
        for key, old_entries in list(rate_limit_entries.items()):
            while old_entries and old_entries[0] <= cutoff:
                old_entries.popleft()
            if not old_entries:
                rate_limit_entries.pop(key, None)
        entries = rate_limit_entries[client_key]
        if len(entries) + track_count > RATE_LIMIT_TRACKS:
            retry_after = max(1, int(entries[0] + RATE_LIMIT_WINDOW_SECONDS - now)) if entries else RATE_LIMIT_WINDOW_SECONDS
            raise HTTPException(
                status_code=429,
                detail=f"下载请求过于频繁，请约 {max(1, retry_after // 60 + 1)} 分钟后重试",
                headers={"Retry-After": str(retry_after)},
            )
        entries.extend([now] * track_count)


def _get_cache_lock(cache_key: str) -> threading.Lock:
    with cache_locks_guard:
        return cache_locks.setdefault(cache_key, threading.Lock())


def _cache_key(track_id: str) -> str:
    safe_quality = re.sub(r"[^A-Za-z0-9_-]", "_", QUALITY)
    safe_format = re.sub(r"[^A-Za-z0-9_-]", "_", FORMAT)
    return f"{track_id}-{safe_format}-{safe_quality}"


def _get_cached_file(cache_key: str) -> Optional[Path]:
    if not CACHE_ENABLED:
        return None
    cache_dir = CACHE_ROOT / cache_key
    if not cache_dir.is_dir():
        return None
    files = [path for path in cache_dir.iterdir() if path.is_file() and path.stat().st_size > 0]
    if not files:
        return None
    cached_file = max(files, key=lambda path: path.stat().st_mtime)
    if CACHE_TTL_SECONDS > 0 and time.time() - cached_file.stat().st_mtime > CACHE_TTL_SECONDS:
        shutil.rmtree(cache_dir, ignore_errors=True)
        return None
    return cached_file


def _restore_cached_file(cached_file: Path, task_dir: Path) -> str:
    destination = task_dir / cached_file.name
    shutil.copy2(cached_file, destination)
    return destination.name


def _store_cached_file(cache_key: str, source: Path):
    if not CACHE_ENABLED:
        return
    cache_dir = CACHE_ROOT / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    for existing in cache_dir.iterdir():
        if existing.is_file() and existing.name != source.name:
            existing.unlink(missing_ok=True)
    temporary = cache_dir / f".{source.name}.{uuid.uuid4().hex}.tmp"
    shutil.copy2(source, temporary)
    os.replace(temporary, cache_dir / source.name)


def _cleanup_cache():
    if not CACHE_ENABLED or CACHE_TTL_SECONDS <= 0 or not CACHE_ROOT.exists():
        return
    cutoff = time.time() - CACHE_TTL_SECONDS
    for cache_dir in CACHE_ROOT.iterdir():
        if not cache_dir.is_dir():
            continue
        files = [path for path in cache_dir.iterdir() if path.is_file()]
        if not files or max(path.stat().st_mtime for path in files) < cutoff:
            shutil.rmtree(cache_dir, ignore_errors=True)


def _create_task(urls: List[str]) -> Dict:
    task_id = uuid.uuid4().hex
    task_dir = DOWNLOAD_ROOT / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    task = {
        "id": task_id,
        "status": "queued",
        "created_at": time.time(),
        "updated_at": time.time(),
        "total": len(urls),
        "done": 0,
        "failed": 0,
        "zip_file": None,
        "items": [
            {
                "url": url,
                "status": "queued",
                "file": None,
                "error": None,
            }
            for url in urls
        ],
    }
    with task_lock:
        tasks[task_id] = task
    executor.submit(_run_task, task_id, task_dir)
    return task


def _snapshot_files(task_dir: Path) -> Dict[str, float]:
    return {
        path.name: path.stat().st_mtime
        for path in task_dir.iterdir()
        if path.is_file() and path.name != "result.zip"
    }


def _find_downloaded_file(task_dir: Path, before: Dict[str, float]) -> Optional[str]:
    after = _snapshot_files(task_dir)
    new_files = [name for name in after if name not in before]
    if new_files:
        return max(new_files, key=lambda name: after[name])
    changed_files = [name for name, mtime in after.items() if before.get(name) != mtime]
    if changed_files:
        return max(changed_files, key=lambda name: after[name])
    if after:
        return max(after, key=lambda name: after[name])
    return None


def _set_task_fields(task_id: str, **fields):
    with task_lock:
        task = tasks.get(task_id)
        if task:
            task.update(fields)
            task["updated_at"] = time.time()


def _set_item_fields(task_id: str, index: int, **fields):
    with task_lock:
        task = tasks.get(task_id)
        if task:
            task["items"][index].update(fields)
            task["updated_at"] = time.time()


def _refresh_counts(task_id: str):
    with task_lock:
        task = tasks.get(task_id)
        if task:
            task["done"] = sum(1 for item in task["items"] if item["status"] == "done")
            task["failed"] = sum(1 for item in task["items"] if item["status"] == "failed")
            task["updated_at"] = time.time()


def _build_zip(task_id: str, task_dir: Path) -> Optional[str]:
    files = [
        path
        for path in task_dir.iterdir()
        if path.is_file() and path.name != "result.zip"
    ]
    if not files:
        return None
    zip_path = task_dir / "result.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    _set_task_fields(task_id, zip_file="result.zip")
    return "result.zip"


def _run_task(task_id: str, task_dir: Path):
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        _set_task_fields(task_id, status="failed")
        with task_lock:
            task = tasks.get(task_id)
            if task:
                for item in task["items"]:
                    item["status"] = "failed"
                    item["error"] = "服务器缺少 SPOTIFY_CLIENT_ID 或 SPOTIFY_CLIENT_SECRET"
                task["failed"] = task["total"]
                task["updated_at"] = time.time()
        return

    _set_task_fields(task_id, status="running")
    downloader = SpotifyDownloader(client_id, client_secret)

    with task_lock:
        urls = [item["url"] for item in tasks[task_id]["items"]]

    for index, url in enumerate(urls):
        _set_item_fields(task_id, index, status="running")
        try:
            before = _snapshot_files(task_dir)
            track_id = _extract_track_id(url)
            if not track_id:
                raise RuntimeError("链接格式有误，请输入 Spotify track 链接")
            cache_key = _cache_key(track_id)

            with _get_cache_lock(cache_key):
                cached_file = _get_cached_file(cache_key)
                if cached_file:
                    file_name = _restore_cached_file(cached_file, task_dir)
                else:
                    success = downloader.download(
                        url=url,
                        output_path=str(task_dir),
                        format=FORMAT,
                        quality=QUALITY,
                        source=SOURCE,
                        cookies=COOKIES_FILE,
                    )
                    if not success:
                        raise RuntimeError(downloader.last_error or "下载失败")
                    file_name = _find_downloaded_file(task_dir, before)
                    if file_name:
                        _store_cached_file(cache_key, task_dir / file_name)

            if not file_name:
                raise RuntimeError("下载完成但未找到输出文件")
            _set_item_fields(task_id, index, status="done", file=file_name, error=None)
        except Exception as exc:
            _set_item_fields(task_id, index, status="failed", error=str(exc))
        _refresh_counts(task_id)

    _build_zip(task_id, task_dir)
    with task_lock:
        task = tasks.get(task_id)
        if task:
            task["status"] = "done" if task["done"] else "failed"
            task["updated_at"] = time.time()


def _cleanup_old_tasks():
    now = time.time()
    expired = []
    with task_lock:
        for task_id, task in tasks.items():
            if now - task["created_at"] > TASK_TTL_SECONDS:
                expired.append(task_id)
        for task_id in expired:
            tasks.pop(task_id, None)
    for task_id in expired:
        task_dir = DOWNLOAD_ROOT / task_id
        if _is_inside(task_dir, DOWNLOAD_ROOT) and task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)


def _public_task(task: Dict) -> Dict:
    return {
        "id": task["id"],
        "status": task["status"],
        "total": task["total"],
        "done": task["done"],
        "failed": task["failed"],
        "zip_file": task["zip_file"],
        "items": task["items"],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    template = templates.get_template("index.html")
    return HTMLResponse(
        template.render(max_links=MAX_LINKS, password_required=bool(WEB_PASSWORD))
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/healthz", include_in_schema=False)
def healthz():
    youtube = get_youtube_health()
    provider = {"status": "disabled"}
    if POT_PROVIDER_URL:
        try:
            with http_requests.Session() as session:
                session.trust_env = False
                response = session.get(f"{POT_PROVIDER_URL}/ping", timeout=2)
                response.raise_for_status()
            provider = {"status": "up"}
        except http_requests.RequestException:
            provider = {"status": "down"}

    healthy = youtube["status"] == "closed" and provider["status"] != "down"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "youtube": youtube, "pot_provider": provider},
    )


@app.post("/api/tasks")
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    x_access_password: Optional[str] = Header(default=None),
):
    _require_password(x_access_password)
    _cleanup_old_tasks()
    _cleanup_cache()
    urls = _validate_urls(payload.urls)
    client_key = request.client.host if request.client else "unknown"
    _check_rate_limit(client_key, len(urls))
    task = _create_task(urls)
    return _public_task(task)


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    x_access_password: Optional[str] = Header(default=None),
):
    _require_password(x_access_password)
    _cleanup_old_tasks()
    with task_lock:
        task = tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        return _public_task(task)


@app.get("/files/{task_id}/{file_name}")
def download_file(
    task_id: str,
    file_name: str,
    x_access_password: Optional[str] = Header(default=None),
    access_password: Optional[str] = Query(default=None),
):
    _require_password(x_access_password, access_password)
    task_dir = DOWNLOAD_ROOT / task_id
    file_path = task_dir / Path(file_name).name
    if not _is_inside(file_path, task_dir) or not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path=str(file_path), filename=file_path.name)
