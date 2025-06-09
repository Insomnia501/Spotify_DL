# SpotifyDL

一个简单的命令行工具，用于从 Spotify 链接下载音乐。支持多个音乐源，确保下载到高质量且匹配的音乐。

## 安装

```bash
pip install spotifydl
```

## 使用方法

1. 设置必要的 API 凭证。在 `.env` 文件中配置以下内容：

```
# Spotify API 凭证（必需）
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

# Deezer API 凭证（可选）
DEEZER_API_KEY=your_deezer_api_key

# SoundCloud API 凭证（可选）
SOUNDCLOUD_CLIENT_ID=your_soundcloud_client_id
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
- `--source` 或 `-s`: 指定音乐源（可选，可选值：deezer, youtubemusic, soundcloud, auto，默认为 youtubemusic）

## 示例

```bash
# 下载单首歌曲（自动选择最佳音乐源）
spotifydl -u "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o "./music"

# 指定使用 Deezer 源下载
spotifydl -u "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o "./music" -s deezer

# 指定使用 YouTube Music 源下载
spotifydl -u "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o "./music" -s youtubemusic

# 指定输出格式和质量
spotifydl -u "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o "./music" -f mp3 -q 320k
```

## 音乐源说明

本工具支持多个音乐源，按以下优先级尝试下载：

1. Deezer（需要 API 凭证）
   - 提供高质量音频
   - 支持多种音频格式
   - 需要 Deezer API 凭证

2. YouTube Music（无需凭证）
   - 提供高质量的官方音频
   - 匹配度高，版本准确
   - 无需额外API凭证

3. SoundCloud（需要 API 凭证）
   - 提供多种音质的音频
   - 支持多种音频格式
   - 需要 SoundCloud API 凭证

工具会自动选择最佳匹配的音乐源，确保下载的音乐与 Spotify 链接中的音乐一致。匹配标准包括：
- 歌曲标题
- 艺术家名称
- 歌曲时长
- ISRC 码（如果可用）

## 注意事项

- 本工具仅用于个人学习和研究使用
- 请遵守相关法律法规和各音乐平台的服务条款
- 下载的音乐仅供个人使用，请勿用于商业用途
- 需要有效的 API 凭证才能使用相应的音乐源
- 建议优先使用 Deezer 源，通常能提供最好的音质

## 许可证

MIT License 