//
//  StatusViews.swift
//  PilotCadetWidget
//
//  Small shared visual components. This file is compiled into BOTH the widget extension and
//  the host app, which is why it lives separately from PilotCadetWidget.swift (that file
//  contains the widget's `@main` entry point and must not be part of the app target).
//

import SwiftUI

/// Coloured status pill: green `OPEN`, orange `INTEREST`, neutral gray `CLOSED`.
struct StatusPill: View {
    let state: ProgramState
    var compact: Bool = false

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: state.symbolName)
                .font(.system(size: compact ? 7 : 8, weight: .bold))
            Text(state.label)
                .font(.system(size: compact ? 8 : 9, weight: .bold, design: .rounded))
                .tracking(0.3)
        }
        .foregroundStyle(state.tint)
        .padding(.horizontal, compact ? 5 : 6)
        .padding(.vertical, compact ? 1.5 : 2)
        .background(
            Capsule(style: .continuous)
                .fill(state.tint.opacity(state == .closed ? 0.14 : 0.18))
        )
        .overlay(
            Capsule(style: .continuous)
                .strokeBorder(state.tint.opacity(0.45), lineWidth: 0.6)
        )
        .fixedSize()
        .accessibilityLabel("Status \(state.label)")
    }
}

/// Passport / right-to-work pill: `🇬🇧 UK`, `🇪🇺 EU`, `🌍 Global`.
struct PassportPill: View {
    let text: String
    var compact: Bool = false

    var body: some View {
        Text(text)
            .font(.system(size: compact ? 9 : 10, weight: .medium))
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .padding(.horizontal, compact ? 5 : 6)
            .padding(.vertical, compact ? 1.5 : 2)
            .background(
                Capsule(style: .continuous)
                    .fill(Color.primary.opacity(0.06))
            )
            .fixedSize()
            .accessibilityLabel("Passport or right to work: \(text)")
    }
}
