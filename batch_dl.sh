#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

OUTPUT_DIR="${OUTPUT_DIR:-./music}"
SOURCE="${SOURCE:-youtubemusic}"
COOKIES_FROM_BROWSER="${COOKIES_FROM_BROWSER:-}"

TRACK_URLS=(
  "https://open.spotify.com/track/..."
  "https://open.spotify.com/track/..."
)

mkdir -p "$OUTPUT_DIR"

for url in "${TRACK_URLS[@]}"; do
  if [[ "$url" != *"/track/"* ]]; then
    echo "Skip non-track URL: $url"
    continue
  fi

  if [[ -n "$COOKIES_FROM_BROWSER" ]]; then
    spotifydl -u "$url" -o "$OUTPUT_DIR" -s "$SOURCE" --cookies-from-browser "$COOKIES_FROM_BROWSER"
  else
    spotifydl -u "$url" -o "$OUTPUT_DIR" -s "$SOURCE"
  fi
done
