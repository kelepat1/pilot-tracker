//
//  WidgetConfig.swift
//  PilotCadetWidget
//
//  Endpoint configuration, shared-cache plumbing and the daily refresh schedule.
//
//  ⚠️ TWO THINGS TO EDIT AFTER CREATING THE XCODE PROJECT
//  1. `appGroupIdentifier` must match the App Group you enable on BOTH the app target and
//     the widget extension target (Signing & Capabilities → App Groups). It is used for the
//     last-known-good cache so the widget still shows data when a fetch fails.
//  2. `defaultStatusURL` must point at your published status.json (GitHub Pages or raw).
//     You can also change it at runtime from the host app, which writes the value into the
//     shared defaults under `statusEndpointURL`.
//

import Foundation

enum WidgetConfig {

    // MARK: - Identifiers

    /// App Group shared by the host app and the widget extension.
    static let appGroupIdentifier = "group.com.example.pilotcadet"

    static let widgetKind = "PilotCadetStatusWidget"

    // MARK: - Endpoint

    /// Replace with your own Pages URL, e.g.
    /// `https://<username>.github.io/pilot-tracker/status.json`
    /// or `https://raw.githubusercontent.com/<username>/pilot-tracker/main/status.json`.
    static let defaultStatusURL = URL(string: "https://kelepat1.github.io/pilot-tracker/status.json")!

    static let endpointDefaultsKey = "statusEndpointURL"

    /// Cache keys for the last successful document.
    static let cacheDocumentKey = "cachedStatusDocument"
    static let cacheDateKey = "cachedStatusDocumentDate"

    // MARK: - Refresh policy

    /// The GitHub Actions cron runs at 08:00 UTC, so refresh shortly after that.
    static let refreshHourUTC = 8
    static let refreshMinuteUTC = 10

    /// Retry sooner when the fetch failed, instead of waiting a whole day.
    static let failureRetryInterval: TimeInterval = 30 * 60

    static let requestTimeout: TimeInterval = 20

    // MARK: - Shared defaults

    /// True when the shared App Group container is genuinely available.
    ///
    /// It is **not** by default: App Groups is disabled in both `.entitlements` files so that a
    /// free ("personal team") Apple ID can sign the project at all. When this is false the
    /// widget can only use the endpoint compiled into `defaultStatusURL`, and the host app's
    /// "Save URL" field cannot reach it — the app says so in its own UI.
    static var isUsingAppGroup: Bool {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier) != nil
    }

    /// Shared defaults when the App Group exists, otherwise this process's own defaults.
    static var sharedDefaults: UserDefaults {
        if isUsingAppGroup, let shared = UserDefaults(suiteName: appGroupIdentifier) {
            return shared
        }
        return .standard
    }

    /// The endpoint actually used: whatever the app last saved, else the built-in default.
    static var statusURL: URL {
        if let raw = sharedDefaults.string(forKey: endpointDefaultsKey),
           let url = URL(string: raw),
           url.scheme?.hasPrefix("http") == true {
            return url
        }
        return defaultStatusURL
    }

    static func setStatusURL(_ url: URL) {
        sharedDefaults.set(url.absoluteString, forKey: endpointDefaultsKey)
    }

    static var isUsingDefaultEndpoint: Bool {
        sharedDefaults.string(forKey: endpointDefaultsKey) == nil
    }

    // MARK: - Schedule helpers

    /// Next 08:10 UTC, i.e. just after the daily cloud check has committed the new status.json.
    static func nextScheduledRefresh(after date: Date = Date()) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? TimeZone(secondsFromGMT: 0)!

        var components = calendar.dateComponents([.year, .month, .day], from: date)
        components.hour = refreshHourUTC
        components.minute = refreshMinuteUTC
        components.second = 0

        guard let today = calendar.date(from: components) else {
            return date.addingTimeInterval(60 * 60)
        }
        if today > date { return today }
        return calendar.date(byAdding: .day, value: 1, to: today) ?? date.addingTimeInterval(60 * 60)
    }
}

// MARK: - Loading

/// Outcome of one widget refresh attempt.
struct StatusLoadResult {
    let document: StatusDocument?
    let isFromCache: Bool
    let error: String?

    var succeeded: Bool { document != nil && error == nil }
}

/// Fetches status.json, caching the last successful document so a network hiccup never
/// replaces real data with an error screen.
enum StatusLoader {

