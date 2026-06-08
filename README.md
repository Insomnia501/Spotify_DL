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

# Web 版访问密码，部署到服务器时建议设置
SPOTIFYDL_WEB_PASSWORD=your_web_password
```

如何获取 `SPOTIFY_CLIENT_ID` 和 `SPOTIFY_CLIENT_SECRET`？

1. 打开 [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)，使用 Spotify 账号登录。
2. 点击 `Create app` 创建应用，填写应用名称和描述。
3. 创建完成后进入应用详情页，复制 `Client ID` 和 `Client Secret`。
4. 将它们写入项目根目录的 `.env` 文件。

Spotify 官方说明见 [Apps | Spotify for Developers](https://developer.spotify.com/documentation/web-api/concepts/apps)。

![获取 Spotify Client ID 和 Secret](assets/2.png)

## Web 版

启动本地 Web 服务：

```bash
uvicorn spotifydl.web:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`，粘贴一个或多个 Spotify track 链接后点击下载。任务完成后可下载单首歌曲，也可以下载全部歌曲的 zip 包。

Web 版配置项：

- `SPOTIFYDL_WEB_PASSWORD`：访问密码。部署到公网服务器时建议设置。
- `SPOTIFYDL_WEB_MAX_LINKS`：单次最多链接数，默认 `20`。
- `SPOTIFYDL_WEB_TASK_TTL_SECONDS`：下载文件保留时间，默认 `86400` 秒。
- `SPOTIFYDL_WEB_WORKERS`：后台下载任务并发数，默认 `2`。
- `SPOTIFYDL_COOKIES_FILE`：服务器上的 YouTube cookies 文件路径，可用于处理 YouTube 验证。

下载文件会保存在项目内的 `web_downloads/`，该目录已被 git 忽略。

如果页面提示无法连接 Web 服务或 `Failed to fetch`：

1. 确认服务正在运行：`uvicorn spotifydl.web:app --host 127.0.0.1 --port 8000`。
2. 确认浏览器打开的是 `http://127.0.0.1:8000`，不要直接打开 HTML 文件。
3. 修改前端代码后刷新页面；必要时用浏览器强制刷新清理旧脚本缓存。

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
