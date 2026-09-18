//
//  WidgetContentViews.swift
//  PilotCadetWidget
//
//  The widget's entire view layer, deliberately free of any `@main` entry point so the layouts
//  can be rendered offscreen at each widget size and inspected (see mac-widget/preview/).
//
//  Size strategy — one data model, four layouts:
//
//    systemSmall      170×170   the actionable programmes only: a summary line plus up to three
//                               compact rows (status dot, airline, passport flag). No status
//                               pill and no programme name: at this size they would truncate
//                               rather than inform.
//    systemMedium     364×170   four rows with airline, programme, passport pill and status pill.
//    systemLarge      364×382   all seven rows, each with the evidence wording that decided the
//                               status.
//    systemExtraLarge 776×382   the same richness as large, in two columns, because seven rows in
//                               a 776pt-wide box would leave a lot of empty space.
//
//  Every text element is line-limited and allowed to shrink (`minimumScaleFactor`) so a long
//  airline or programme name degrades gracefully instead of clipping.
//

import SwiftUI
import WidgetKit

// MARK: - Small pieces

/// The coloured state dot used by the compact layouts.
struct StatusDot: View {
    let state: ProgramState
    var size: CGFloat = 6

    var body: some View {
        Circle()
            .fill(state.tint)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

/// A one-line row for `systemSmall`: dot, airline, passport flag.
struct CompactRow: View {
    let program: ProgramStatus

    private var flag: String {
        // Only the emoji survives at this size; the country code would push the airline name out.
        String(program.passportBadge.prefix(while: { !$0.isLetter && !$0.isNumber }))
            .trimmingCharacters(in: .whitespaces)
    }

    var body: some View {
        HStack(spacing: 5) {
            StatusDot(state: program.status, size: 5)
            Text(program.airline)
                .font(.system(size: 9.5, weight: program.status.isActionable ? .semibold : .regular))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Spacer(minLength: 2)
            if !flag.isEmpty {
                Text(flag).font(.system(size: 8))
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(program.airline), \(program.status.label), \(program.passportBadge)")
    }
}

/// How much detail a row shows. Driven by the measured height each family actually has:
///
///   .programme  medium  - two lines (airline, programme); evidence does not fit
///   .evidence   large   - two lines, the second being the wording that decided the status
///   .full       xlarge  - three lines, because a 776pt-wide, 382pt-tall box has room to spare
enum RowDetail {
    case programme
    case evidence
    case full
}

/// The row used by `systemMedium` upwards.
struct ProgramRow: View {
    let program: ProgramStatus
    var detail: RowDetail = .programme
    var compact: Bool = false

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
            StatusDot(state: program.status)

            VStack(alignment: .leading, spacing: detail == .full ? 1 : 0) {
                HStack(spacing: 4) {
                    Text(program.airline)
                        .font(.system(size: compact ? 11 : 11.5, weight: .semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                    if program.isStale {
                        Image(systemName: "wifi.exclamationmark")
                            .font(.system(size: 8, weight: .semibold))
                            .foregroundStyle(ProgramState.error.tint)
                            .help("Last check failed – showing the last known status")
                    }
                }

                switch detail {
                case .programme:
                    Text(program.program)
                        .font(.system(size: 9.5))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)

                case .evidence:
                    Text(program.evidence ?? program.program)
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)

                case .full:
                    Text(program.program)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Text(program.evidence ?? program.scopeShort)
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
            }

            Spacer(minLength: 4)

            PassportPill(text: program.passportBadge, compact: compact)
            StatusPill(state: program.status, compact: compact)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(program.airline), \(program.program), \(program.status.label), \(program.passportBadge)"
        )
    }
}

// MARK: - Header and footer

struct WidgetHeader: View {
    let summary: StatusSummary
    var compact: Bool = false

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "airplane.departure")
                .font(.system(size: compact ? 11 : 12, weight: .semibold))
                .foregroundStyle(.tint)

            Text(compact ? "Cadets" : "Pilot Cadet Watch")
                .font(.system(size: compact ? 11.5 : 12.5, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.8)

            Spacer(minLength: 4)

            headline
        }
        .padding(.bottom, 5)
    }

    @ViewBuilder
    private var headline: some View {
        if summary.open > 0 {
            HStack(spacing: 3) {
                Circle().fill(ProgramState.open.tint).frame(width: 5, height: 5)
                Text("\(summary.open) open")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(ProgramState.open.tint)
            }
            .fixedSize()
        } else if summary.interest > 0 {
            HStack(spacing: 3) {
                Circle().fill(ProgramState.interest.tint).frame(width: 5, height: 5)
                Text("\(summary.interest) interest")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(ProgramState.interest.tint)
            }
            .fixedSize()
        } else {
            Text("all closed")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.secondary)
                .fixedSize()
        }
    }
}

