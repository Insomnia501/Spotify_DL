import os
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from yt_dlp import YoutubeDL
import logging
from typing import Optional, Dict, Any

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SpotifyDownloader:
    def __init__(self, client_id: str, client_secret: str):
        """初始化下载器"""
        self.sp = spotipy.Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            )
        )
    
    def _extract_track_id(self, url: str) -> Optional[str]:
        """从Spotify URL中提取track ID"""
        pattern = r'track/([a-zA-Z0-9]+)'
        match = re.search(pattern, url)
        return match.group(1) if match else None
    
    def _get_track_info(self, track_id: str) -> Dict[str, Any]:
        """获取歌曲信息"""
        try:
            track = self.sp.track(track_id)
            return {
                'name': track['name'],
                'artists': [artist['name'] for artist in track['artists']],
                'album': track['album']['name']
            }
        except Exception as e:
            logger.error(f"获取歌曲信息失败: {str(e)}")
            raise
    
    def _search_youtube(self, track_info: Dict[str, Any]) -> Optional[str]:
        """在YouTube上搜索歌曲"""
        search_query = f"{track_info['name']} {' '.join(track_info['artists'])} audio"
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
        }
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch:{search_query}", download=False)
                if result and 'entries' in result and result['entries']:
                    return result['entries'][0]['url']
        except Exception as e:
            logger.error(f"YouTube搜索失败: {str(e)}")
        
        return None
    
    def download(self, url: str, output_path: str, format: str = 'mp3', quality: str = '320k') -> bool:
        """下载歌曲"""
        try:
            # 提取track ID
            track_id = self._extract_track_id(url)
            if not track_id:
                raise ValueError("无效的Spotify URL")
            
            # 获取歌曲信息
            track_info = self._get_track_info(track_id)
            logger.info(f"正在下载: {track_info['name']} - {', '.join(track_info['artists'])}")
            
            # 搜索YouTube
            youtube_url = self._search_youtube(track_info)
            if not youtube_url:
                raise ValueError("未找到可下载的音频源")
            
            # 设置下载选项
            ydl_opts = {
                'format': f'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': format,
                    'preferredquality': quality,
                }],
                'outtmpl': os.path.join(output_path, f"{track_info['name']}.%(ext)s"),
                'quiet': False,
                'no_warnings': False,
            }
            
            # 下载音频
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            
            logger.info(f"下载完成: {track_info['name']}")
            return True
            
        except Exception as e:
            logger.error(f"下载失败: {str(e)}")
            return False 