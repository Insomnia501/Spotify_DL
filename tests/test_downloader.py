import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from spotifydl.downloader import YouTubeDiagnostics, YouTubeDownloadError, YouTubeSource


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

    def test_flat_search_selects_only_one_video_for_download(self):
        source = YouTubeSource()
        search = MagicMock()
        search.extract_info.return_value = {"entries": [
            {"id": "wrong", "title": "Unrelated", "channel": None, "uploader": None, "duration": 180},
            {"id": "correct", "title": "Test Artist - Test Song", "duration": 180},
        ]}
        download = MagicMock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as output_dir:
            temporary = Path(output_dir) / f"temp_spotify_dl_{TRACK_INFO['spotify_id']}.mp3"
            download.download.side_effect = lambda urls: temporary.write_bytes(b"audio")
            with patch("spotifydl.downloader.YoutubeDL") as factory, patch.object(
                source, "_get_js_runtimes", return_value={}
            ), patch.object(source, "_download_album_cover", return_value=None), patch.object(source, "_set_audio_tags"):
                factory.return_value.__enter__.side_effect = [search, download]
                result = source._download_attempt("query", output_dir, "mp3", "320k", TRACK_INFO, {})
                self.assertTrue(Path(result).exists())
                self.assertTrue(factory.call_args_list[0].args[0]["extract_flat"])
                self.assertNotIn("extractor_args", factory.call_args_list[0].args[0])
                download.download.assert_called_once_with(["https://www.youtube.com/watch?v=correct"])

    def test_search_failure_preserves_bot_classification_and_stage(self):
        source = YouTubeSource()
        with patch("spotifydl.downloader.YoutubeDL") as factory, patch.object(source, "_get_js_runtimes", return_value={}):
            factory.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError("Confirm you're not a bot")
            with self.assertRaises(YouTubeDownloadError) as raised:
                source._download_attempt("query", ".", "mp3", "320k", TRACK_INFO, {})
        self.assertEqual(raised.exception.code, "bot_check")
        self.assertEqual(raised.exception.stage, "search")

    def test_token_diagnostics_do_not_log_secret(self):
        diagnostics = YouTubeDiagnostics()
        with self.assertLogs("spotifydl.downloader", level="INFO") as captured:
            diagnostics.debug("[pot:bgutil:http] Generating a gvs PO Token")
            diagnostics.debug("[pot:bgutil:http] Generated POT: secret-token-value")
            diagnostics.warning("[pot] Error reaching POST /get_pot")
        self.assertTrue(diagnostics.token_requested)
        self.assertTrue(diagnostics.token_generated)
        self.assertTrue(diagnostics.token_failed)
        self.assertNotIn("secret-token-value", " ".join(captured.output))

    def test_provider_warning_is_reported_as_token_failure(self):
        source = YouTubeSource()
        search = MagicMock()
        search.extract_info.return_value = {"entries": [{
            "id": "correct", "title": "Test Artist - Test Song", "duration": 180,
        }]}

        def download_factory(options):
            context = MagicMock()
            if options.get("extract_flat"):
                context.__enter__.return_value = search
            else:
                def fail(urls):
                    options["logger"].warning("[pot:bgutil:http] Error reaching POST /get_pot")
                    raise RuntimeError("Requested format is not available")
                context.__enter__.return_value.download.side_effect = fail
            return context

        with patch("spotifydl.downloader.YoutubeDL", side_effect=download_factory), patch.object(
            source, "_get_js_runtimes", return_value={}
        ):
            with self.assertRaises(YouTubeDownloadError) as raised:
                source._download_attempt("query", ".", "mp3", "320k", TRACK_INFO, {})
        self.assertEqual(raised.exception.code, "token_failed")
        self.assertEqual(raised.exception.stage, "token")

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

    def test_retries_bot_check_once_with_cookies(self):
        source = YouTubeSource()
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as output_dir:
            cookie_file = Path(output_dir) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\\n", encoding="utf-8")
            with patch.dict(os.environ, {"SPOTIFYDL_YOUTUBE_MIN_INTERVAL_SECONDS": "0"}), patch.object(
                source,
                "_download_attempt",
                side_effect=[YouTubeDownloadError("bot_check", "机器人验证"), str(Path(output_dir) / "song.mp3")],
            ) as attempt:
                success = source.download_track(
                    "query", output_dir, "mp3", "320k", TRACK_INFO, cookies=str(cookie_file)
                )

        self.assertTrue(success)
        self.assertEqual(attempt.call_count, 2)
        self.assertEqual(attempt.call_args_list[0].args[-1], {})
        self.assertEqual(attempt.call_args_list[1].args[-1]["cookiefile"], str(cookie_file))

    def test_does_not_retry_bot_check_more_than_once(self):
        source = YouTubeSource()
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as output_dir:
            cookie_file = Path(output_dir) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\\n", encoding="utf-8")
            with patch.dict(os.environ, {"SPOTIFYDL_YOUTUBE_MIN_INTERVAL_SECONDS": "0"}), patch.object(
                source,
                "_download_attempt",
                side_effect=[YouTubeDownloadError("bot_check", "机器人验证"), YouTubeDownloadError("bot_check", "仍需验证")],
            ) as attempt:
                success = source.download_track(
                    "query", output_dir, "mp3", "320k", TRACK_INFO, cookies=str(cookie_file)
                )

        self.assertFalse(success)
        self.assertEqual(attempt.call_count, 2)
        self.assertEqual(attempt.call_args_list[1].args[-1]["cookiefile"], str(cookie_file))
        self.assertEqual(source.last_error.code, "bot_check")


if __name__ == "__main__":
    unittest.main()
