//
//  Renderer.swift — offscreen renderer for the widget layouts.
//
//  Widgets cannot be screenshotted from a script, and a layout that clips is only visible when it
//  is rendered at the exact size macOS gives it. This harness draws each family into a PNG at its
//  real point size, so the layouts can be checked visually:
//
//      mac-widget/preview/render.sh          # PNGs land in mac-widget/preview/out/
//
//  It compiles the view layer WITHOUT PilotCadetWidget.swift, because that file holds the widget
//  bundle's `@main` and would clash with this executable's entry point.
//
//  Sizes are the macOS point sizes for each family; the 12pt margin approximates what WidgetKit
//  applies, so text that fits here fits on the desktop.
//

import AppKit
import SwiftUI
import WidgetKit   // for WidgetFamily

@main
struct WidgetPreviewRenderer {

    // Real macOS widget point sizes.
    static let small = CGSize(width: 170, height: 170)
    static let medium = CGSize(width: 364, height: 170)
    static let large = CGSize(width: 364, height: 382)
    static let extraLarge = CGSize(width: 776, height: 382)
    /// Must match PilotCadetWidgetView.contentMargin(for:) — WidgetKit's own margins are
    /// disabled, so these *are* the content margins.
    static func margin(_ family: WidgetFamily) -> CGFloat { family == .systemSmall ? 12 : 14 }

    @MainActor
    static func main() {
        let outputDirectory = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
        let document = StatusDocument.sample

        func content(_ family: WidgetFamily, document doc: StatusDocument = StatusDocument.sample,
                     error: String? = nil, cached: Bool = false) -> some View {
            PilotCadetContentView(document: doc, error: error, isFromCache: cached, family: family)
                .padding(margin(family))
        }

        render(content(.systemSmall, document: document), points: small, name: "01-small", into: outputDirectory)
        render(content(.systemMedium, document: document), points: medium, name: "02-medium", into: outputDirectory)
        render(content(.systemLarge, document: document), points: large, name: "03-large", into: outputDirectory)
        render(content(.systemExtraLarge, document: document), points: extraLarge, name: "04-extraLarge", into: outputDirectory)

        // Failure states, which must not clip either.
        render(
            content(.systemMedium, document: document, error: "status.json not found (404). Check the Pages URL.", cached: true),
            points: medium, name: "05-medium-offline", into: outputDirectory
        )
        render(
            PilotCadetEmptyView(message: "status.json not found (404). Check the Pages URL and that Pages is enabled.").padding(margin(.systemSmall)),
            points: small, name: "06-small-no-feed", into: outputDirectory
        )

        // Worst case: a very long airline/programme name, a long evidence sentence and a stale row.
        let stress = StatusDocument(
            schemaVersion: 1,
            generatedAt: document.generatedAt,
            summary: document.summary,
            programs: document.programs.enumerated().map { index, program in
                guard index == 0 else { return program }
                return ProgramStatus(
                    id: program.id,
                    airline: "Cathay Pacific Airways (Hong Kong)",
                    program: "Cadet Pilot Programme — fully sponsored, ~80 weeks",
                    passport: program.passport,
                    passportLabel: program.passportLabel,
                    rtwScope: program.rtwScope,
                    status: .open,
                    evidence: "Applications to the ~80-week Cathay Cadet Pilot Programme are open year-round, and this sentence is deliberately long to test truncation.",
                    consecutiveFailures: 2
                )
            }
        )
        render(content(.systemSmall, document: stress), points: small, name: "07-small-stress", into: outputDirectory)
        render(content(.systemMedium, document: stress), points: medium, name: "08-medium-stress", into: outputDirectory)
        render(content(.systemLarge, document: stress), points: large, name: "09-large-stress", into: outputDirectory)

        // Dark appearance, since macOS widgets follow the system theme.
        render(
            content(.systemMedium, document: document).environment(\.colorScheme, .dark),
            points: medium, name: "10-medium-dark", into: outputDirectory
        )

        // ---- does every layout fit the box the widget gives it? ------------------------------
        //
        // WidgetKit's default margins are disabled in the configuration, so the usable box is
        // exactly the family size minus the margin this code applies. That makes these checks
        // authoritative rather than approximate.
        print("\nlayout fit (intrinsic content vs the usable box):")
        var failures = 0

        func usable(_ size: CGSize, _ family: WidgetFamily) -> CGSize {
            CGSize(width: size.width - margin(family) * 2, height: size.height - margin(family) * 2)
        }
        func raw(_ family: WidgetFamily, doc: StatusDocument) -> some View {
            PilotCadetContentView(document: doc, error: nil, isFromCache: false, family: family)
        }
        func check(_ family: WidgetFamily, _ size: CGSize, _ label: String, doc: StatusDocument) {
            if !measure(raw(family, doc: doc), available: usable(size, family), name: label) { failures += 1 }
        }

        check(.systemSmall, small, "small", doc: document)
        check(.systemMedium, medium, "medium", doc: document)
        check(.systemLarge, large, "large", doc: document)
        check(.systemExtraLarge, extraLarge, "extraLarge", doc: document)
        check(.systemSmall, small, "small (long names)", doc: stress)
        check(.systemMedium, medium, "medium (long names)", doc: stress)
        check(.systemLarge, large, "large (long names)", doc: stress)
        check(.systemExtraLarge, extraLarge, "extraLarge (long names)", doc: stress)
        // The failure states must fit too.
        if !measure(PilotCadetEmptyView(message: "status.json not found (404). Check the Pages URL and that Pages is enabled."),
                    available: usable(small, .systemSmall), name: "small (no feed)") { failures += 1 }

        print(failures == 0
              ? "\nall layouts fit their box"
              : "\n\(failures) layout(s) do not fit - see above")
        exit(failures == 0 ? 0 : 1)
    }

