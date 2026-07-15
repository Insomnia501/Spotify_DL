import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from spotifydl.downloader import YouTubeDownloadError, YouTubeSource


TRACK_INFO = {
    "name": "Test Song",
    "artists": ["Test Artist"],
    "duration_ms": 180000,
    "spotify_id": "1234567890123456789012",
}


class YouTubeSourceTests(unittest.TestCase):
    def test_rejects_candidate_below_match_threshold(self):
        source = YouTubeSource()
        entries = [{"id": "video", "title": "Unrelated", "duration": 180}]

        with patch.dict(os.environ, {"SPOTIFYDL_YOUTUBE_MIN_MATCH_SCORE": "4"}):
            self.assertIsNone(source._find_best_match(entries, TRACK_INFO))

    def test_configures_http_po_token_provider(self):
        source = YouTubeSource()

        with patch.dict(os.environ, {"SPOTIFYDL_POT_PROVIDER_URL": "http://pot-provider:4416"}):
            options = source._get_extractor_options()

        self.assertEqual(options["extractor_args"]["youtube"]["player_client"], ["mweb"])
        self.assertEqual(
            options["extractor_args"]["youtubepot-bgutilhttp"]["base_url"],
            ["http://pot-provider:4416"],
        )

    def test_classifies_age_check_before_cookie_hint(self):
        source = YouTubeSource()
        failure = source._classify_error(
            RuntimeError("Sign in to confirm your age. Use --cookies-from-browser or --cookies")
        )
        self.assertEqual(failure.code, "auth_required")

    def test_uses_cookies_only_after_auth_required_error(self):
        source = YouTubeSource()
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as output_dir:
            cookie_file = Path(output_dir) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch.dict(os.environ, {"SPOTIFYDL_YOUTUBE_MIN_INTERVAL_SECONDS": "0"}), patch.object(
                source,
                "_download_attempt",
                side_effect=[YouTubeDownloadError("auth_required", "需要登录"), str(Path(output_dir) / "song.mp3")],
            ) as attempt:
                success = source.download_track(
                    "query", output_dir, "mp3", "320k", TRACK_INFO, cookies=str(cookie_file)
                )

        self.assertTrue(success)
        self.assertEqual(attempt.call_count, 2)
        self.assertEqual(attempt.call_args_list[0].args[-1], {})
        self.assertEqual(attempt.call_args_list[1].args[-1]["cookiefile"], str(cookie_file))

    def test_does_not_send_cookies_for_bot_check(self):
        source = YouTubeSource()
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as output_dir:
            cookie_file = Path(output_dir) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch.dict(os.environ, {"SPOTIFYDL_YOUTUBE_MIN_INTERVAL_SECONDS": "0"}), patch.object(
                source,
                "_download_attempt",
                side_effect=YouTubeDownloadError("bot_check", "机器人验证"),
            ) as attempt:
                success = source.download_track(
                    "query", output_dir, "mp3", "320k", TRACK_INFO, cookies=str(cookie_file)
                )

        self.assertFalse(success)
        self.assertEqual(attempt.call_count, 1)
        self.assertEqual(source.last_error.code, "bot_check")


if __name__ == "__main__":
    unittest.main()
