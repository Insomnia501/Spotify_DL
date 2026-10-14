"""Public recommendations, independent of audio downloads."""

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from collections import deque
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
import spotipy
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from spotipy.oauth2 import SpotifyClientCredentials

logger = logging.getLogger(__name__)


class RecommendationRequest(BaseModel):
    spotify_url: str
    nickname: str
    reason: str = ""


def validate_submission(payload):
    nickname = payload.nickname.strip()
    reason = payload.reason.strip()
    if not 1 <= len(nickname) <= 30:
        raise HTTPException(400, "昵称需要填写 1～30 个字符")
    if len(reason) > 300:
        raise HTTPException(400, "推荐理由最多 300 个字符")
    try:
        url = urlsplit(payload.spotify_url.strip())
        match = re.fullmatch(r"/track/([A-Za-z0-9]{22})/?", url.path)
        valid = url.scheme == "https" and url.netloc == "open.spotify.com" and match
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(400, "链接格式有误，请输入 Spotify 单曲链接")
    track_id = match.group(1)
    return track_id, f"https://open.spotify.com/track/{track_id}", nickname, reason


class RecommendationStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT NOT NULL, spotify_url TEXT NOT NULL,
                name TEXT NOT NULL, album TEXT NOT NULL, artists TEXT NOT NULL,
                cover_url TEXT, nickname TEXT NOT NULL, reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS recommendations_recent ON recommendations(created_at DESC, id DESC)")

    @staticmethod
    def deserialize(row):
        result = dict(row)
        result["artists"] = json.loads(result["artists"])
        return result

    def add(self, metadata, spotify_url, nickname, reason):
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        with closing(self.connect()) as connection, connection:
            cursor = connection.execute(
                """INSERT INTO recommendations
                (track_id, spotify_url, name, album, artists, cover_url, nickname, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (metadata["track_id"], spotify_url, metadata["name"], metadata["album"],
                 json.dumps(metadata["artists"], ensure_ascii=False), metadata["cover_url"], nickname, reason, created_at),
            )
            row = connection.execute("SELECT * FROM recommendations WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self.deserialize(row)

    def latest(self):
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT * FROM recommendations ORDER BY created_at DESC, id DESC LIMIT 20").fetchall()
        return [self.deserialize(row) for row in rows]


def fetch_track_metadata(track_id):
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not secret:
        raise HTTPException(503, "歌曲信息服务暂不可用，请稍后重试")
    try:
        with requests.Session() as session:
            credentials = SpotifyClientCredentials(
                client_id=client_id, client_secret=secret, requests_timeout=8,
                requests_session=session, cache_handler=spotipy.MemoryCacheHandler(),
            )
            client = spotipy.Spotify(client_credentials_manager=credentials, requests_timeout=8,
                                     requests_session=session, retries=0, status_retries=0, backoff_factor=0)
            track = client.track(track_id)
        if not track or not track.get("name") or not track.get("artists"):
            raise HTTPException(404, "找不到这首歌曲，请检查链接")
        images = track["album"].get("images") or []
        image = min(images, key=lambda item: abs((item.get("width") or 300) - 300)) if images else None
        cover_url = image.get("url") if image else None
        if cover_url and urlsplit(cover_url).scheme != "https":
            cover_url = None
        return {"track_id": track_id, "name": track["name"], "album": track["album"]["name"],
                "artists": [artist["name"] for artist in track["artists"]], "cover_url": cover_url}
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            raise HTTPException(404, "找不到这首歌曲，请检查链接") from exc
        if exc.http_status == 429:
            retry_after = str((exc.headers or {}).get("Retry-After", "60"))
            raise HTTPException(503, "歌曲信息查询繁忙，请稍后重试", headers={"Retry-After": retry_after}) from exc
        logger.warning("Spotify recommendation lookup failed: status=%s", exc.http_status)
        raise HTTPException(503, "歌曲信息服务暂不可用，请稍后重试") from exc
    except (requests.RequestException, spotipy.SpotifyOauthError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Spotify recommendation lookup failed: %s", type(exc).__name__)
        raise HTTPException(503, "无法获取歌曲信息，请稍后重试") from exc


class SubmissionLimiter:
    def __init__(self, limit=10, window=3600):
        self.limit = limit
        self.window = window
        self.entries = {}
        self.lock = threading.Lock()

    def check(self, key):
        now = time.monotonic()
        with self.lock:
            for old_key, entries in list(self.entries.items()):
                while entries and entries[0] <= now - self.window:
                    entries.popleft()
                if not entries:
                    del self.entries[old_key]
            entries = self.entries.setdefault(key, deque())
            if len(entries) >= self.limit:
                retry = max(1, math.ceil(entries[0] + self.window - now))
                raise HTTPException(429, "推荐提交过于频繁，请稍后重试", headers={"Retry-After": str(retry)})
            entries.append(now)


def create_router(store):
    router = APIRouter()
    limiter = SubmissionLimiter()

    @router.get("/api/recommendations")
    def list_recommendations():
        try:
            return {"items": store.latest()}
        except sqlite3.Error as exc:
            logger.error("Recommendation read failed: %s", type(exc).__name__)
            raise HTTPException(503, "推荐列表暂不可用，请稍后重试") from exc

    @router.post("/api/recommendations", status_code=201)
    def submit_recommendation(payload: RecommendationRequest, request: Request):
        limiter.check(request.client.host if request.client else "unknown")
        track_id, url, nickname, reason = validate_submission(payload)
        metadata = fetch_track_metadata(track_id)
        try:
            return store.add(metadata, url, nickname, reason)
        except sqlite3.Error as exc:
            logger.error("Recommendation write failed: %s", type(exc).__name__)
            raise HTTPException(503, "推荐保存失败，请稍后重试") from exc

    return router