    /// Measures a layout's intrinsic size against the box macOS will give it.
    ///
    /// This is the check that matters for "does it display correctly at every size", and it is
    /// stricter than looking at a screenshot: a stack that needs more height than the family
    /// offers gets clipped, and a row whose intrinsic width exceeds the family will have its text
    /// truncated with "…" (or shrunk by minimumScaleFactor). Both are reported here numerically.
    @MainActor
    static func measure(_ view: some View, available: CGSize, name: String) -> Bool {
        let renderer = ImageRenderer(content: view)
        renderer.scale = 1
        guard let size = renderer.nsImage?.size else {
            print("  OVERFLOW  \(name): could not be measured")
            return false
        }
        // Height is the hard constraint: too tall means clipped content. Width is reported but not
        // failed, because rows use lineLimit(1) and are *designed* to truncate long evidence at
        // the tail rather than overflow.
        let heightFits = size.height <= available.height + 0.5
        let slack = available.height - size.height
        print(String(format: "  %@  %-24@ content %4.0f×%4.0f pt   box %4.0f×%4.0f pt   %@%.0f pt",
                     heightFits ? "fits    " : "OVERFLOW", name as NSString,
                     size.width, size.height, available.width, available.height,
                     heightFits ? "spare " : "over by ", abs(slack)))
        return heightFits
    }

    @MainActor
    static func render(_ view: some View, points: CGSize, name: String, into directory: String) {
        let framed = view
            .frame(width: points.width, height: points.height, alignment: .topLeading)
            .background(Color(nsColor: .windowBackgroundColor))

        let renderer = ImageRenderer(content: framed)
        renderer.scale = 2  // Retina, matching real widget rendering

        guard let image = renderer.nsImage,
              let tiff = image.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            print("FAILED to render \(name) — the view did not fit \(Int(points.width))×\(Int(points.height))pt")
            return
        }

        let url = URL(fileURLWithPath: directory).appendingPathComponent("\(name).png")
        do {
            try png.write(to: url)
            print("wrote \(name).png  (\(Int(points.width))×\(Int(points.height))pt)")
        } catch {
            print("FAILED to write \(name): \(error)")
        }
    }
}
