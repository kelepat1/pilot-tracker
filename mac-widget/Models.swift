//
//  Models.swift
//  PilotCadetWidget
//
//  Decodable structures mirroring the schema published by scraper/monitor.py in status.json.
//
//  Decoding rules that matter in practice:
//   * An unrecognised `status` string must never fail the whole decode. A future monitor
//     release that adds a state (or a typo in a hand-edited file) degrades that one row to
//     `.unknown` instead of blanking the widget.
//   * `generated_at` is parsed leniently: the monitor writes second-precision ISO-8601, but
//     fractional seconds and `+00:00` offsets are tolerated too.
//   * Every field except `programs` is optional, so a partially written file still renders.
//

import Foundation
import SwiftUI

// MARK: - Status

/// The five states the widget can render. Three are the product contract
/// (`OPEN` / `INTEREST` / `CLOSED`); `UNKNOWN` and `ERROR` exist so a broken scraper is
/// visible on the desktop instead of masquerading as a closed application window.
enum ProgramState: String, Codable, CaseIterable {
    case open = "OPEN"
    case interest = "INTEREST"
    case closed = "CLOSED"
    case unknown = "UNKNOWN"
    case error = "ERROR"

    /// Tolerant decoding: anything unrecognised becomes `.unknown`.
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ProgramState(rawValue: raw.uppercased()) ?? .unknown
    }

    var label: String {
        switch self {
        case .open: return "OPEN"
        case .interest: return "INTEREST"
        case .closed: return "CLOSED"
        case .unknown: return "UNKNOWN"
        case .error: return "ERROR"
        }
    }

    /// Green / orange / neutral gray, per the interface contract.
    var tint: Color {
        switch self {
        case .open: return Color(red: 0.10, green: 0.65, blue: 0.28)
        case .interest: return Color(red: 0.85, green: 0.50, blue: 0.05)
        case .closed: return Color(red: 0.55, green: 0.56, blue: 0.58)
        case .unknown: return Color(red: 0.45, green: 0.47, blue: 0.50)
        case .error: return Color(red: 0.72, green: 0.25, blue: 0.22)
        }
    }

    /// Widget ordering: actionable states float to the top.
    var displayRank: Int {
        switch self {
        case .open: return 0
        case .interest: return 1
        case .unknown: return 2
        case .error: return 3
        case .closed: return 4
        }
    }

    var isActionable: Bool { self == .open || self == .interest }

    var symbolName: String {
        switch self {
        case .open: return "checkmark.circle.fill"
        case .interest: return "bell.badge.fill"
        case .closed: return "moon.zzz.fill"
        case .unknown: return "questionmark.circle.fill"
        case .error: return "exclamationmark.triangle.fill"
        }
    }
}

// MARK: - Passport tag

/// Right-to-work tagging. The monitor sends a ready-made label (`🇬🇧 UK`, `🇪🇺 EU`,
/// `🌍 Global`); these helpers only exist so the widget can still render sensibly when the
/// label is missing.
enum PassportTag: String, Codable {
    case uk = "UK"
    case eu = "EU"
    case global = "Global"

    var defaultLabel: String {
        switch self {
        case .uk: return "🇬🇧 UK"
        case .eu: return "🇪🇺 EU"
        case .global: return "🌍 Global"
        }
    }

    /// Best-effort mapping from the free-form `passport` string in status.json.
    static func infer(from raw: String?) -> PassportTag? {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else { return nil }
        let needle = raw.uppercased()
        if needle.contains("UK") || needle.contains("GB") { return .uk }
        if needle.contains("EU") || needle.contains("EEA") { return .eu }
        if needle.contains("GLOBAL") || needle.contains("INTERNATIONAL") { return .global }
        return nil
    }
}

// MARK: - status.json

/// One programme row inside `status.json`.
struct ProgramStatus: Decodable, Identifiable, Hashable {
    let id: String
    let airline: String
    let program: String
    let passport: String?
    let passportLabel: String?
    let rtwScope: String?
    let status: ProgramState
    let previousStatus: String?
    let statusChanged: Bool
    let changedAt: String?
    let checkedAt: String?
    let contentChanged: Bool
    let applyUrl: String?
    let sourceUrl: String?
    let evidence: String?
    let consecutiveFailures: Int
    let error: String?

