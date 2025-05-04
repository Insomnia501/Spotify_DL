# SpotifyDL

一个简单的命令行工具，用于从 Spotify 链接下载音乐。

## 安装

```bash
pip install spotifydl
```

## 使用方法

1. 设置 Spotify API 凭证。在.env文件里。包含以下内容：

```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

2. 使用命令行下载音乐：

```bash
spotifydl --url "https://open.spotify.com/track/your_track_id" -o "/path/to/output"
```

### 参数说明

- `--url` 或 `-u`: Spotify 音乐链接（必需）
- `--output` 或 `-o`: 输出目录路径（必需）
- `--format` 或 `-f`: 输出格式（可选，默认为 mp3）
- `--quality` 或 `-q`: 音频质量（可选，默认为 320k）

## 示例

```bash
# 下载单首歌曲
spotifydl -u "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o "./music"

# 指定输出格式和质量
spotifydl -u "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o "./music" -f mp3 -q 320k
```

## 注意事项

- 本工具仅用于个人学习和研究使用
- 请遵守相关法律法规和 Spotify 的服务条款
- 下载的音乐仅供个人使用，请勿用于商业用途

## 许可证

MIT License 