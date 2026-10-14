import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import requests
import spotipy
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from spotifydl.recommendations import RecommendationStore, create_router, fetch_track_metadata

TRACK_ID = "1234567890123456789012"
METADATA = {"track_id": TRACK_ID, "name": "Song", "album": "Album", "artists": ["Artist"], "cover_url": None}
PAYLOAD = {"spotify_url": f"https://open.spotify.com/track/{TRACK_ID}?si=test", "nickname": " Listener ", "reason": "Great song"}


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temporary.cleanup)
        self.store = RecommendationStore(Path(self.temporary.name) / "board.sqlite3")
        self.store.initialize()
        self.app = FastAPI()
        self.app.include_router(create_router(self.store))
        self.client = TestClient(self.app)

    def test_public_submission_duplicate_and_persistence(self):
        with patch("spotifydl.recommendations.fetch_track_metadata", return_value=METADATA) as fetch:
            for _ in range(2):
                response = self.client.post("/api/recommendations", json=PAYLOAD)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["nickname"], "Listener")
                self.assertNotIn("?", response.json()["spotify_url"])
            fetch.assert_called_with(TRACK_ID)
        reopened = RecommendationStore(self.store.path)
        reopened.initialize()
        self.assertEqual(len(reopened.latest()), 2)
        self.assertGreater(reopened.latest()[0]["id"], reopened.latest()[1]["id"])
        with patch("spotifydl.recommendations.fetch_track_metadata") as fetch:
            response = self.client.get("/api/recommendations")
            self.assertEqual(response.status_code, 200)
            fetch.assert_not_called()

    def test_latest_twenty_same_timestamp(self):
        for index in range(25):
            self.store.add(METADATA, PAYLOAD["spotify_url"], str(index), "")
        with closing(self.store.connect()) as connection, connection:
            connection.execute("UPDATE recommendations SET created_at = ?", ("2026-01-01T00:00:00+00:00",))
        items = self.store.latest()
        self.assertEqual(len(items), 20)
        self.assertEqual([item["id"] for item in items], list(range(25, 5, -1)))

    def test_validation_does_not_call_spotify(self):
        invalid = [{**PAYLOAD, "spotify_url": "https://evil.test/track/" + TRACK_ID},
                   {**PAYLOAD, "nickname": " "}, {**PAYLOAD, "nickname": "x" * 31},
                   {**PAYLOAD, "reason": "x" * 301}]
        with patch("spotifydl.recommendations.fetch_track_metadata") as fetch:
            for payload in invalid:
                self.assertEqual(self.client.post("/api/recommendations", json=payload).status_code, 400)
            fetch.assert_not_called()
        self.assertEqual(self.store.latest(), [])

    def test_failures_are_not_saved(self):
        with patch("spotifydl.recommendations.fetch_track_metadata", side_effect=HTTPException(404, "missing")):
            self.assertEqual(self.client.post("/api/recommendations", json=PAYLOAD).status_code, 404)
        with patch("spotifydl.recommendations.fetch_track_metadata", return_value=METADATA), patch.object(
            self.store, "add", side_effect=sqlite3.OperationalError("locked")
        ):
            self.assertEqual(self.client.post("/api/recommendations", json=PAYLOAD).status_code, 503)
        self.assertEqual(self.store.latest(), [])

    def test_limiter_counts_failed_attempts(self):
        with patch("spotifydl.recommendations.fetch_track_metadata", side_effect=HTTPException(503, "unavailable")) as fetch:
            for _ in range(10):
                self.assertEqual(self.client.post("/api/recommendations", json=PAYLOAD).status_code, 503)
            response = self.client.post("/api/recommendations", json=PAYLOAD)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(fetch.call_count, 10)

    def test_metadata_selects_medium_cover_and_handles_errors(self):
        track = {"name": "Song", "artists": [{"name": "Artist"}], "album": {"name": "Album", "images": [
            {"width": 640, "url": "https://example.com/large.jpg"},
            {"width": 300, "url": "https://example.com/medium.jpg"},
        ]}}
        with patch.dict("os.environ", {"SPOTIFY_CLIENT_ID": "test", "SPOTIFY_CLIENT_SECRET": "test"}), patch(
            "spotifydl.recommendations.spotipy.Spotify"
        ) as factory:
            factory.return_value.track.return_value = track
            self.assertEqual(fetch_track_metadata(TRACK_ID)["cover_url"], "https://example.com/medium.jpg")
            track["album"]["images"] = []
            self.assertIsNone(fetch_track_metadata(TRACK_ID)["cover_url"])
            for error, expected in [(requests.Timeout(), 503),
                                    (spotipy.SpotifyException(404, -1, "missing"), 404),
                                    (spotipy.SpotifyException(429, -1, "busy", headers={"Retry-After": "90"}), 503)]:
                factory.return_value.track.side_effect = error
                with self.assertRaises(HTTPException) as raised:
                    fetch_track_metadata(TRACK_ID)
                self.assertEqual(raised.exception.status_code, expected)
                if getattr(error, "http_status", None) == 429:
                    self.assertEqual(raised.exception.headers["Retry-After"], "90")

    def test_real_app_routes_do_not_require_download_password(self):
        from spotifydl import web
        client = TestClient(web.app)
        with patch.object(web, "WEB_PASSWORD", "private"), patch.object(web.recommendation_store, "latest", return_value=[]), patch.object(web, "_create_task") as download, patch(
            "spotifydl.recommendations.fetch_track_metadata", return_value=METADATA
        ), patch.object(web.recommendation_store, "add", return_value={"id": 1}):
            self.assertEqual(client.get("/api/recommendations").status_code, 200)
            self.assertEqual(client.post("/api/recommendations", json=PAYLOAD).status_code, 201)
            self.assertEqual(client.post("/api/tasks", json={"urls": []}).status_code, 401)
            download.assert_not_called()

    def test_text_is_stored_literally_and_blank_reason_is_normalized(self):
        payload = {**PAYLOAD, "nickname": "<script>alert(1)</script>", "reason": "  "}
        with patch("spotifydl.recommendations.fetch_track_metadata", return_value=METADATA):
            response = self.client.post("/api/recommendations", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["nickname"], payload["nickname"])
        self.assertEqual(response.json()["reason"], "")


if __name__ == "__main__":
    unittest.main()