    enum CodingKeys: String, CodingKey {
        case id
        case airline
        case program
        case passport
        case passportLabel = "passport_label"
        case rtwScope = "rtw_scope"
        case status
        case previousStatus = "previous_status"
        case statusChanged = "status_changed"
        case changedAt = "changed_at"
        case checkedAt = "checked_at"
        case contentChanged = "content_changed"
        case applyUrl = "apply_url"
        case sourceUrl = "source_url"
        case evidence
        case consecutiveFailures = "consecutive_failures"
        case error
    }

    /// Memberwise initialiser, used by the widget's placeholder/sample timelines. Declaring
    /// `init(from:)` suppresses the synthesised one, so it is spelled out here.
    init(
        id: String,
        airline: String,
        program: String,
        passport: String? = nil,
        passportLabel: String? = nil,
        rtwScope: String? = nil,
        status: ProgramState,
        previousStatus: String? = nil,
        statusChanged: Bool = false,
        changedAt: String? = nil,
        checkedAt: String? = nil,
        contentChanged: Bool = false,
        applyUrl: String? = nil,
        sourceUrl: String? = nil,
        evidence: String? = nil,
        consecutiveFailures: Int = 0,
        error: String? = nil
    ) {
        self.id = id
        self.airline = airline
        self.program = program
        self.passport = passport
        self.passportLabel = passportLabel
        self.rtwScope = rtwScope
        self.status = status
        self.previousStatus = previousStatus
        self.statusChanged = statusChanged
        self.changedAt = changedAt
        self.checkedAt = checkedAt
        self.contentChanged = contentChanged
        self.applyUrl = applyUrl
        self.sourceUrl = sourceUrl
        self.evidence = evidence
        self.consecutiveFailures = consecutiveFailures
        self.error = error
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // `id` is the only genuinely required field; fall back to airline+program otherwise.
        let airline = (try? container.decode(String.self, forKey: .airline)) ?? "Unknown airline"
        let program = (try? container.decode(String.self, forKey: .program)) ?? ""
        self.airline = airline
        self.program = program
        self.id = (try? container.decode(String.self, forKey: .id)) ?? "\(airline)-\(program)"
        self.passport = try? container.decodeIfPresent(String.self, forKey: .passport)
        self.passportLabel = try? container.decodeIfPresent(String.self, forKey: .passportLabel)
        self.rtwScope = try? container.decodeIfPresent(String.self, forKey: .rtwScope)
        self.status = (try? container.decode(ProgramState.self, forKey: .status)) ?? .unknown
        self.previousStatus = try? container.decodeIfPresent(String.self, forKey: .previousStatus)
        self.statusChanged = (try? container.decode(Bool.self, forKey: .statusChanged)) ?? false
        self.changedAt = try? container.decodeIfPresent(String.self, forKey: .changedAt)
        self.checkedAt = try? container.decodeIfPresent(String.self, forKey: .checkedAt)
        self.contentChanged = (try? container.decode(Bool.self, forKey: .contentChanged)) ?? false
        self.applyUrl = try? container.decodeIfPresent(String.self, forKey: .applyUrl)
        self.sourceUrl = try? container.decodeIfPresent(String.self, forKey: .sourceUrl)
        self.evidence = try? container.decodeIfPresent(String.self, forKey: .evidence)
        self.consecutiveFailures = (try? container.decode(Int.self, forKey: .consecutiveFailures)) ?? 0
        self.error = try? container.decodeIfPresent(String.self, forKey: .error)
    }

    // MARK: Derived display values

    /// The exact page a candidate should open. `apply_url` wins; `source_url` is the fallback.
    var applicationLink: URL? {
        for candidate in [applyUrl, sourceUrl] {
            if let candidate, let url = URL(string: candidate), url.scheme?.hasPrefix("http") == true {
                return url
            }
        }
        return nil
    }

    /// Passport pill text: monitor label first, then inference, then a neutral globe.
    var passportBadge: String {
        if let label = passportLabel, !label.isEmpty { return label }
        if let tag = PassportTag.infer(from: passport) { return tag.defaultLabel }
        if let passport, !passport.isEmpty { return "🌍 \(passport)" }
        return "🌍 Global"
    }

