#!/usr/bin/env bash
#
# install.sh — build the widget, install it to /Applications, and register it cleanly.
#
# Why this is a script and not three commands you run by hand:
#
#   Every Xcode build registers its product with LaunchServices and pluginkit. That means a build
#   in DerivedData and the copy in /Applications are *two* registrations of the same widget bundle
#   identifier, and the widget gallery can read the stale one. The symptom is confusing: the widget
#   appears, but a size you just added is greyed out in "Edit Widgets" because the gallery still
#   believes the older build's set of supported sizes.
#
# So this script removes the build-folder copies and unregisters them before registering the
# installed one, then bounces the widget services so the gallery re-reads it.
#
# Usage:  mac-widget/install.sh
#
set -euo pipefail

cd "$(dirname "$0")"                       # mac-widget/
APP_NAME="PilotCadet"
INSTALLED="/Applications/$APP_NAME.app"
BUNDLE_ID="com.patrikk31.PilotCadet"
APEX_NAME="PilotCadetWidgetExtension"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister"

step() { printf '\n=== %s ===\n' "$1"; }

if ! xcodebuild -version >/dev/null 2>&1 && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi

step "Build (Release, ad-hoc signed)"
xcodebuild -project PilotCadetWidget.xcodeproj -scheme PilotCadet -configuration Release \
  -destination "platform=macOS,arch=arm64" \
  CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" CODE_SIGNING_REQUIRED=YES \
  CODE_SIGNING_ALLOWED=YES PROVISIONING_PROFILE_SPECIFIER="" build \
  | grep -E "BUILD (SUCCEEDED|FAILED)|error:" || true

DERIVED=$(ls -d ~/Library/Developer/Xcode/DerivedData/PilotCadetWidget-*/Build/Products/Release 2>/dev/null | head -1)
[ -n "$DERIVED" ] || { echo "no Release build product found"; exit 1; }
[ -d "$DERIVED/$APP_NAME.app" ] || { echo "build did not produce $APP_NAME.app"; exit 1; }

step "Quit the running copy"
pkill -f "$INSTALLED/Contents/MacOS/$APP_NAME" 2>/dev/null && echo "  quit" || echo "  (not running)"

step "Install to /Applications"
rm -rf "$INSTALLED"
ditto "$DERIVED/$APP_NAME.app" "$INSTALLED"
codesign --verify --deep --strict "$INSTALLED" && echo "  signature verifies"

step "Remove build-folder copies that could shadow the installed widget"
# These are regenerable build products; deleting them does not touch the installed app.
python3 - "$DERIVED" "$LSREGISTER" "$APP_NAME" <<'PY'
import subprocess, sys
from pathlib import Path

release_products = Path(sys.argv[1]).parent          # .../Build/Products
lsregister = sys.argv[2]
app_name = sys.argv[3]

removed = 0
for variant in ("Debug", "Release"):
    app = release_products / variant / f"{app_name}.app"
    if not app.exists():
        continue
    appex = app / "Contents" / "PlugIns" / "PilotCadetWidgetExtension.appex"
    for path in (appex, app):
        if path.exists():
            subprocess.run(["pluginkit", "-r", str(path)], capture_output=True)
            subprocess.run([lsregister, "-u", str(path)], capture_output=True)
    # remove the products so LaunchServices cannot re-discover them
    import shutil
    shutil.rmtree(app)
    removed += 1
print(f"  unregistered and removed {removed} build-folder copy/copies")
PY

step "Refresh the widget gallery"
# Do this BEFORE registering: bouncing chronod at the same moment as pluginkit -a can lose the
# registration, leaving the widget absent from the gallery.
killall chronod 2>/dev/null && echo "  chronod restarted" || echo "  chronod was not running"
killall NotificationCenter 2>/dev/null && echo "  NotificationCenter restarted" || true
sleep 2

step "Register the installed widget extension"
pluginkit -r "$INSTALLED/Contents/PlugIns/$APEX_NAME.appex" 2>/dev/null || true
pluginkit -a "$INSTALLED/Contents/PlugIns/$APEX_NAME.appex"
sleep 2
if ! pluginkit -m -A -D -v -p com.apple.widgetkit-extension 2>/dev/null | grep -qi "$APP_NAME"; then
  echo "  not listed yet - one more nudge"
  pluginkit -a "$INSTALLED/Contents/PlugIns/$APEX_NAME.appex"
  sleep 3
fi

step "What the system now believes"
if pluginkit -m -A -D -v -p com.apple.widgetkit-extension 2>&1 | grep -i "$APP_NAME" | sed 's/^/  /'; then
  count=$(pluginkit -m -A -D -v -p com.apple.widgetkit-extension 2>/dev/null | grep -ci "$APP_NAME")
  [ "$count" -gt 1 ] && echo "  WARNING: $count registrations - a stale copy is still registered and can" \
                           "grey out sizes in the gallery. Remove it with: pluginkit -r <path>"
  [ "$count" -eq 1 ] && echo "  exactly one registration - correct"
else
  echo "  NOT registered - open the gallery once to force discovery, or log out and back in"
fi

echo
echo "Open the gallery: right-click the desktop -> Edit Widgets, or System Settings -> Desktop & Dock -> Widgets."
echo "Sizes offered come from supportedFamilies in PilotCadetWidget.swift: small, medium, large, extra-large."
echo "If a size you just added is still greyed out, log out and back in once - the gallery keeps a"
echo "per-user cache that only a session restart reliably clears."
