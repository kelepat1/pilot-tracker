# mac-widget — native macOS status widget

WidgetKit widget (`systemMedium` / `systemLarge`, macOS 14+) that renders the seven cadet
programmes from your published `status.json`, with green/orange/gray status pills, 🇬🇧/🇪🇺/🌍
passport pills, and a click-through deep link on every row.

## Open it

```bash
open PilotCadetWidget.xcodeproj      # host app target + widget extension target
```

1. **Signing**: nothing to do for local use. The project is configured for ad-hoc signing
   (`CODE_SIGN_IDENTITY = "-"`), which is enough for macOS to register the widget — see
   *Verifying a build* below for the verified command sequence. Picking an **Apple ID team** on
   both targets is only needed to distribute the widget to another machine.
2. **Bundle identifiers**: already set to `com.patrikk31.PilotCadet` and
   `com.patrikk31.PilotCadet.PilotCadetWidget`; change them if you prefer your own prefix (both
   targets, then rebuild and re-run the install commands).
3. **App Groups**: deliberately **not** enabled, because a free personal team cannot sign that
   capability. Nothing is lost: `WidgetConfig` falls back to the widget's own `UserDefaults`, and
   the endpoint comes from `defaultStatusURL` compiled into the code. To enable the shared cache
   with a paid team, uncomment the block at the bottom of both `.entitlements` files and keep
   `WidgetConfig.appGroupIdentifier` in sync.
4. **Endpoint**: set `WidgetConfig.defaultStatusURL` to your published `status.json` (Pages or raw
   GitHub URL). You can also paste it into the running app, which stores it in the app's defaults.
5. Add the widget: *System Settings → Desktop & Dock → Widgets → Edit Widgets*, or right-click
   the desktop → *Edit Widgets* → search "Pilot Cadet Watch".

## Verifying a build without opening Xcode

```bash
./verify-build.sh                 # full: xcodebuild + product checks (needs Xcode)
./verify-build.sh --link-only     # compile+link+assemble+ad-hoc sign (Command Line Tools only)
./verify-build.sh --typecheck-only
python3 check-contract.py         # status.json <-> Models.swift contract
```

`--link-only` compiles and links both targets for release, checks that the extension links
`WidgetKit` and `SwiftUI`, assembles a real `.app` with the `.appex` embedded, ad-hoc signs both
bundles, runs `codesign --verify --deep --strict`, and asserts the App Sandbox and network-client
entitlements are present in both products.

**It can deliver a working local widget.** Verified on 2026-09-18 with Xcode 27.0: an ad-hoc
signed ("Sign to Run Locally") build installed to `/Applications` and launched **is registered by
`pluginkit`** — `pluginkit -m -p com.apple.widgetkit-extension` lists
`com.patrikk31.PilotCadet.PilotCadetWidget(1.0)` — which is exactly what the widget gallery reads.
No Apple ID, team or provisioning profile is required for local use:

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
xcodebuild -project PilotCadetWidget.xcodeproj -scheme PilotCadet -configuration Release \
  -destination "platform=macOS,arch=arm64" \
  CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY="-" CODE_SIGNING_REQUIRED=YES CODE_SIGNING_ALLOWED=YES \
  PROVISIONING_PROFILE_SPECIFIER="" build

ditto "$(ls -d ~/Library/Developer/Xcode/DerivedData/PilotCadetWidget-*/Build/Products/Release | head -1)/PilotCadet.app" \
      /Applications/PilotCadet.app
codesign --verify --deep --strict /Applications/PilotCadet.app
pluginkit -a /Applications/PilotCadet.app/Contents/PlugIns/PilotCadetWidgetExtension.appex
open -a /Applications/PilotCadet.app
```

An Apple ID/team is only needed to *distribute* the widget to other machines (Developer ID
signing and notarisation). `.github/workflows/widget_build.yml` runs a genuine `xcodebuild` on a
macOS runner if you want that proof in CI.

## Toolchain caveat on this machine

The default SDK is `MacOSX.sdk -> MacOSX27.0.sdk`, and **that SDK ships no SwiftUI macro plugin**,
so anything using `@State` or `@Environment` fails with:

```
external macro implementation type 'SwiftUIMacros.StateMacro' could not be found for macro 'State()'
```

`MacOSX26.5.sdk` works. `verify-build.sh` detects this automatically by compiling a real SwiftUI
view; for manual commands use:

```bash
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk swift build
```

`.vscode/settings.json` exports the same `SDKROOT` into the integrated terminal. Installing full
Xcode and selecting it (`sudo xcode-select -s /Applications/Xcode.app`) removes the problem
entirely, since Xcode ships a matched toolchain and its own SDKs.

## Files

| File | Purpose |
|---|---|
| `PilotCadetWidget.swift` | Widget, `TimelineProvider`, row/header views, sample timeline |
| `Models.swift` | Decodable models mirroring `status.json`; tolerant status decoding |
| `WidgetConfig.swift` | Endpoint, App Group, refresh schedule, last-known-good cache |
| `StatusViews.swift` | Status + passport pills, compiled into both targets |
| `PilotCadetApp.swift` | Minimal host app: set the feed URL, refresh the widget |
| `Info.plist` | Widget extension `Info.plist` (`com.apple.widgetkit-extension`) |
| `*.entitlements` | App Sandbox, network client, App Group (identical group in both) |
| `Package.swift` | SwiftPM view of the shared, Xcode-independent sources |
| `verify-build.sh` | Build verification; falls back to CLT-only checks |
| `check-pbxproj.py` | Static project-file validation (duplicate IDs, wiring, embedding) |
| `check-contract.py` | Asserts `status.json` and `Models.swift` still agree |
| `BundledStatus.json` | Snapshot of `status.json` shipped inside the extension, used when the live feed is unreachable |

## How the widget picks its data

`StatusLoader` degrades in order of freshness, and the footer always tells you which one you are
looking at:

1. **Live feed** — `defaultStatusURL`, fetched with `URLSession` and cached on success.
2. **Last successful fetch** — cached in the container, shown as *"Offline – last saved feed"*.
3. **`BundledStatus.json`** — the snapshot compiled into the extension at build time. This is what
   makes a freshly installed widget show the seven programmes instead of an error panel, and it
   also covers a network outage. Refresh it before a build with:
   `cp ../status.json BundledStatus.json`
4. **Error state** — no data at all; it shows the endpoint it tried so a 404 is diagnosable.

## Status of this project's build

Verified with **Xcode 27.0 (27A266a)**: `xcodebuild` builds both targets in Debug and Release as
universal binaries, embeds the extension, and the extension declares
`com.apple.widgetkit-extension` at `LSMinimumSystemVersion 14.0`.

One real defect was found and fixed this way: the app's product **file reference** and the app
**native target** shared the object ID `AA…0010`, so Xcode resolved the Products group's child to
a `PBXNativeTarget` and refused to open the project ("*The PBXGroup … has an invalid value for
children*"). `check-pbxproj.py` now catches that class of error without Xcode.
