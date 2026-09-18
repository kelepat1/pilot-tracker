#!/usr/bin/env bash
#
# verify-build.sh — build verification for the macOS widget, on whatever toolchain this Mac has.
#
# Modes:
#   full (default)   xcodebuild the project and check the products. Needs full Xcode.
#                    Falls back to the strongest CLT checks with a clear notice when Xcode is
#                    absent.
#   --link-only      Compile AND link both targets with swiftc, assemble a real .app with the
#                    widget extension embedded, ad-hoc sign it, and verify signatures,
#                    entitlements and linked frameworks. Works with Command Line Tools only,
#                    and is much stronger than a typecheck: it proves codegen, linking against
#                    WidgetKit/SwiftUI, bundle layout and entitlement syntax.
#   --typecheck-only Fastest signal; typechecks both source sets.
#
# Why SDK detection is not trivial on this machine:
#   * /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk (the default SwiftPM uses) was built by
#     a slightly different swiftlang than the installed compiler, so `swift build` fails outright;
#   * the newest SDK (MacOSX27.sdk) has no SwiftUIMacros plugin, so any @State/@Environment use
#     fails with "macro implementation type 'SwiftUIMacros.StateMacro' could not be found".
# The probe below therefore compiles a real SwiftUI view with @State, not a trivial file.
#
set -uo pipefail

cd "$(dirname "$0")"
MODE="${1:-full}"
STATUS=0
CACHE="$(pwd)/.swiftcache"

hdr() { printf '\n=== %s ===\n' "$1"; }
ok()  { printf '  ✅ %s\n' "$1"; }
bad() { printf '  ❌ %s\n' "$1"; STATUS=1; }

# --- pick an SDK that can actually compile SwiftUI ------------------------------------------
detect_sdk() {
  local probe
  probe="$(mktemp -t sdkprobe).swift"
  cat > "$probe" <<'SWIFT'
import SwiftUI
struct Probe: View {
    @State private var value = 1
    var body: some View { Text("\(value)") }
}
SWIFT
  local candidate
  for candidate in $(ls -d /Library/Developer/CommandLineTools/SDKs/MacOSX*.sdk 2>/dev/null | sort -Vr); do
    if swiftc -typecheck -sdk "$candidate" -target arm64-apple-macos14.0 \
        -module-cache-path "$CACHE" "$probe" >/dev/null 2>&1; then
      rm -f "$probe"
      echo "$candidate"
      return 0
    fi
  done
  rm -f "$probe"
  return 1
}

