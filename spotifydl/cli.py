import os
import click
from dotenv import load_dotenv
from .downloader import SpotifyDownloader
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@click.command()
@click.option('--url', '-u', required=True, help='Spotify音乐链接')
@click.option('--output', '-o', required=True, help='输出目录路径')
@click.option('--format', '-f', default='mp3', help='输出格式 (默认: mp3)')
@click.option('--quality', '-q', default='320k', help='音频质量 (默认: 320k)')
def main(url: str, output: str, format: str, quality: str):
    """从Spotify链接下载音乐"""
    try:
        # 加载环境变量
        load_dotenv()
        
        # 获取Spotify API凭证
        client_id = os.getenv('SPOTIFY_CLIENT_ID')
        client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            raise ValueError("未找到Spotify API凭证。请确保设置了SPOTIFY_CLIENT_ID和SPOTIFY_CLIENT_SECRET环境变量。")
        
        # 确保输出目录存在
        os.makedirs(output, exist_ok=True)
        
        # 创建下载器实例
        downloader = SpotifyDownloader(client_id, client_secret)
        
        # 开始下载
        if downloader.download(url, output, format, quality):
            logger.info("下载成功完成！")
        else:
            logger.error("下载失败。")
            exit(1)
            
    except Exception as e:
        logger.error(f"发生错误: {str(e)}")
        exit(1)

if __name__ == '__main__':
    main() 