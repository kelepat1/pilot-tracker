//
//  PilotCadetWidget.swift
//  PilotCadetWidget
//
//  Native macOS 14+ desktop widget (systemMedium + systemLarge) for the pilot cadet monitor.
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

/// One programme row. Tapping it opens the application landing page.
struct ProgramRow: View {
    let program: ProgramStatus
    var showsEvidence: Bool = false

    var body: some View {
        Group {
            if let url = program.applicationLink {
                Link(destination: url) { content }
                    .buttonStyle(.plain)
                    .help("Open \(program.airline) – \(program.program)")
            } else {
                content
            }
        }
    }

    private var content: some View {
        HStack(alignment: .center, spacing: 7) {
            Circle()
                .fill(program.status.tint)
                .frame(width: 6, height: 6)

            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 4) {
                    Text(program.airline)
                        .font(.system(size: 11.5, weight: .semibold))
                        .lineLimit(1)
                    if program.isStale {
                        Image(systemName: "wifi.exclamationmark")
                            .font(.system(size: 8, weight: .semibold))
                            .foregroundStyle(ProgramState.error.tint)
                            .help("Last check failed – showing the last known status")
                    }
                }
                if showsEvidence, let evidence = program.evidence, !evidence.isEmpty {
                    Text(evidence)
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                } else {
                    Text(program.program)
                        .font(.system(size: 9.5))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
            }

            Spacer(minLength: 4)

            PassportPill(text: program.passportBadge, compact: !showsEvidence)
            StatusPill(state: program.status, compact: !showsEvidence)
        }
        .contentShape(Rectangle())
    }
}

// MARK: - Loaded state

struct PilotCadetContentView: View {
    let document: StatusDocument
    let error: String?
    let isFromCache: Bool
    let family: WidgetFamily

    private var rowLimit: Int { family == .systemLarge ? 7 : 4 }
    private var showsEvidence: Bool { family == .systemLarge }

    private var programs: [ProgramStatus] { document.displayPrograms }