struct WidgetFooter: View {
    let document: StatusDocument
    let error: String?
    let isFromCache: Bool

    var body: some View {
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
                .fixedSize()
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

// MARK: - Layouts

/// `systemSmall`: a count, then the programmes that need attention.
struct SmallWidgetLayout: View {
    let document: StatusDocument
    let summary: StatusSummary

    private var actionable: [ProgramStatus] {
        let ordered = document.displayPrograms
        let needingAction = ordered.filter { $0.status.isActionable }
        return Array((needingAction.isEmpty ? ordered : needingAction).prefix(3))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 4) {
                Image(systemName: "airplane.departure")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.tint)
                Text("Cadets")
                    .font(.system(size: 10.5, weight: .bold))
                    .lineLimit(1)
                Spacer(minLength: 0)
            }

            // The headline number is the whole point of the small size.
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text("\(summary.open)")
                    .font(.system(size: 30, weight: .heavy, design: .rounded))
                    .foregroundStyle(summary.open > 0 ? ProgramState.open.tint : .primary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(summary.open == 1 ? "open" : "open")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .padding(.top, 1)

            Text(secondaryCounts)
                .font(.system(size: 9))
                .foregroundStyle(.tertiary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)

            Spacer(minLength: 4)

            VStack(alignment: .leading, spacing: 3) {
                ForEach(actionable) { program in
                    CompactRow(program: program)
                }
            }

            Spacer(minLength: 0)
        }
    }

    private var secondaryCounts: String {
        var parts: [String] = []
        if summary.interest > 0 { parts.append("\(summary.interest) interest") }
        if summary.closed > 0 { parts.append("\(summary.closed) closed") }
        if summary.unknown + summary.error > 0 { parts.append("\(summary.unknown + summary.error) unknown") }
        return parts.isEmpty ? "nothing actionable" : parts.joined(separator: " · ")
    }
}

