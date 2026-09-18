//
//  PilotCadetWidget.swift
//  PilotCadetWidget
//
//  Native macOS 14+ desktop widget (small, medium, large and extra-large) for the pilot cadet
//  monitor. The layouts themselves live in WidgetContentViews.swift.
//
//  Data flow
//  ---------
//  GitHub Actions commits status.json daily at 08:00 UTC → the widget fetches it with
//  URLSession → decodes StatusDocument → renders one row per programme. The timeline asks for
//  a refresh just after 08:10 UTC, and retries every 30 minutes if the fetch fails. The last
//  successful payload is cached in the shared App Group, so a failed refresh shows stale data
//  with a warning rather than an empty widget.
//
//  Interaction
//  -----------
//  Every row is a `Link` to that programme's application landing page, so clicking a row opens
//  the exact portal page in the default browser. The whole widget also carries a `widgetURL`
//  pointing at the highest-priority row (first OPEN, else first INTEREST), which is what makes
//  a large tap target work.
//

import SwiftUI
import WidgetKit

// MARK: - Timeline entry

struct PilotStatusEntry: TimelineEntry {
    let date: Date
    let document: StatusDocument?
    let error: String?
    let isFromCache: Bool

    /// Highest-priority deep link for the whole-widget tap target.
    var primaryLink: URL? {
        guard let document else { return nil }
        let ordered = document.displayPrograms
        let actionable = ordered.first { $0.status.isActionable }
        return (actionable ?? ordered.first)?.applicationLink
    }

    var isStale: Bool { isFromCache || (document?.programs.contains(where: \.isStale) ?? false) }
}

// MARK: - Provider

struct PilotStatusProvider: TimelineProvider {

    func placeholder(in context: Context) -> PilotStatusEntry {
        PilotStatusEntry(date: Date(), document: .sample, error: nil, isFromCache: false)
    }

    func getSnapshot(in context: Context, completion: @escaping (PilotStatusEntry) -> Void) {
        // The gallery and the "add widget" preview must render instantly: never block on network.
        if context.isPreview {
            completion(PilotStatusEntry(date: Date(), document: .sample, error: nil, isFromCache: false))
            return
        }
        let cached = StatusLoader.snapshot()
        completion(
            PilotStatusEntry(
                date: Date(),
                document: cached.document ?? .sample,
                error: cached.error,
                isFromCache: cached.isFromCache
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<PilotStatusEntry>) -> Void) {
        Task {
            let result = await StatusLoader.load()
            let entry = PilotStatusEntry(
                date: Date(),
                document: result.document,
                error: result.error,
                isFromCache: result.isFromCache
            )

            // Normal cadence: just after the next 08:00 UTC cloud run.
            // Failure cadence: come back in 30 minutes instead of losing a whole day.
            let next = result.succeeded
                ? WidgetConfig.nextScheduledRefresh()
                : Date().addingTimeInterval(WidgetConfig.failureRetryInterval)

            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }
}

// MARK: - Small building blocks

// MARK: - Widget entry view

struct PilotCadetWidgetView: View {
    /// The margin this widget keeps for itself, in points (WidgetKit's default is disabled).
    ///
    /// These are the values the offscreen layout checks in `preview/` measure against, so the
    /// numbers in that report are exactly what the desktop gets:
    ///
    ///     systemSmall       170×170   margin 12  -> usable 146×146, content 106×106
    ///     systemMedium      364×170   margin 14  -> usable 336×142, content 259×127
    ///     systemLarge       364×382   margin 14  -> usable 336×354, content 564×252
    ///     systemExtraLarge  776×382   margin 14  -> usable 748×354, content 1042×261
    static func contentMargin(for family: WidgetFamily) -> CGFloat {
        family == .systemSmall ? 12 : 14
    }

    @Environment(\.widgetFamily) private var family
    let entry: PilotStatusEntry

    var body: some View {
        Group {
            if let document = entry.document, !document.programs.isEmpty {
                PilotCadetContentView(
                    document: document,
                    error: entry.error,
                    isFromCache: entry.isFromCache,
                    family: family
                )
            } else {
                PilotCadetEmptyView(message: entry.error)
            }
        }
        .padding(Self.contentMargin(for: family))
        .containerBackground(for: .widget) {
            LinearGradient(
                colors: [
                    Color(nsColor: .windowBackgroundColor),
                    ProgramState.open.tint.opacity(entry.document?.openPrograms.isEmpty == false ? 0.10 : 0.0)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
        .widgetURL(entry.primaryLink)
    }
}

// MARK: - Widget declaration

struct PilotCadetWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: WidgetConfig.widgetKind, provider: PilotStatusProvider()) { entry in
            PilotCadetWidgetView(entry: entry)
        }
        .configurationDisplayName("Pilot Cadet Watch")
        .description("Daily application status for fully funded pilot cadet programmes, tagged by right to work.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge, .systemExtraLarge])
        // Apply our own content margin instead of WidgetKit's default, so the space each layout
        // has is a number we choose and can verify offscreen (see preview/). WidgetKit's margin
        // varies by family, and guessing it is how a layout ends up clipped on the desktop.
        .contentMarginsDisabled()
    }
}

@main
struct PilotCadetWidgetBundle: WidgetBundle {
    var body: some Widget {
        PilotCadetWidget()
    }
}