    private var summary: StatusSummary {
        document.summary ?? StatusSummary.compute(from: document.programs)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().opacity(0.35)

            VStack(alignment: .leading, spacing: family == .systemLarge ? 6 : 4) {
                ForEach(programs.prefix(rowLimit)) { program in
                    ProgramRow(program: program, showsEvidence: showsEvidence)
                }
                if programs.count > rowLimit {
                    Text("+\(programs.count - rowLimit) more programmes")
                        .font(.system(size: 9.5, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.top, 5)

            Spacer(minLength: 0)
            footer
        }
    }

    private var header: some View {
        HStack(spacing: 6) {
            Image(systemName: "airplane.departure")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.tint)

            Text("Pilot Cadet Watch")
                .font(.system(size: 12.5, weight: .bold))
                .lineLimit(1)

            Spacer(minLength: 4)

            if summary.open > 0 {
                HStack(spacing: 3) {
                    Circle().fill(ProgramState.open.tint).frame(width: 5, height: 5)
                    Text("\(summary.open) open")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(ProgramState.open.tint)
                }
            } else if summary.interest > 0 {
                HStack(spacing: 3) {
                    Circle().fill(ProgramState.interest.tint).frame(width: 5, height: 5)
                    Text("\(summary.interest) interest")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(ProgramState.interest.tint)
                }
            } else {
                Text("all closed")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.bottom, 5)
    }

    private var footer: some View {
        HStack(spacing: 4) {
            if let error {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 8))
                    .foregroundStyle(ProgramState.error.tint)
                Text(isFromCache ? "Offline – last saved feed" : "Feed error")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(ProgramState.error.tint)
                Text("· \(error)")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            } else {
                Text(lastCheckedText)
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            Text("daily · 08:00 UTC")
                .font(.system(size: 9))
                .foregroundStyle(.quaternary)
        }
        .padding(.top, 4)
    }

    private var lastCheckedText: String {
        guard let generated = document.generatedDate else { return "Awaiting first cloud check" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return "Checked \(formatter.localizedString(for: generated, relativeTo: Date()))"
    }
}

// MARK: - Empty / error state

struct PilotCadetEmptyView: View {
    let message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "airplane.departure")
                    .font(.system(size: 12, weight: .semibold))
                Text("Pilot Cadet Watch")
                    .font(.system(size: 12.5, weight: .bold))
                Spacer(minLength: 0)
            }
            Spacer(minLength: 0)
            Text("No status feed yet")
                .font(.system(size: 11.5, weight: .semibold))
            // Show which endpoint failed: without it a 404 is impossible to diagnose from the
            // desktop, and the widget's URL is compiled in rather than editable in the app.
            Text(WidgetConfig.statusURL.absoluteString)
                .font(.system(size: 9))
                .foregroundStyle(.tertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            Text(message ?? "Set the status.json URL in the Pilot Cadet app, then refresh the widget.")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .lineLimit(3)
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Widget entry view

struct PilotCadetWidgetView: View {
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
        .supportedFamilies([.systemMedium, .systemLarge])
    }
}

@main
struct PilotCadetWidgetBundle: WidgetBundle {
    var body: some Widget {
        PilotCadetWidget()
    }
}

// MARK: - Sample data (placeholder + gallery preview)

extension StatusDocument {
    /// Representative document used for the widget placeholder, gallery preview and the
    /// "no network yet" snapshot path. Deliberately close to real published data.
    static var sample: StatusDocument {
        let programs: [ProgramStatus] = [
            ProgramStatus(
                id: "ba-speedbird",
                airline: "British Airways",
                program: "Speedbird Pilot Academy",
                passport: "UK",
                passportLabel: "🇬🇧 UK",
                rtwScope: "UK Right to Work",
                status: .interest,
                evidence: "Register your interest and we will contact you as soon as the next application window opens."
            ),
            ProgramStatus(
                id: "jet2-flightpath",
                airline: "Jet2.com",
                program: "Jet2FlightPath Scheme",
                passport: "UK",
                passportLabel: "🇬🇧 UK",
                rtwScope: "UK Right to Work",
                status: .closed,
                evidence: "Applications for the current Jet2FlightPath intake are closed."
            ),
            ProgramStatus(
                id: "tui-mpl",
                airline: "TUI Airways",
                program: "MPL Cadet Programme",
                passport: "UK",
                passportLabel: "🇬🇧 UK",
                rtwScope: "UK Right to Work",
                status: .interest,
                evidence: "Applications are now closed — register your interest for the next intake."
            ),
            ProgramStatus(
                id: "aerlingus-future-pilot",
                airline: "Aer Lingus",
                program: "Future Pilot Programme",
                passport: "EU",
                passportLabel: "🇪🇺 EU",
                rtwScope: "EU/EEA Right to Work",
                status: .closed,
                evidence: "Applications for the Future Pilot Programme are currently closed."
            ),
            ProgramStatus(
                id: "airfrance-cadets",
                airline: "Air France",
                program: "Cadets Air France",
                passport: "EU",
                passportLabel: "🇪🇺 EU",
                rtwScope: "EU/EEA Right to Work",
                status: .open,
                evidence: "Les candidatures pour la promotion sont ouvertes jusqu'au 15 avril."
            ),
            ProgramStatus(
                id: "wizzair-pilot-academy",
                airline: "Wizz Air",
                program: "Wizz Air Pilot Academy",
                passport: "EU",
                passportLabel: "🇪🇺 EU",
                rtwScope: "EU/EEA Right to Work",
                status: .closed,
                evidence: "No current cadet pilot vacancies in the pilot academy search."
            ),
            ProgramStatus(
                id: "cathay-cadet",
                airline: "Cathay Pacific",
                program: "Cadet Pilot Programme",
                passport: "Global",
                passportLabel: "🌍 Global",
                rtwScope: "International / Targeted RTW",
                status: .closed,
                evidence: "The Cadet Pilot Programme is not currently open for applications."
            )
        ]
        return StatusDocument(
            schemaVersion: 1,
            generatedAt: StatusDocument.parseTimestamp("2026-02-12T08:00:00Z").map {
                ISO8601DateFormatter().string(from: $0)
            },
            summary: StatusSummary.compute(from: programs),
            programs: programs
        )
    }
}