/// `systemMedium`, `systemLarge`: a single column, capped to what the measured height allows.
struct SingleColumnLayout: View {
    let programs: [ProgramStatus]
    let rowLimit: Int
    let detail: RowDetail
    let compact: Bool
    /// medium has no vertical room for an overflow line, so it is limited to large and above.
    let showsOverflowNote: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: detail == .programme ? 4 : 6) {
            ForEach(programs.prefix(rowLimit)) { program in
                ProgramRow(program: program, detail: detail, compact: compact)
            }
            if showsOverflowNote, programs.count > rowLimit {
                Text("+\(programs.count - rowLimit) more programmes")
                    .font(.system(size: 9.5, weight: .medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.top, 5)
    }
}

/// `systemExtraLarge`: two columns, plus a count strip, because a single column of seven rows in a
/// 776pt-wide box leaves most of the area empty.
struct TwoColumnLayout: View {
    let programs: [ProgramStatus]
    let summary: StatusSummary

    private var split: (left: [ProgramStatus], right: [ProgramStatus]) {
        let half = Int(ceil(Double(programs.count) / 2.0))
        return (Array(programs.prefix(half)), Array(programs.dropFirst(half)))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            CountStrip(summary: summary)
                .padding(.bottom, 8)

            HStack(alignment: .top, spacing: 24) {
                column(split.left)
                column(split.right)
            }

            Spacer(minLength: 0)
        }
        .padding(.top, 5)
    }

    private func column(_ items: [ProgramStatus]) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(items) { program in
                ProgramRow(program: program, detail: .full)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A row of labelled counts, used by the extra-large layout where there is room for it.
struct CountStrip: View {
    let summary: StatusSummary

    private var items: [(String, Int, Color)] {
        [
            ("open", summary.open, ProgramState.open.tint),
            ("interest", summary.interest, ProgramState.interest.tint),
            ("closed", summary.closed, ProgramState.closed.tint),
            ("unknown", summary.unknown + summary.error, ProgramState.unknown.tint),
        ]
    }

    var body: some View {
        HStack(spacing: 18) {
            ForEach(items, id: \.0) { label, count, tint in
                HStack(spacing: 5) {
                    Circle().fill(tint).frame(width: 7, height: 7)
                    Text("\(count)")
                        .font(.system(size: 13, weight: .bold, design: .rounded))
                        .foregroundStyle(count > 0 && label == "open" ? tint : .primary)
                    Text(label)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
                .fixedSize()
            }
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Root content view

struct PilotCadetContentView: View {
    let document: StatusDocument
    let error: String?
    let isFromCache: Bool
    let family: WidgetFamily

    private var programs: [ProgramStatus] { document.displayPrograms }

    private var summary: StatusSummary {
        document.summary ?? StatusSummary.compute(from: document.programs)
    }

    var body: some View {
        switch family {
        case .systemSmall:
            // 170×170: only the actionable programmes, and no room for a status pill.
            SmallWidgetLayout(document: document, summary: summary)

        case .systemExtraLarge:
            // 776×382: height to spare, so rows carry programme *and* evidence, in two columns.
            VStack(alignment: .leading, spacing: 0) {
                WidgetHeader(summary: summary)
                Divider().opacity(0.35)
                TwoColumnLayout(programs: programs, summary: summary)
                WidgetFooter(document: document, error: error, isFromCache: isFromCache)
            }

        case .systemLarge:
            // 364×382: fits all seven rows with the deciding wording.
            VStack(alignment: .leading, spacing: 0) {
                WidgetHeader(summary: summary)
                Divider().opacity(0.35)
                SingleColumnLayout(programs: programs, rowLimit: 7, detail: .evidence,
                                   compact: false, showsOverflowNote: false)
                Spacer(minLength: 0)
                WidgetFooter(document: document, error: error, isFromCache: isFromCache)
            }

        default:  // .systemMedium — 364×170
            // Three two-line rows, not four: four overflowed 170pt by ~27pt once WidgetKit's own
            // content margins are accounted for (measured, see preview/). The three shown are the
            // most actionable, because displayPrograms sorts OPEN and INTEREST first.
            VStack(alignment: .leading, spacing: 0) {
                WidgetHeader(summary: summary)
                Divider().opacity(0.35)
                SingleColumnLayout(programs: programs, rowLimit: 3, detail: .programme,
                                   compact: true, showsOverflowNote: false)
                Spacer(minLength: 0)
                WidgetFooter(document: document, error: error, isFromCache: isFromCache)
            }
        }
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
            Text(message ?? "Set the status.json URL in the Pilot Cadet app, then refresh the widget.")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .lineLimit(3)
            // Show which endpoint failed: without it a 404 is impossible to diagnose from the
            // desktop, and the widget's URL is compiled in rather than editable in the app.
            Text(WidgetConfig.statusURL.absoluteString)
                .font(.system(size: 9))
                .foregroundStyle(.tertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Sample data (placeholder, gallery preview, offscreen layout checks)

extension StatusDocument {
    /// Representative document used for the widget placeholder, the gallery preview, the
    /// "no network yet" snapshot path, and the offscreen layout renders in `preview/`.
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
