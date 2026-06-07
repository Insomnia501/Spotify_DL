# SpotifyDL

从 Spotify 单曲链接读取歌曲元数据，并通过 `yt-dlp` 在 YouTube 上搜索、下载音频，最后写入标题、艺人、专辑、年份、曲序和封面等标签。

> 仅供个人学习和研究使用。请遵守 Spotify、YouTube 及相关平台的服务条款和当地法律法规。

## 当前状态

- 当前可靠下载源：`youtubemusic`（实际通过 `yt-dlp` 搜索 YouTube）。
- `deezer`、`soundcloud`、`auto` 选项仍保留在 CLI 中，但下载逻辑尚未完整实现，不建议作为常规用法。
- 支持单首或多首 Spotify track 链接；暂不支持 playlist/album 批量解析。

## 环境要求(需要自行配置)

- Python 3.8+
- FFmpeg（`yt-dlp` 转音频需要）
- yt-dlp（Python 依赖，执行 `pip install -e .` 时会自动安装；如需单独安装或升级可执行 `python -m pip install -U yt-dlp`）
- Node.js 20.0.0+（推荐安装 Node.js 24 LTS 或更新的 LTS；用于 YouTube 签名解析，代码会自动查找 `nvm` 或 PATH 中的 `node`）

macOS 可用 Homebrew 安装 FFmpeg：

```bash
brew install ffmpeg
```

## 安装本工具

```bash
pip install -e .
```

## 配置

在项目根目录创建 `.env`：

```dotenv
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
```

获取 `SPOTIFY_CLIENT_ID` 和 `SPOTIFY_CLIENT_SECRET`：

1. 打开 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)，使用 Spotify 账号登录。
2. 点击 `Create app` 创建应用，填写应用名称和描述。
3. 创建完成后进入应用详情页，复制 `Client ID` 和 `Client Secret`。
4. 将它们写入项目根目录的 `.env` 文件。

Spotify 官方说明见 [Apps | Spotify for Developers](https://developer.spotify.com/documentation/web-api/concepts/apps)。

![获取 Spotify Client ID 和 Secret](assets/2.png)

## 使用

```bash
spotifydl -u "https://open.spotify.com/track/..." -o "./music" -s youtubemusic
```

常用参数：

- `-u, --url`：Spotify 单曲链接，必填。
- `-o, --output`：输出目录，必填。
- `-f, --format`：输出格式，默认 `mp3`。
- `-q, --quality`：音频质量，默认 `320k`。
- `-s, --source`：音乐源，建议使用默认的 `youtubemusic`。
- `-c, --cookies`：YouTube cookies 文件路径。
- `--cookies-from-browser`：从浏览器读取 cookies，例如 `chrome`、`firefox`、`edge`、`safari`。

如何获取Spotify单曲链接？

![如何获取 Spotify 单曲链接](assets/1.png)



如果遇到 YouTube 机器人验证，可尝试：

```bash
spotifydl -u "https://open.spotify.com/track/..." -o "./music" --cookies-from-browser chrome
```

或指定 cookies 文件：

```bash
spotifydl -u "https://open.spotify.com/track/..." -o "./music" -c "/path/to/cookies.txt"
```

## 批量下载

项目提供了 `batch_dl.sh` 作为批量下载模板。编辑脚本里的 `TRACK_URLS` 数组，每行放一个 Spotify track 链接：

```bash
TRACK_URLS=(
  "https://open.spotify.com/track/..."
  "https://open.spotify.com/track/..."
)
```

按需调整输出目录和下载源：

```bash
OUTPUT_DIR="${OUTPUT_DIR:-./music}"
SOURCE="${SOURCE:-youtubemusic}"
```

如果 YouTube 需要浏览器 cookies，可以运行时传入浏览器名：

```bash
COOKIES_FROM_BROWSER=chrome ./batch_dl.sh
```

首次运行前给脚本增加执行权限：

```bash
chmod +x batch_dl.sh
./batch_dl.sh
```

## 输出

下载完成后，文件名格式为：

```text
艺人 - 歌名.mp3
```

非法文件名字符会被替换为 `_`，同名文件会被覆盖。

## 许可证

MIT License