    static func load() async -> StatusLoadResult {
        do {
            let (document, rawData) = try await fetchDocument()
            cache(rawData: rawData)
            return StatusLoadResult(document: document, isFromCache: false, error: nil)
        } catch {
            // Degrade in order of freshness: live feed -> last successful fetch -> snapshot
            // bundled at build time -> error state. A widget that shows yesterday's statuses
            // with a visible warning is far more useful than one that shows nothing, and it is
            // what makes the widget useful before the feed URL has even been published.
            if let cached = cachedDocument() {
                return StatusLoadResult(document: cached, isFromCache: true, error: error.localizedDescription)
            }
            if let bundled = bundledDocument() {
                return StatusLoadResult(document: bundled, isFromCache: true, error: error.localizedDescription)
            }
            return StatusLoadResult(document: nil, isFromCache: false, error: error.localizedDescription)
        }
    }

    /// Fetches and decodes the feed. Returns the raw bytes as well, because the cache stores
    /// the published payload verbatim (the models are decode-only by design).
    static func fetchDocument() async throws -> (StatusDocument, Data) {
        var request = URLRequest(url: WidgetConfig.statusURL)
        request.timeoutInterval = WidgetConfig.requestTimeout
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let (data, response) = try await URLSession.shared.data(for: request)

        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw StatusLoadError.httpStatus(http.statusCode)
        }
        if data.isEmpty {
            throw StatusLoadError.emptyBody
        }

        do {
            let document = try JSONDecoder().decode(StatusDocument.self, from: data)
            return (document, data)
        } catch {
            throw StatusLoadError.decoding(error.localizedDescription)
        }
    }

    // MARK: Cache

    /// Store the last successful payload so a later failure degrades to "stale data" rather
    /// than an empty widget.
    static func cache(rawData: Data) {
        let defaults = WidgetConfig.sharedDefaults
        defaults.set(rawData, forKey: WidgetConfig.cacheDocumentKey)
        defaults.set(Date().timeIntervalSince1970, forKey: WidgetConfig.cacheDateKey)
    }

    /// Snapshot of `status.json` shipped inside the widget bundle (`BundledStatus.json`).
    ///
    /// This is the final fallback before the error state, so a freshly installed widget shows the
    /// seven programmes immediately instead of a blank "no feed yet" panel. The footer labels it
    /// as offline data and the fetch error is shown alongside it.
    static func bundledDocument() -> StatusDocument? {
        let bundles = [Bundle.main, Bundle(for: BundleToken.self)]
        for bundle in bundles {
            if let url = bundle.url(forResource: "BundledStatus", withExtension: "json"),
               let data = try? Data(contentsOf: url),
               let document = try? JSONDecoder().decode(StatusDocument.self, from: data) {
                return document
            }
        }
        return nil
    }

    /// Cached copy of the last successful fetch, if any.
    static func cachedDocument() -> StatusDocument? {
        guard let data = WidgetConfig.sharedDefaults.data(forKey: WidgetConfig.cacheDocumentKey) else { return nil }
        return try? JSONDecoder().decode(StatusDocument.self, from: data)
    }

    static func cacheAge() -> TimeInterval? {
        let stamp = WidgetConfig.sharedDefaults.double(forKey: WidgetConfig.cacheDateKey)
        guard stamp > 0 else { return nil }
        return Date().timeIntervalSince1970 - stamp
    }

    /// Snapshot path: reuse the cache immediately so the gallery and the lock-screen preview
    /// render instantly instead of waiting for the network.
    static func snapshot() -> StatusLoadResult {
        if let cached = cachedDocument() {
            return StatusLoadResult(document: cached, isFromCache: true, error: nil)
        }
        return StatusLoadResult(document: nil, isFromCache: false, error: nil)
    }
}

enum StatusLoadError: LocalizedError {
    case httpStatus(Int)
    case emptyBody
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .httpStatus(let code):
            if code == 404 {
                return "status.json not found (404). Check the Pages URL and that Pages is enabled."
            }
            return "The status feed returned HTTP \(code)."
        case .emptyBody:
            return "The status feed is empty."
        case .decoding(let detail):
            return "The status feed is not the expected JSON: \(detail)"
        }
    }
}

/// Anchor class used to locate this code's bundle when `Bundle.main` is not the extension
/// (for example when the same sources are compiled into the SwiftPM library target).
private final class BundleToken {}