# --- CLT-only: compile, link, assemble, sign ------------------------------------------------
link_only() {
  local sdk="$1" out=/tmp/widget-link-check
  rm -rf "$out"; mkdir -p "$out"

  local target files binary label
  for target in "Models.swift WidgetConfig.swift StatusViews.swift PilotCadetWidget.swift:PilotCadetWidgetExtension:widget extension" \
                "Models.swift WidgetConfig.swift StatusViews.swift PilotCadetApp.swift:PilotCadet:host app"; do
    IFS=':' read -r files binary label <<< "$target"
    hdr "Compile + link: $label"
    # shellcheck disable=SC2086
    if swiftc -O -sdk "$sdk" -target arm64-apple-macos14.0 -module-cache-path "$CACHE" \
         -application-extension -framework SwiftUI -framework WidgetKit \
         $files -o "$out/$binary" 2>/tmp/link.err; then
      ok "$(file -b "$out/$binary")"
    else
      bad "$label failed to build"; sed 's/^/     /' /tmp/link.err | head -15; return
    fi
  done

  hdr "Linked frameworks (WidgetKit/SwiftUI must resolve)"
  local framework
  for framework in WidgetKit SwiftUI; do
    if otool -L "$out/PilotCadetWidgetExtension" | grep -q "$framework"; then
      ok "extension links $framework"
    else
      bad "extension does not link $framework"
    fi
  done

  hdr "Bundle layout + ad-hoc signature"
  local app="$out/PilotCadet.app"
  mkdir -p "$app/Contents/MacOS" "$app/Contents/PlugIns/PilotCadetWidgetExtension.appex/Contents/MacOS"
  cp "$out/PilotCadet" "$app/Contents/MacOS/PilotCadet"
  cp "$out/PilotCadetWidgetExtension" "$app/Contents/PlugIns/PilotCadetWidgetExtension.appex/Contents/MacOS/"
  cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>PilotCadet</string>
<key>CFBundleIdentifier</key><string>com.example.PilotCadet</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
</dict></plist>
PLIST
  # Xcode substitutes these variables; do the same so codesign sees a valid bundle.
  sed -e 's/\$(EXECUTABLE_NAME)/PilotCadetWidgetExtension/g' \
      -e 's/\$(PRODUCT_BUNDLE_IDENTIFIER)/com.example.PilotCadet.PilotCadetWidget/g' \
      -e 's/\$(PRODUCT_NAME)/PilotCadetWidgetExtension/g' \
      -e 's/\$(MACOSX_DEPLOYMENT_TARGET)/14.0/g' \
      Info.plist > "$app/Contents/PlugIns/PilotCadetWidgetExtension.appex/Contents/Info.plist"

  if codesign --force --sign - --timestamp=none --entitlements PilotCadetWidget.entitlements \
       "$app/Contents/PlugIns/PilotCadetWidgetExtension.appex" >/dev/null 2>&1; then
    ok "widget extension signed with PilotCadetWidget.entitlements"
  else
    bad "extension signing failed"
  fi
  if codesign --force --sign - --timestamp=none --entitlements PilotCadet.entitlements "$app" \
       >/dev/null 2>&1; then
    ok "host app signed with PilotCadet.entitlements"
  else
    bad "app signing failed"
  fi

  if codesign --verify --deep --strict "$app" >/dev/null 2>&1; then
    ok "codesign --verify --deep --strict: valid"
  else
    bad "signature verification failed"
  fi

  hdr "Embedded entitlements"
  local bundle name ent key
  for bundle in "$app" "$app/Contents/PlugIns/PilotCadetWidgetExtension.appex"; do
    name=$(basename "$bundle")
    ent=$(codesign -d --entitlements - "$bundle" 2>/dev/null)
    for key in com.apple.security.application-groups com.apple.security.network.client com.apple.security.app-sandbox; do
      if grep -q "$key" <<< "$ent"; then ok "$name has $key"; else bad "$name is missing $key"; fi
    done
  done
}

# --- dispatch -------------------------------------------------------------------------------
# If Xcode is installed but the system-wide developer directory still points at the Command Line
# Tools, use Xcode's toolchain for this run via DEVELOPER_DIR. That needs no sudo and leaves the
# machine's selection untouched.
if ! xcodebuild -version >/dev/null 2>&1 && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi

XCODE_OUT="$(xcodebuild -version 2>&1 || true)"
LICENSE_BLOCKED=0
if grep -qi "license" <<< "$XCODE_OUT"; then
  LICENSE_BLOCKED=1
fi

