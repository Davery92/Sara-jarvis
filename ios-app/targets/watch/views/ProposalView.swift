import SwiftUI

/// Approval screen (plan §8.6, §11.4).
///
/// This is where the approval boundary is actually enforced in the interface,
/// so its rules are strict:
///
///  - No countdown applies anything. There is no timer that turns into a yes;
///    an expired proposal simply stops being offered (§8.6, §2.4).
///  - "Keep current" is a real, equally-weighted button, not a dismissal. If
///    saying no is harder than saying yes, consent stops meaning anything.
///  - The wording is future tense until the transaction succeeds. Sara says
///    "I recommend", never "I dropped the weight" (§11.4).
///
/// Both buttons issue the same kind of idempotent command, so a tap that is
/// lost in flight resolves once when it replays — never twice, never opposite.
struct ProposalView: View {
    let proposal: WorkoutProposal

    @EnvironmentObject private var manager: WorkoutManager
    @State private var resolving = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Label("Sara recommends", systemImage: "sparkles")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.tint)

                if let change = proposal.weightChange {
                    HStack(spacing: 6) {
                        Text("\(Int(change.current))")
                            .foregroundStyle(.secondary)
                        Image(systemName: "arrow.right")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        Text("\(Int(change.proposed)) lb")
                            .fontWeight(.semibold)
                    }
                    .font(.title3)
                    .monospacedDigit()
                }

                if let reason = proposal.reason {
                    Text(reason)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                Button {
                    resolve(approve: true)
                } label: {
                    Text("Approve").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(resolving)

                Button {
                    resolve(approve: false)
                } label: {
                    Text("Keep current").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(resolving)

                Text("Nothing changes until you approve.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 4)
        }
    }

    private func resolve(approve: Bool) {
        resolving = true
        manager.resolve(proposal: proposal, approve: approve)
    }
}
