#!/bin/bash
# Build and run the offscreen layout renderer. Usage: preview/render.sh
set -euo pipefail
cd "$(dirname "$0")/.."                       # mac-widget/

SDK="${SDK:-/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk}"
[ -d "$SDK" ] || SDK=$(xcrun --sdk macosx --show-sdk-path)
OUT="preview/out"
mkdir -p "$OUT"

swiftc -O -sdk "$SDK" -target arm64-apple-macos14.0 \
  -framework SwiftUI -framework WidgetKit -framework AppKit \
  Models.swift WidgetConfig.swift StatusViews.swift WidgetContentViews.swift preview/Renderer.swift \
  -o /tmp/widget-preview-render

/tmp/widget-preview-render "$OUT"
