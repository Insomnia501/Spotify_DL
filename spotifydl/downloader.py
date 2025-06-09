import os
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import logging
from typing import Optional, Dict, Any, List
import requests
from abc import ABC, abstractmethod
import json
from ytmusicapi import YTMusic
from yt_dlp import YoutubeDL
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TRCK
from mutagen.mp3 import MP3
from mutagen import File
import tempfile

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MusicSource(ABC):
    """音乐源抽象基类"""
    @abstractmethod
    def search_track(self, track_info: Dict[str, Any]) -> Optional[str]:
        """搜索音乐并返回下载链接"""
        pass

    @abstractmethod
    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any]) -> bool:
        """下载音乐"""
        pass

class DeezerSource(MusicSource):
    def __init__(self):
        self.base_url = "https://api.deezer.com"
        # 这里需要添加 Deezer API 凭证
        self.api_key = os.getenv('DEEZER_API_KEY')

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

    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any]) -> bool:
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

    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any]) -> bool:
        # 实现 SoundCloud 下载逻辑
        logger.warning("SoundCloud下载功能尚未完全实现。")
        return False

class YouTubeMusicSource(MusicSource):
    """YouTube Music音乐源"""
    def __init__(self):
        self.ytmusic = YTMusic()

    def search_track(self, track_info: Dict[str, Any]) -> Optional[str]:
        query = f"{track_info['name']} {track_info['artists'][0]}"
        try:
            search_results = self.ytmusic.search(query, filter="songs", limit=5)
            
            # 简单的匹配逻辑：选择第一个结果
            if search_results:
                best_match = None
                highest_score = -1

                for result in search_results:
                    score = 0
                    # 检查标题匹配度
                    if track_info['name'].lower() in result['title'].lower():
                        score += 2
                    
                    # 检查艺术家匹配度
                    if result.get('artists') and any(a['name'].lower() in artist.lower() for a in result['artists'] for artist in track_info['artists']):
                        score += 2

                    # 检查时长匹配度 (允许10秒误差)
                    if result.get('duration_seconds') and abs(result['duration_seconds'] - track_info['duration_ms'] / 1000) < 10:
                        score += 3
                    
                    if score > highest_score:
                        highest_score = score
                        best_match = result

                if best_match:
                    logger.info(f"在YouTube Music上找到匹配: {best_match['title']} - {[a['name'] for a in best_match['artists']]}")
                    return f"https://music.youtube.com/watch?v={best_match['videoId']}"

        except Exception as e:
            logger.error(f"YouTube Music搜索失败: {str(e)}")
        return None

    def _download_album_cover(self, track_info: Dict[str, Any]) -> Optional[str]:
        """下载专辑封面"""
        try:
            if track_info.get('album_cover_url'):
                response = requests.get(track_info['album_cover_url'])
                if response.status_code == 200:
                    # 创建临时文件保存封面
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

            # 如果是MP3文件，使用ID3标签
            if isinstance(audio_file, MP3):
                if audio_file.tags is None:
                    audio_file.add_tags()
                
                tags = audio_file.tags
                tags.clear()  # 清除现有标签
                
                # 设置基本信息
                tags.add(TIT2(encoding=3, text=track_info['name']))  # 标题
                tags.add(TPE1(encoding=3, text=', '.join(track_info['artists'])))  # 艺术家
                tags.add(TALB(encoding=3, text=track_info['album']))  # 专辑
                
                # 设置发行年份（如果有）
                if track_info.get('release_date'):
                    tags.add(TDRC(encoding=3, text=track_info['release_date'][:4]))
                
                # 设置曲目编号（如果有）
                if track_info.get('track_number'):
                    tags.add(TRCK(encoding=3, text=str(track_info['track_number'])))
                
                # 添加专辑封面
                if cover_path and os.path.exists(cover_path):
                    with open(cover_path, 'rb') as cover_file:
                        tags.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,  # Cover (front)
                            desc='Cover',
                            data=cover_file.read()
                        ))
                
                audio_file.save()
                logger.info(f"已设置音频标签: {track_info['name']}")
            
            else:
                # 对于其他格式，使用通用标签
                audio_file['TITLE'] = track_info['name']
                audio_file['ARTIST'] = ', '.join(track_info['artists'])
                audio_file['ALBUM'] = track_info['album']
                if track_info.get('release_date'):
                    audio_file['DATE'] = track_info['release_date'][:4]
                audio_file.save()
                
        except Exception as e:
            logger.warning(f"设置音频标签失败: {str(e)}")

    def download_track(self, url: str, output_path: str, format: str, quality: str, track_info: Dict[str, Any]) -> bool:
        try:
            # 确保输出路径是绝对路径
            output_path = os.path.abspath(os.path.expanduser(output_path))
            
            # 使用Spotify信息创建文件名
            safe_filename = self._create_safe_filename(track_info)
            final_output_path = os.path.join(output_path, f"{safe_filename}.{format}")
            
            # 使用一个更简单的临时文件命名策略
            temp_filename = f"temp_spotify_dl_{track_info['spotify_id']}"
            temp_output_template = os.path.join(output_path, f"{temp_filename}.%(ext)s")
            
            logger.info(f"输出目录: {output_path}")
            logger.info(f"临时文件模板: {temp_output_template}")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': format,
                    'preferredquality': quality,
                }],
                'outtmpl': temp_output_template,
                'quiet': False,
                'no_warnings': False,
                'keepvideo': False,
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                # 下载音频
                info = ydl.extract_info(url, download=True)
                logger.info("音频下载完成，开始处理文件...")
                
                # 预期的临时文件路径
                temp_file_path = os.path.join(output_path, f"{temp_filename}.{format}")
                logger.info(f"预期文件路径: {temp_file_path}")
                
                # 检查文件是否存在
                if os.path.exists(temp_file_path):
                    logger.info(f"找到下载的文件: {temp_file_path}")
                    
                    # 下载专辑封面
                    cover_path = self._download_album_cover(track_info)
                    if cover_path:
                        logger.info("专辑封面下载成功")
                    else:
                        logger.warning("专辑封面下载失败")
                    
                    # 设置音频标签
                    self._set_audio_tags(temp_file_path, track_info, cover_path)
                    
                    # 重命名文件为最终名称
                    if os.path.exists(final_output_path):
                        os.remove(final_output_path)  # 删除可能存在的同名文件
                    
                    os.rename(temp_file_path, final_output_path)
                    logger.info(f"文件已重命名为: {final_output_path}")
                    
                    # 清理临时封面文件
                    if cover_path and os.path.exists(cover_path):
                        os.remove(cover_path)
                        logger.info("临时封面文件已清理")
                    
                    logger.info(f"下载完成并已设置标签: {safe_filename}.{format}")
                    return True
                else:
                    # 如果预期的文件不存在，尝试查找所有可能的文件
                    logger.warning(f"预期文件不存在: {temp_file_path}")
                    logger.info("正在查找下载的文件...")
                    
                    # 列出目录中的所有文件
                    try:
                        all_files = os.listdir(output_path)
                        logger.info(f"目录中的所有文件: {all_files}")
                    except Exception as e:
                        logger.error(f"无法列出目录文件: {e}")
                        return False
                    
                    found_files = []
                    for file in all_files:
                        file_path = os.path.join(output_path, file)
                        logger.info(f"检查文件: {file}")
                        if file.endswith(f'.{format}') and temp_filename in file:
                            found_files.append(file_path)
                            logger.info(f"匹配的文件: {file_path}")
                    
                    if found_files:
                        # 使用找到的第一个文件
                        temp_file_path = found_files[0]
                        logger.info(f"使用找到的文件: {temp_file_path}")
                        
                        # 下载专辑封面
                        cover_path = self._download_album_cover(track_info)
                        
                        # 设置音频标签
                        self._set_audio_tags(temp_file_path, track_info, cover_path)
                        
                        # 重命名文件为最终名称
                        if os.path.exists(final_output_path):
                            os.remove(final_output_path)
                        
                        os.rename(temp_file_path, final_output_path)
                        
                        # 清理临时封面文件
                        if cover_path and os.path.exists(cover_path):
                            os.remove(cover_path)
                        
                        logger.info(f"下载完成并已设置标签: {safe_filename}.{format}")
                        return True
                    else:
                        logger.error("无法找到下载的音频文件")
                        return False
            
        except Exception as e:
            logger.error(f"使用yt-dlp从YouTube Music下载失败: {str(e)}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return False

    def _create_safe_filename(self, track_info: Dict[str, Any]) -> str:
        """创建安全的文件名"""
        title = track_info['name']
        artist = track_info['artists'][0] if track_info['artists'] else 'Unknown Artist'
        filename = f"{artist} - {title}"
        
        # 移除不安全的字符
        unsafe_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        
        return filename

class SpotifyDownloader:
    def __init__(self, client_id: str, client_secret: str):
        """初始化下载器"""
        self.sp = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            )
        )
        # 初始化音乐源列表
        self.sources: List[MusicSource] = [
            DeezerSource(),
            YouTubeMusicSource(),
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

    def download(self, url: str, output_path: str, format: str = 'mp3', quality: str = '320k', source: str = 'auto') -> bool:
        """下载歌曲"""
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
                sources_to_try = [s for s in self.sources if isinstance(s, YouTubeMusicSource)]
            elif source == 'soundcloud':
                sources_to_try = [s for s in self.sources if isinstance(s, SoundCloudSource)]
            else:
                raise ValueError(f"不支持的音乐源: {source}")
            
            if not sources_to_try:
                raise ValueError(f"指定的音乐源 '{source}' 不可用")
            
            # 尝试从指定的音乐源下载
            for music_source in sources_to_try:
                try:
                    download_url = music_source.search_track(track_info)
                    if download_url:
                        logger.info(f"找到音乐源: {music_source.__class__.__name__}")
                        if music_source.download_track(download_url, output_path, format, quality, track_info):
                            logger.info(f"下载完成: {track_info['name']}")
                            return True
                except Exception as e:
                    logger.warning(f"从 {music_source.__class__.__name__} 下载失败: {str(e)}")
                    if source != 'auto':  # 如果指定了特定源，不继续尝试其他源
                        raise
                    continue
            
            if source == 'auto':
                raise ValueError("所有音乐源都无法下载该歌曲")
            else:
                raise ValueError(f"无法从指定的音乐源 '{source}' 下载该歌曲")
            
        except Exception as e:
            logger.error(f"下载失败: {str(e)}")
            return False 