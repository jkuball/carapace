#!/usr/bin/env bash

set -euo pipefail

if ! command -v magick >/dev/null 2>&1; then
  echo "magick is required to generate frontend/public PWA icons" >&2
  exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
frontend_root=$(cd "$script_dir/.." && pwd)
icon_svg="$frontend_root/src/app/icon.svg"

# Render SVG at high density first. Without this, ImageMagick rasterizes the
# 36x36 source at its intrinsic size and then upscales it, which makes large
# PNG install icons noticeably blurry.
magick -background none -density 576 "$icon_svg" -resize 192x192 "$frontend_root/public/pwa-192x192.png"
magick -background none -density 1536 "$icon_svg" -resize 512x512 "$frontend_root/public/pwa-512x512.png"
magick -background none -density 540 "$icon_svg" -resize 180x180 "$frontend_root/public/apple-touch-icon.png"

echo "Generated PWA icons from $icon_svg"