    var isStale: Bool { consecutiveFailures > 0 }

    /// Compact right-to-work text used in the medium widget.
    var scopeShort: String {
        guard let rtwScope, !rtwScope.isEmpty else { return passportBadge }
        return rtwScope
            .replacingOccurrences(of: "Right to Work", with: "RTW")
            .replacingOccurrences(of: "right to work", with: "RTW")
    }

    static func == (lhs: ProgramStatus, rhs: ProgramStatus) -> Bool {
        lhs.id == rhs.id && lhs.status == rhs.status && lhs.evidence == rhs.evidence
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
        hasher.combine(status)
    }
}

/// The whole published document.
struct StatusDocument: Decodable {
    let schemaVersion: Int?
    let generatedAt: String?
    let summary: StatusSummary?
    let programs: [ProgramStatus]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case summary
        case programs
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.schemaVersion = try? container.decodeIfPresent(Int.self, forKey: .schemaVersion)
        self.generatedAt = try? container.decodeIfPresent(String.self, forKey: .generatedAt)
        self.summary = try? container.decodeIfPresent(StatusSummary.self, forKey: .summary)
        self.programs = (try? container.decode([ProgramStatus].self, forKey: .programs)) ?? []
    }

    /// Convenience initialiser used by the widget's placeholder and preview paths.
    init(schemaVersion: Int?, generatedAt: String?, summary: StatusSummary?, programs: [ProgramStatus]) {
        self.schemaVersion = schemaVersion
        self.generatedAt = generatedAt
        self.summary = summary
        self.programs = programs
    }

    var generatedDate: Date? { StatusDocument.parseTimestamp(generatedAt) }

    /// Programmes sorted for display: OPEN, INTEREST, UNKNOWN, ERROR, then CLOSED; ties broken
    /// by the order the monitor published (which follows the catalogue).
    var displayPrograms: [ProgramStatus] {
        programs.enumerated()
            .sorted { lhs, rhs in
                if lhs.element.status.displayRank != rhs.element.status.displayRank {
                    return lhs.element.status.displayRank < rhs.element.status.displayRank
                }
                return lhs.offset < rhs.offset
            }
            .map(\.element)
    }

    var openPrograms: [ProgramStatus] { programs.filter { $0.status == .open } }
    var actionablePrograms: [ProgramStatus] { programs.filter { $0.status.isActionable } }

    /// Lenient ISO-8601 parsing (with and without fractional seconds, `Z` or numeric offset).
    static func parseTimestamp(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = withFraction.date(from: raw) { return date }

        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let date = plain.date(from: raw) { return date }

        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd"] {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone(identifier: "UTC")
            formatter.dateFormat = format
            if let date = formatter.date(from: raw) { return date }
        }
        return nil
    }
}

/// Aggregate counters written by the monitor. Optional everywhere: the widget recomputes
/// them from `programs` when absent so the header is never wrong.
struct StatusSummary: Decodable {
    let open: Int
    let interest: Int
    let closed: Int
    let unknown: Int
    let error: Int

    enum CodingKeys: String, CodingKey {
        case open, interest, closed, unknown, error
    }

    init(open: Int, interest: Int, closed: Int, unknown: Int, error: Int) {
        self.open = open
        self.interest = interest
        self.closed = closed
        self.unknown = unknown
        self.error = error
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.open = (try? container.decode(Int.self, forKey: .open)) ?? 0
        self.interest = (try? container.decode(Int.self, forKey: .interest)) ?? 0
        self.closed = (try? container.decode(Int.self, forKey: .closed)) ?? 0
        self.unknown = (try? container.decode(Int.self, forKey: .unknown)) ?? 0
        self.error = (try? container.decode(Int.self, forKey: .error)) ?? 0
    }

    static func compute(from programs: [ProgramStatus]) -> StatusSummary {
        StatusSummary(
            open: programs.filter { $0.status == .open }.count,
            interest: programs.filter { $0.status == .interest }.count,
            closed: programs.filter { $0.status == .closed }.count,
            unknown: programs.filter { $0.status == .unknown }.count,
            error: programs.filter { $0.status == .error }.count
        )
    }
}