if [ "$LICENSE_BLOCKED" -eq 1 ] || [ "$MODE" = "--typecheck-only" ] || [ "$MODE" = "--link-only" ] || ! xcodebuild -version >/dev/null 2>&1; then
  if [ "$MODE" = "full" ]; then
    hdr "Full Xcode unavailable"
    if [ "$LICENSE_BLOCKED" -eq 1 ]; then
      echo "  Xcode is installed but its licence has not been accepted, which blocks every"
      echo "  xcodebuild invocation. Accept it once (needs your admin password):"
      echo
      echo "      sudo xcodebuild -license accept"
      echo
      echo "  Then re-run this script for the real xcodebuild check."
    else
      echo "  xcodebuild is missing (only Command Line Tools are installed)."
      echo "  Install Xcode from the App Store, then: sudo xcode-select -s /Applications/Xcode.app"
    fi
    echo "  Continuing with the strongest checks this toolchain allows."
  fi

  if ! SDK="$(detect_sdk)"; then
    bad "no installed SDK can compile SwiftUI with this compiler"; exit 1
  fi
  hdr "Toolchain"
  echo "  compiler: $(swift --version 2>/dev/null | head -1)"
  echo "  SDK:      $SDK"

  if [ "$MODE" != "--typecheck-only" ]; then
    link_only "$SDK"
  fi

  hdr "Typecheck"
  if swiftc -typecheck -module-cache-path "$CACHE" -sdk "$SDK" -target arm64-apple-macos14.0 \
       Models.swift WidgetConfig.swift StatusViews.swift PilotCadetWidget.swift 2>/tmp/tc.err; then
    ok "widget extension typechecks"
  else
    bad "widget extension failed to typecheck"; sed 's/^/     /' /tmp/tc.err | head -10
  fi
  if swiftc -typecheck -module-cache-path "$CACHE" -sdk "$SDK" -target arm64-apple-macos14.0 \
       Models.swift WidgetConfig.swift StatusViews.swift PilotCadetApp.swift 2>/tmp/tc2.err; then
    ok "host app typechecks"
  else
    bad "host app failed to typecheck"; sed 's/^/     /' /tmp/tc2.err | head -10
  fi

  hdr "Python contract"
  # Prefer the project venv (system python3 has no pytest).
  PY=""
  for candidate in ../.venv/bin/python ../../.venv/bin/python "$(command -v python3 || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then PY="$candidate"; break; fi
  done
  if [ -n "$PY" ] && "$PY" -c "import pytest" >/dev/null 2>&1; then
    if "$PY" -m pytest ../scraper/tests -q 2>&1 | tail -2 | sed 's/^/  /'; then
      ok "monitor test suite passes"
    else
      bad "monitor test suite failed"
    fi
  else
    echo "  ⏭  pytest not installed for ${PY:-python3} — skipped (CI runs this step)"
  fi

  printf '\n%s\n' "$([ "$STATUS" -eq 0 ] && echo 'ALL AVAILABLE CHECKS PASSED' || echo 'SOME CHECKS FAILED')"
  echo "Caveat: this does not use Xcode's build system, and an ad-hoc signature is not a"
  echo "distribution signature — the widget will not appear in the widget gallery until it is"
  echo "built and signed in Xcode, or by .github/workflows/widget_build.yml on a macOS runner."
  exit "$STATUS"
fi

hdr "Toolchain"
xcodebuild -version | sed 's/^/  /'

hdr "Project structure"
# Static check first: a duplicate object ID in a hand-written pbxproj makes Xcode resolve a
# reference to the wrong object type and refuse to open the project, and Xcode's message for it
# is hard to read back. This catches it in a second.
if python3 check-pbxproj.py | sed 's/^/  /'; then
  ok "project.pbxproj is internally consistent"
else
  bad "project.pbxproj has structural problems"
fi
if xcodebuild -list -project PilotCadetWidget.xcodeproj 2>&1 | sed 's/^/  /'; then
  ok "xcodebuild can open the project"
else
  bad "xcodebuild could not read the project"
fi

hdr "Build (signing disabled)"
if xcodebuild -project PilotCadetWidget.xcodeproj -scheme PilotCadet -configuration Debug \
     -destination "platform=macOS,arch=arm64" \
     CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
     build 2>&1 | tail -25; then
  ok "xcodebuild succeeded"
else
  bad "xcodebuild failed"
fi

hdr "Products"
APP=$(find ~/Library/Developer/Xcode/DerivedData -name "PilotCadet.app" -maxdepth 6 2>/dev/null | head -1)
APEX=$(find ~/Library/Developer/Xcode/DerivedData -name "PilotCadetWidgetExtension.appex" -maxdepth 8 2>/dev/null | head -1)
[ -n "$APP" ]  && ok "host app:  $APP"  || bad "host app product not found"
[ -n "$APEX" ] && ok "extension: $APEX" || bad "widget extension product not found"
if [ -n "$APP" ] && [ -d "$APP/Contents/PlugIns/PilotCadetWidgetExtension.appex" ]; then
  ok "extension is embedded in the app bundle"
fi
if [ -n "$APEX" ]; then
  POINT=$(/usr/libexec/PlistBuddy -c "Print :NSExtension:NSExtensionPointIdentifier" "$APEX/Contents/Info.plist" 2>/dev/null)
  if [ "$POINT" = "com.apple.widgetkit-extension" ]; then
    ok "extension declares com.apple.widgetkit-extension"
  else
    bad "unexpected NSExtensionPointIdentifier: ${POINT:-<missing>}"
  fi
fi

printf '\n%s\n' "$([ "$STATUS" -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'SOME CHECKS FAILED')"
exit "$STATUS"
