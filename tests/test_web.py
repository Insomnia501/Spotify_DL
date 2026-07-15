import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from spotifydl import web


class WebHelpersTests(unittest.TestCase):
    def setUp(self):
        with web.rate_limit_lock:
            web.rate_limit_entries.clear()

    def test_extracts_strict_spotify_track_url(self):
        track_id = "1234567890123456789012"
        self.assertEqual(
            web._extract_track_id(f"https://open.spotify.com/track/{track_id}?si=test"),
            track_id,
        )
        self.assertIsNone(web._extract_track_id(f"https://example.com/track/{track_id}"))
        self.assertIsNone(web._extract_track_id("https://open.spotify.com/album/invalid"))

    def test_rate_limit_counts_tracks_in_batch(self):
        with patch.object(web, "RATE_LIMIT_TRACKS", 2), patch.object(web, "RATE_LIMIT_WINDOW_SECONDS", 3600):
            web._check_rate_limit("client", 2)
            with self.assertRaises(HTTPException) as raised:
                web._check_rate_limit("client", 1)

        self.assertEqual(raised.exception.status_code, 429)

    def test_cache_round_trip(self):
        with tempfile.TemporaryDirectory(dir=web.PROJECT_ROOT) as temporary_dir:
            root = Path(temporary_dir)
            source = root / "Artist - Song.mp3"
            source.write_bytes(b"audio")
            cache_root = root / "cache"
            task_dir = root / "task"
            task_dir.mkdir()

            with patch.object(web, "CACHE_ENABLED", True), patch.object(web, "CACHE_ROOT", cache_root):
                web._store_cached_file("track-mp3-320k", source)
                cached_file = web._get_cached_file("track-mp3-320k")
                restored_name = web._restore_cached_file(cached_file, task_dir)

            self.assertEqual(restored_name, source.name)
            self.assertEqual((task_dir / restored_name).read_bytes(), b"audio")

    def test_health_endpoint_without_provider(self):
        with patch.object(web, "POT_PROVIDER_URL", ""):
            response = web.healthz()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"pot_provider":{"status":"disabled"}', response.body)


if __name__ == "__main__":
    unittest.main()
