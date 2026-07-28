import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { fitnessService } from '../../services/fitness';
import { workoutCoordinator } from '../../services/workoutCoordinator';
import { describeProposal, type WorkoutProposal } from '../../services/workoutContracts';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

/**
 * Questions Sara asks after the workout, on the summary screen (plan §4.3, §8).
 *
 * These exist because of a rule the in-session controls enforce strictly:
 * adding a set changes today's workout and nothing else. That is right during
 * the workout — a man mid-session should not be editing his program — but it
 * would mean re-adding the same set every week forever.
 *
 * So the question is asked once, here, where there is time to think about it,
 * and it is a genuinely separate approval. Nothing about tapping Add Set at the
 * rack implies a yes to this. "Not now" is a full-weight button; the workout is
 * already saved either way.
 *
 * Deliberately session-less: these proposals outlive the workout that produced
 * them, so they are fetched from `/v2/proposals` rather than read off a live
 * projection.
 */

const OUT_OF_GYM_KINDS = new Set(['template_set_count', 'next_session_weight']);

export default function PostWorkoutProposals() {
  const [proposals, setProposals] = useState<WorkoutProposal[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { proposals: all } = await fitnessService.v2Proposals('pending');
      setProposals(all.filter((p) => OUT_OF_GYM_KINDS.has(p.kind)));
    } catch {
      // A summary screen that can't reach the network still shows the workout.
      setProposals([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const resolve = async (proposal: WorkoutProposal, approve: boolean) => {
    setBusy(proposal.proposal_id);
    // Optimistic removal: the question has been answered, and leaving it on
    // screen invites a second tap that would do nothing.
    setProposals((prev) => prev.filter((p) => p.proposal_id !== proposal.proposal_id));
    try {
      await workoutCoordinator.resolveProposal(proposal.proposal_id, approve, 'phone');
    } catch {
      await load();
    } finally {
      setBusy(null);
    }
  };

  if (proposals.length === 0) return null;

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <Ionicons name="sparkles" size={14} color={colors.primary} />
        <Text style={styles.headerText}>Before you go</Text>
      </View>

      {proposals.map((proposal) => (
        <View key={proposal.proposal_id} style={styles.card}>
          <Text style={styles.change}>{describeProposal(proposal) ?? 'A change to your plan'}</Text>
          {proposal.reason ? <Text style={styles.reason}>{proposal.reason}</Text> : null}
          <View style={styles.actions}>
            <TouchableOpacity
              style={[styles.button, styles.approve]}
              onPress={() => resolve(proposal, true)}
              disabled={busy === proposal.proposal_id}
            >
              <Text style={styles.approveText}>Make it permanent</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.button, styles.keep]}
              onPress={() => resolve(proposal, false)}
              disabled={busy === proposal.proposal_id}
            >
              <Text style={styles.keepText}>Not now</Text>
            </TouchableOpacity>
          </View>
        </View>
      ))}

      <Text style={styles.footnote}>Your plan doesn't change unless you say so.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignSelf: 'stretch',
    marginTop: spacing.lg,
    gap: spacing.sm,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  headerText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.semibold,
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
  card: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    gap: spacing.xs,
  },
  change: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
  },
  reason: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.xs,
  },
  button: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.md,
  },
  approve: {
    backgroundColor: colors.primary,
  },
  approveText: {
    color: colors.background,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.bold,
  },
  keep: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceLight,
  },
  keepText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  footnote: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
});
