import os
import re
import spotipy
import threading
import time
from spotipy.oauth2 import SpotifyClientCredentials
import logging
from typing import Optional, Dict, Any, List
import requests
from abc import ABC, abstractmethod

from yt_dlp import YoutubeDL
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TRCK
from mutagen.mp3 import MP3
from mutagen import File
import tempfile

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class YouTubeDownloadError(RuntimeError):
    """带分类的 YouTube 下载错误，供 Web 层显示可执行的失败原因。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class YouTubeCircuitBreaker:
    def __init__(self):
        self._lock = threading.Lock()
        self._failure_count = 0
        self._open_until = 0.0

    def check(self):
        with self._lock:
            remaining = self._open_until - time.time()
        if remaining > 0:
            raise YouTubeDownloadError(
                "circuit_open",
                f"YouTube 暂时限制了服务器请求，请约 {max(1, int(remaining / 60) + 1)} 分钟后重试",
            )

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            self._open_until = 0.0

    def record_failure(self, code: str):
        if code not in {"bot_check", "forbidden", "rate_limited"}:
            return
        threshold = max(1, int(os.getenv("SPOTIFYDL_YOUTUBE_BREAKER_THRESHOLD", "3")))
        cooldown = max(60, int(os.getenv("SPOTIFYDL_YOUTUBE_BREAKER_COOLDOWN_SECONDS", "900")))
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= threshold:
                self._open_until = time.time() + cooldown
                self._failure_count = 0
                logger.warning("YouTube 熔断已开启，冷却 %s 秒", cooldown)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            remaining = max(0, int(self._open_until - time.time()))
            return {
                "status": "open" if remaining else "closed",
                "cooldown_remaining_seconds": remaining,
                "recent_failures": self._failure_count,
            }


_youtube_breaker = YouTubeCircuitBreaker()
_youtube_rate_lock = threading.Lock()
_last_youtube_attempt = 0.0


def _wait_for_youtube_rate_slot():
    """限制歌曲级请求启动频率，避免并发任务同时冲击 YouTube。"""
    global _last_youtube_attempt
    interval = max(0.0, float(os.getenv("SPOTIFYDL_YOUTUBE_MIN_INTERVAL_SECONDS", "2")))
    with _youtube_rate_lock:
        wait_seconds = interval - (time.monotonic() - _last_youtube_attempt)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_youtube_attempt = time.monotonic()


def get_youtube_health() -> Dict[str, Any]:
    return _youtube_breaker.status()

class MusicSource(ABC):
    """音乐源抽象基类"""
    @abstractmethod
    def search_track(self, track_info: Dict[str, Any]) -> Optional[str]:
        """搜索音乐并返回下载链接"""
        pass

    @abstractmethod
    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any], 
                      cookies: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> bool:
        """下载音乐"""
        pass

class DeezerSource(MusicSource):
    def __init__(self):
        self.base_url = "https://api.deezer.com"

    def search_track(self, track_info: Dict[str, Any]) -> Optional[str]:
        try:
            query = f"{track_info['name']} {track_info['artists'][0]}"
            response = requests.get(f"{self.base_url}/search", params={
                'q': query,
                'output': 'json'
            })
            if response.status_code == 200:
                data = response.json()
                if data.get('data'):
                    # 返回第一个匹配结果的下载链接
                    return data['data'][0].get('link')
        except Exception as e:
            logger.error(f"Deezer搜索失败: {str(e)}")
        return None

    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any], 
                      cookies: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> bool:
        # 实现 Deezer 下载逻辑
        logger.warning("Deezer下载功能尚未完全实现。")
        return False

class SoundCloudSource(MusicSource):
    def __init__(self):
        self.client_id = os.getenv('SOUNDCLOUD_CLIENT_ID')
        self.base_url = "https://api.soundcloud.com"

    def search_track(self, track_info: Dict[str, Any]) -> Optional[str]:
        try:
            query = f"{track_info['name']} {track_info['artists'][0]}"
            response = requests.get(f"{self.base_url}/tracks", params={
                'q': query,
                'client_id': self.client_id
            })
            if response.status_code == 200:
                data = response.json()
                if data:
                    # 返回第一个匹配结果的下载链接
                    return data[0].get('download_url')
        except Exception as e:
            logger.error(f"SoundCloud搜索失败: {str(e)}")
        return None

    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any], 
                      cookies: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> bool:
        # 实现 SoundCloud 下载逻辑
        logger.warning("SoundCloud下载功能尚未完全实现。")
        return False

class YouTubeSource(MusicSource):
    """YouTube音乐源（通过yt-dlp内置搜索，无需额外API认证）"""

    def __init__(self):
        self.last_error: Optional[YouTubeDownloadError] = None
        self.last_output_path: Optional[str] = None

    def search_track(self, track_info: Dict[str, Any]) -> Optional[str]:
        """构建搜索查询字符串"""
        query = f"{track_info['name']} {track_info['artists'][0]}"
        return query

    def _find_best_match(self, entries: List[Dict], track_info: Dict[str, Any]) -> Optional[Dict]:
        """从搜索结果中按多维度评分选出最佳匹配"""
        target_duration = track_info['duration_ms'] / 1000
        best_entry = None
        best_score = -1

        for entry in entries:
            if not entry:
                continue
            score = 0
            title = entry.get('title', '').lower()
            uploader = (entry.get('uploader', '') + ' ' + entry.get('channel', '')).lower()
            duration = entry.get('duration') or 0

            # 标题匹配（+2）
            if track_info['name'].lower() in title:
                score += 2
            # 艺术家匹配（标题或上传者中包含艺术家名 +2）
            if any(a.lower() in title or a.lower() in uploader for a in track_info['artists']):
                score += 2
            # 时长匹配（10秒内 +3，30秒内 +1）
            if duration:
                diff = abs(duration - target_duration)
                if diff < 10:
                    score += 3
                elif diff < 30:
                    score += 1

            if score > best_score:
                best_score = score
                best_entry = entry

        minimum_score = max(1, int(os.getenv("SPOTIFYDL_YOUTUBE_MIN_MATCH_SCORE", "4")))
        if best_entry and best_score >= minimum_score:
            logger.info(f"最佳匹配: '{best_entry.get('title')}' (评分: {best_score}, 时长: {best_entry.get('duration')}s)")
            return best_entry
        logger.warning("YouTube 最佳候选评分 %s，低于最低要求 %s", best_score, minimum_score)
        return None

    def _download_album_cover(self, track_info: Dict[str, Any]) -> Optional[str]:
        """下载专辑封面"""
        try:
            if track_info.get('album_cover_url'):
                response = requests.get(track_info['album_cover_url'])
                if response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                        temp_file.write(response.content)
                        return temp_file.name
        except Exception as e:
            logger.warning(f"下载专辑封面失败: {str(e)}")
        return None

    def _set_audio_tags(self, file_path: str, track_info: Dict[str, Any], cover_path: Optional[str] = None):
        """设置音频文件的元数据标签"""
        try:
            audio_file = File(file_path)
            if audio_file is None:
                logger.warning(f"无法读取音频文件: {file_path}")
                return

            if isinstance(audio_file, MP3):
                if audio_file.tags is None:
                    audio_file.add_tags()
                tags = audio_file.tags
                tags.clear()
                tags.add(TIT2(encoding=3, text=track_info['name']))
                tags.add(TPE1(encoding=3, text=', '.join(track_info['artists'])))
                tags.add(TALB(encoding=3, text=track_info['album']))
                if track_info.get('release_date'):
                    tags.add(TDRC(encoding=3, text=track_info['release_date'][:4]))
                if track_info.get('track_number'):
                    tags.add(TRCK(encoding=3, text=str(track_info['track_number'])))
                if cover_path and os.path.exists(cover_path):
                    with open(cover_path, 'rb') as cover_file:
                        tags.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc='Cover',
                            data=cover_file.read()
                        ))
                audio_file.save()
                logger.info(f"已设置音频标签: {track_info['name']}")
            else:
                audio_file['TITLE'] = track_info['name']
                audio_file['ARTIST'] = ', '.join(track_info['artists'])
                audio_file['ALBUM'] = track_info['album']
                if track_info.get('release_date'):
                    audio_file['DATE'] = track_info['release_date'][:4]
                audio_file.save()

        except Exception as e:
            logger.warning(f"设置音频标签失败: {str(e)}")

    def _create_safe_filename(self, track_info: Dict[str, Any]) -> str:
        """创建安全的文件名"""
        title = track_info['name']
        artist = track_info['artists'][0] if track_info['artists'] else 'Unknown Artist'
        filename = f"{artist} - {title}"
        unsafe_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        return filename

    def _get_js_runtimes(self) -> dict:
        """自动检测可用的 JS 运行时，用于 yt-dlp EJS YouTube 签名解算"""
        import shutil
        import glob

        # 优先查找 nvm 管理的 node（遍历所有版本）
        nvm_node_pattern = os.path.expanduser('~/.nvm/versions/node/*/bin/node')
        nvm_nodes = sorted(glob.glob(nvm_node_pattern), reverse=True)  # 最新版本优先
        if nvm_nodes:
            node_path = nvm_nodes[0]
            logger.info(f"使用 nvm Node.js: {node_path}")
            return {'node': {'path': node_path}}

        # 其次在 PATH 中查找 node
        node_in_path = shutil.which('node')
        if node_in_path:
            logger.info(f"使用系统 Node.js: {node_in_path}")
            return {'node': {'path': node_in_path}}

        # 最后回退到默认 deno（如果没安装任何运行时，留给 yt-dlp 自己报错）
        logger.warning("未找到 Node.js，回退到 deno（若未安装 deno 则下载可能失败）")
        return {'deno': {}}

    def _get_extractor_options(self) -> Dict[str, Any]:
        provider_url = os.getenv("SPOTIFYDL_POT_PROVIDER_URL", "").strip()
        if not provider_url:
            return {}
        return {
            "extractor_args": {
                "youtube": {"player_client": ["mweb"]},
                "youtubepot-bgutilhttp": {"base_url": [provider_url]},
            }
        }

    def _get_cookie_options(
        self,
        cookies: Optional[str],
        cookies_from_browser: Optional[str],
    ) -> Dict[str, Any]:
        if cookies:
            cookie_path = os.path.abspath(os.path.expanduser(cookies))
            if not os.path.isfile(cookie_path):
                raise YouTubeDownloadError("cookies_invalid", "服务器上的 YouTube Cookies 文件不存在")
            logger.info("登录受限内容使用备用 Cookies 文件: %s", cookie_path)
            return {"cookiefile": cookie_path}
        if cookies_from_browser:
            logger.info("登录受限内容从浏览器导入备用 Cookies: %s", cookies_from_browser)
            return {"cookiesfrombrowser": (cookies_from_browser,)}
        return {}

    def _classify_error(self, error: Exception) -> YouTubeDownloadError:
        if isinstance(error, YouTubeDownloadError):
            return error

        raw_message = str(error)
        message = raw_message.lower()
        if "429" in message or "too many requests" in message:
            return YouTubeDownloadError("rate_limited", "YouTube 请求过于频繁，服务器已进入冷却")
        if "confirm you're not a bot" in message or "confirm you’re not a bot" in message or "captcha" in message:
            return YouTubeDownloadError("bot_check", "YouTube 要求机器人验证，请稍后重试")
        if "403" in message or "forbidden" in message:
            return YouTubeDownloadError("forbidden", "YouTube 拒绝了服务器请求，请稍后重试")

        auth_markers = (
            "age-restricted",
            "age restricted",
            "confirm your age",
            "members-only",
            "members only",
            "private video",
            "login required",
            "authentication required",
        )
        if any(marker in message for marker in auth_markers):
            return YouTubeDownloadError("auth_required", "该 YouTube 内容需要登录验证")
        if "cookie" in message:
            return YouTubeDownloadError("cookies_invalid", "备用 YouTube Cookies 已失效或格式不正确")
        if "timed out" in message or "temporary failure" in message or "network is unreachable" in message:
            return YouTubeDownloadError("network", "连接 YouTube 失败，请稍后重试")
        return YouTubeDownloadError("download_failed", f"YouTube 下载失败: {raw_message}")

    def _cleanup_temporary_files(self, output_path: str, spotify_id: str):
        prefix = f"temp_spotify_dl_{spotify_id}"
        for name in os.listdir(output_path):
            if name.startswith(prefix):
                try:
                    os.remove(os.path.join(output_path, name))
                except OSError:
                    logger.warning("无法清理临时文件: %s", name)

    def _download_attempt(
        self,
        search_query: str,
        output_path: str,
        format: str,
        quality: str,
        track_info: Dict[str, Any],
        auth_options: Dict[str, Any],
    ) -> str:
        search_url = f"ytsearch5:{search_query}"
        logger.info("在 YouTube 上搜索: %s", search_query)
        js_runtimes = self._get_js_runtimes()
        extractor_options = self._get_extractor_options()

        ydl_search_opts = {
            "quiet": True,
            "no_warnings": True,
            "js_runtimes": js_runtimes,
            **extractor_options,
            **auth_options,
        }
        with YoutubeDL(ydl_search_opts) as ydl:
            search_info = ydl.extract_info(search_url, download=False)

        entries = (search_info.get("entries") or []) if search_info else []
        if not entries:
            raise YouTubeDownloadError("no_results", "YouTube 搜索未返回结果")

        best_entry = self._find_best_match(entries, track_info)
        if not best_entry:
            raise YouTubeDownloadError("no_match", "未找到可信度足够的歌曲匹配")

        video_url = best_entry.get("webpage_url") or f"https://www.youtube.com/watch?v={best_entry['id']}"
        logger.info("使用视频: %s", video_url)
        safe_filename = self._create_safe_filename(track_info)
        final_output_path = os.path.join(output_path, f"{safe_filename}.{format}")
        temp_filename = f"temp_spotify_dl_{track_info['spotify_id']}"
        temp_output_template = os.path.join(output_path, f"{temp_filename}.%(ext)s")

        ydl_dl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": format,
                "preferredquality": quality,
            }],
            "outtmpl": temp_output_template,
            "quiet": False,
            "no_warnings": False,
            "keepvideo": False,
            "extractor_retries": 1,
            "fragment_retries": 1,
            "js_runtimes": js_runtimes,
            "http_headers": {"Accept-Language": "en-us,en;q=0.5"},
            **extractor_options,
            **auth_options,
        }
        with YoutubeDL(ydl_dl_opts) as ydl:
            ydl.download([video_url])

        temp_file_path = os.path.join(output_path, f"{temp_filename}.{format}")
        if not os.path.exists(temp_file_path):
            matched = [
                os.path.join(output_path, name)
                for name in os.listdir(output_path)
                if name.startswith(temp_filename) and name.endswith(f".{format}")
            ]
            if not matched:
                raise YouTubeDownloadError("output_missing", "下载完成但未找到音频文件")
            temp_file_path = matched[0]

        cover_path = self._download_album_cover(track_info)
        try:
            self._set_audio_tags(temp_file_path, track_info, cover_path)
            if os.path.exists(final_output_path):
                os.remove(final_output_path)
            os.replace(temp_file_path, final_output_path)
        finally:
            if cover_path and os.path.exists(cover_path):
                os.remove(cover_path)

        logger.info("下载完成并已设置标签: %s.%s", safe_filename, format)
        return final_output_path

    def download_track(self, search_query: str, output_path: str, format: str, quality: str,
                      track_info: Dict[str, Any], cookies: Optional[str] = None,
                      cookies_from_browser: Optional[str] = None) -> bool:
        self.last_error = None
        self.last_output_path = None
        try:
            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(output_path, exist_ok=True)
            _youtube_breaker.check()
            _wait_for_youtube_rate_slot()

            try:
                self.last_output_path = self._download_attempt(
                    search_query, output_path, format, quality, track_info, {}
                )
            except Exception as exc:
                failure = self._classify_error(exc)
                has_fallback = bool(cookies or cookies_from_browser)
                if failure.code != "auth_required" or not has_fallback:
                    raise failure

                logger.warning("匿名下载需要登录，使用备用 Cookies 重试一次")
                self._cleanup_temporary_files(output_path, track_info["spotify_id"])
                auth_options = self._get_cookie_options(cookies, cookies_from_browser)
                self.last_output_path = self._download_attempt(
                    search_query, output_path, format, quality, track_info, auth_options
                )

            _youtube_breaker.record_success()
            return True
        except Exception as e:
            failure = self._classify_error(e)
            self.last_error = failure
            _youtube_breaker.record_failure(failure.code)
            logger.error("使用 yt-dlp 从 YouTube 下载失败 [%s]: %s", failure.code, failure)
            return False

class SpotifyDownloader:
    def __init__(self, client_id: str, client_secret: str):
        """初始化下载器"""
        self.last_error: Optional[str] = None
        self.last_error_code: Optional[str] = None
        self.last_output_path: Optional[str] = None
        self.sp = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            )
        )
        # 初始化音乐源列表
        self.sources: List[MusicSource] = [
            DeezerSource(),
            YouTubeSource(),
            SoundCloudSource(),
            # 可以添加更多音乐源
        ]
    
    def _extract_track_id(self, url: str) -> Optional[str]:
        """从Spotify URL中提取track ID"""
        pattern = r'track/([a-zA-Z0-9]+)'
        match = re.search(pattern, url)
        return match.group(1) if match else None
    
    def _get_track_info(self, track_id: str) -> Dict[str, Any]:
        """获取歌曲信息"""
        try:
            track = self.sp.track(track_id)
            
            # 获取专辑封面URL（选择最高质量的）
            album_cover_url = None
            if track['album']['images']:
                album_cover_url = track['album']['images'][0]['url']  # 第一个通常是最高质量的
            
            return {
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
                'album': track['album']['name'],
                'duration_ms': track['duration_ms'],
                'popularity': track['popularity'],
                'isrc': track['external_ids'].get('isrc', ''),
                'spotify_id': track_id,
                'release_date': track['album']['release_date'],
                'track_number': track['track_number'],
                'album_cover_url': album_cover_url
            }
        except Exception as e:
            logger.error(f"获取歌曲信息失败: {str(e)}")
            raise

    def _find_best_match(self, track_info: Dict[str, Any], search_results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """找到最佳匹配的音乐"""
        if not search_results:
            return None

        best_match = None
        highest_score = 0

        for result in search_results:
            score = 0
            # 检查标题匹配度
            if track_info['name'].lower() in result['title'].lower():
                score += 3
            # 检查艺术家匹配度
            if any(artist.lower() in result['artist'].lower() for artist in track_info['artists']):
                score += 2
            # 检查时长匹配度（允许30秒误差）
            if abs(result.get('duration', 0) - track_info['duration_ms']/1000) < 30:
                score += 2
            # 检查ISRC匹配（如果可用）
            if result.get('isrc') == track_info['isrc']:
                score += 5

            if score > highest_score:
                highest_score = score
                best_match = result

        return best_match if highest_score >= 5 else None

    def download(self, url: str, output_path: str, format: str = 'mp3', quality: str = '320k', 
                source: str = 'auto', cookies: Optional[str] = None, cookies_from_browser: Optional[str] = None) -> bool:
        """下载歌曲"""
        self.last_error = None
        self.last_error_code = None
        self.last_output_path = None
        try:
            # 提取track ID
            track_id = self._extract_track_id(url)
            if not track_id:
                raise ValueError("无效的Spotify URL")
            
            # 获取歌曲信息
            track_info = self._get_track_info(track_id)
            logger.info(f"正在下载: {track_info['name']} - {', '.join(track_info['artists'])}")
            
            # 根据指定的音乐源选择下载源
            sources_to_try = []
            
            if source == 'auto':
                # 自动模式：按优先级尝试所有源
                sources_to_try = self.sources
            elif source == 'deezer':
                sources_to_try = [s for s in self.sources if isinstance(s, DeezerSource)]
            elif source == 'youtubemusic':
                sources_to_try = [s for s in self.sources if isinstance(s, YouTubeSource)]
            elif source == 'soundcloud':
                sources_to_try = [s for s in self.sources if isinstance(s, SoundCloudSource)]
            else:
                raise ValueError(f"不支持的音乐源: {source}")
            
            if not sources_to_try:
                raise ValueError(f"指定的音乐源 '{source}' 不可用")
            
            # 记录最后的错误信息
            last_error = None
            
            # 尝试从指定的音乐源下载
            for music_source in sources_to_try:
                try:
                    logger.info(f"尝试使用音乐源: {music_source.__class__.__name__}")
                    download_url = music_source.search_track(track_info)
                    if download_url:
                        logger.info(f"找到音乐源: {music_source.__class__.__name__}")
                        if music_source.download_track(download_url, output_path, format, quality, track_info, cookies, cookies_from_browser):
                            self.last_output_path = getattr(music_source, "last_output_path", None)
                            logger.info(f"下载完成: {track_info['name']}")
                            return True
                        else:
                            source_error = getattr(music_source, "last_error", None)
                            if source_error:
                                self.last_error_code = getattr(source_error, "code", "download_failed")
                                last_error = str(source_error)
                            else:
                                last_error = f"{music_source.__class__.__name__} 下载失败"
                    else:
                        last_error = f"{music_source.__class__.__name__} 未找到匹配的音乐"
                        
                except Exception as e:
                    last_error = f"从 {music_source.__class__.__name__} 下载失败: {str(e)}"
                    logger.warning(last_error)
                    
                    # 如果不是自动模式，直接抛出错误
                    if source != 'auto':
                        raise
                    
                    continue
            
            # 所有源都失败了
            if source == 'auto':
                raise ValueError(f"所有音乐源都无法下载该歌曲。最后错误: {last_error}")
            else:
                raise ValueError(f"无法从指定的音乐源 '{source}' 下载该歌曲。错误: {last_error}")
            
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"下载失败: {str(e)}")
            return False 
