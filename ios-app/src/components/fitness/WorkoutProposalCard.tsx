import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useWorkoutMode } from '../../context/WorkoutModeContext';
import { describeProposal } from '../../services/workoutContracts';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * Coaching line and approval controls (plan §9.5, §11.4).
 *
 * Two things share this space, and the difference between them is the whole
 * point of the approval model:
 *
 *  - Ordinary coaching is transient. It appears, it is read, it goes.
 *  - A proposal is a question. It stays until David answers it — it does NOT
 *    fade after five seconds like coaching does, because a question that
 *    disappears unanswered and then gets applied anyway is not consent, and
 *    one that disappears and is discarded silently is just confusing (§9.5).
 *
 * Wording is future tense throughout. Sara says what she recommends; she never
 * says "I dropped the weight" before the approval transaction has succeeded
 * (§11.4). "Keep current" is a full-weight button, not a dismissal — if saying
 * no is harder than saying yes, consent stops meaning anything.
 */
export default function WorkoutProposalCard() {
  const { pendingProposal, coaching, approveProposal, rejectProposal } = useWorkoutMode();

  if (pendingProposal) {
    const change = describeProposal(pendingProposal);
    return (
      <View style={[styles.card, styles.proposalCard]}>
        <View style={styles.headerRow}>
          <Ionicons name="sparkles" size={14} color={colors.primary} />
          <Text style={styles.headerText}>Sara recommends</Text>
        </View>

        {change && <Text style={styles.change}>{change}</Text>}
        {pendingProposal.reason && (
          <Text style={styles.reason}>{pendingProposal.reason}</Text>
        )}

        <View style={styles.actions}>
          <TouchableOpacity
            style={[styles.button, styles.approve]}
            onPress={() => approveProposal(pendingProposal.proposal_id)}
          >
            <Text style={styles.approveText}>Approve</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.button, styles.keep]}
            onPress={() => rejectProposal(pendingProposal.proposal_id)}
          >
            <Text style={styles.keepText}>Keep current</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.footnote}>Nothing changes until you approve.</Text>
      </View>
    );
  }

  if (coaching?.text) {
    return (
      <View style={styles.card}>
        <Ionicons name="chatbubble-ellipses-outline" size={14} color={colors.textSecondary} />
        <Text style={styles.coaching}>{coaching.text}</Text>
      </View>
    );
  }

  return null;
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  proposalCard: {
    flexDirection: 'column',
    alignItems: 'stretch',
    borderWidth: 1,
    borderColor: colors.primary,
    gap: spacing.xs,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  headerText: {
    fontSize: fontSizes.xs,
    color: colors.primary,
    fontWeight: fontWeights.semibold,
  },
  change: {
    fontSize: fontSizes.lg,
    color: colors.text,
    fontWeight: fontWeights.bold,
    fontVariant: ['tabular-nums'],
  },
  reason: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  coaching: {
    flex: 1,
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  button: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.sm,
    alignItems: 'center',
  },
  approve: {
    backgroundColor: colors.primary,
  },
  approveText: {
    fontSize: fontSizes.sm,
    color: colors.background,
    fontWeight: fontWeights.semibold,
  },
  keep: {
    backgroundColor: colors.surfaceLight,
  },
  keepText: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: fontWeights.semibold,
  },
  footnote: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
});
