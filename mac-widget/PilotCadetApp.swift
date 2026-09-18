//
//  PilotCadetApp.swift
//  PilotCadet (host app)
//
//  Minimal container app for the widget extension. A WidgetKit extension cannot be installed
//  on its own, so this target exists to (a) carry the App Group entitlement and (b) give you a
//  place to paste your status.json URL without editing WidgetConfig.swift.
//
//  Everything here is deliberately small: the interesting logic lives in Models.swift,
//  WidgetConfig.swift and PilotCadetWidget.swift, which are shared with the widget target.
//

import SwiftUI
import WidgetKit

@main
struct PilotCadetApp: App {
    var body: some Scene {
        WindowGroup("Pilot Cadet Watch") {
            SettingsView()
                .frame(minWidth: 460, minHeight: 420)
        }
        .windowResizability(.contentSize)
    }
}

struct SettingsView: View {
    @State private var endpointText: String
    @State private var document: StatusDocument?
    @State private var statusMessage: String?
    @State private var isLoading = false

    init() {
        _endpointText = State(initialValue: WidgetConfig.statusURL.absoluteString)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header

            GroupBox("Status feed") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("URL of the status.json published by the GitHub Actions workflow.")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    TextField("https://<user>.github.io/pilot-tracker/status.json", text: $endpointText)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(saveEndpoint)

                    HStack(spacing: 8) {
                        Button("Save URL", action: saveEndpoint)
                        Button(isLoading ? "Checking…" : "Test connection", action: testConnection)
                            .disabled(isLoading)
                        Button("Refresh widget", action: refreshWidget)
                        Spacer()
                    }

                    // Be explicit rather than silently misleading: without the App Group the
                    // sandboxed widget cannot read the value saved here, so the endpoint the
                    // widget uses is the one compiled into WidgetConfig.swift.
                    if !WidgetConfig.isUsingAppGroup {
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "info.circle.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(.orange)
                            Text("App Groups are disabled, so the widget reads the URL compiled into "
                                 + "WidgetConfig.swift. This field only affects the preview below. "
                                 + "To change the widget's URL, edit that file and rebuild.")
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(6)
            }

            GroupBox("Live preview") {
                if let document {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("\(document.programs.count) programmes · updated \(document.generatedAt ?? "unknown")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        ForEach(document.displayPrograms) { program in
                            HStack(spacing: 8) {
                                StatusPill(state: program.status)
                                Text(program.airline).font(.system(size: 12, weight: .semibold))
                                Text(program.program).font(.system(size: 11)).foregroundStyle(.secondary)
                                Spacer()
                                PassportPill(text: program.passportBadge)
                                if let url = program.applicationLink {
                                    Link("Open", destination: url).font(.system(size: 11))
                                }
                            }
                        }
                    }
                    .padding(6)
                } else {
                    Text(statusMessage ?? "No feed loaded yet.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(6)
                }
            }

            if let statusMessage, document != nil {
                Text(statusMessage).font(.caption).foregroundStyle(.secondary)
            }

            Spacer(minLength: 0)

            Text("Tip: keep this app in /Applications. macOS only keeps widgets alive for installed apps.")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(18)
        .task {
            // Opening the app should also refresh the desktop widget, otherwise a feed that was
            // just published would not appear until macOS decided to ask for a new timeline.
            WidgetCenter.shared.reloadAllTimelines()
            await refreshFromFeed()
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "airplane.departure").font(.title2)
            VStack(alignment: .leading, spacing: 1) {
                Text("Pilot Cadet Watch").font(.headline)
                Text("Passive daily monitoring of fully funded cadet programmes")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }

    private func saveEndpoint() {
        let trimmed = endpointText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme?.hasPrefix("http") == true else {
            statusMessage = "That is not a valid http(s) URL."
            return
        }
        WidgetConfig.setStatusURL(url)
        statusMessage = "Saved. Reloading the widget…"
        refreshWidget()
        Task { await refreshFromFeed() }
    }

    private func refreshWidget() {
        WidgetCenter.shared.reloadTimelines(ofKind: WidgetConfig.widgetKind)
        WidgetCenter.shared.reloadAllTimelines()
    }

    private func testConnection() {
        Task { await refreshFromFeed() }
    }

    private func refreshFromFeed() async {
        isLoading = true
        defer { isLoading = false }
        let result = await StatusLoader.load()
        document = result.document
        if let error = result.error {
            statusMessage = "Fetch failed: \(error)"
        } else {
            statusMessage = "Feed loaded (\(result.isFromCache ? "from cache" : "live"))."
        }
    }
}
