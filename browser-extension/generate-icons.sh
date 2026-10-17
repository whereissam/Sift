#!/bin/bash
# Generate the extension's PNG icons from the app logo
# Requires ImageMagick (or sips on macOS)

cd "$(dirname "$0")"
SRC=../frontend/public/logo.png

if command -v magick &> /dev/null || command -v convert &> /dev/null; then
    IM=$(command -v magick || command -v convert)
    for size in 16 48 128; do
        "$IM" "$SRC" -resize "${size}x${size}" "icons/icon${size}.png"
    done
    echo "Icons generated with ImageMagick"
elif command -v sips &> /dev/null; then
    for size in 16 48 128; do
        sips -z "$size" "$size" "$SRC" --out "icons/icon${size}.png" > /dev/null
    done
    echo "Icons generated with sips"
else
    echo "Please install ImageMagick to generate PNG icons"
    echo "  macOS: brew install imagemagick"
    echo "  Ubuntu: apt install imagemagick"
    exit 1
fi
