// Read-only detail view for a past workout — replaces the old Alert.alert text
// dump. Shows the (now-corrected) date/time, a quick stat row, melded Apple-Watch
// heart rate, and each exercise's sets.
import React from 'react';
import { Modal, View, Text, ScrollView, TouchableOpacity, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
import { WorkoutSession } from '../../services/fitness';

interface Props {
  visible: boolean;
  session: WorkoutSession | null;
  onClose: () => void;
  onEdit?: (session: WorkoutSession) => void;
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

export default function WorkoutDetailModal({ visible, session, onClose, onEdit }: Props) {
  if (!session) return null;

  const first = session.exercises[0];
  const rawDate = first?.session_time || session.session_date || session.created_at;
  const d = new Date(rawDate && rawDate.includes('T') ? rawDate : `${rawDate}T12:00:00`);
  const dateLabel = d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  const timeLabel = first?.session_time
    ? d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    : null;

  // Group sets by exercise, preserving first-seen order.
  const order: string[] = [];
  const groups: Record<string, typeof session.exercises> = {};
  session.exercises.forEach((s) => {
    if (!groups[s.exercise_id]) {
      groups[s.exercise_id] = [];
      order.push(s.exercise_id);
    }
    groups[s.exercise_id].push(s);
  });

  const totalSets = session.exercises.length;
  const totalVolume = session.exercises.reduce(
    (sum, s) => sum + (Number(s.weight) || 0) * (Number(s.reps) || 0), 0,
  );
  const volumeLabel = totalVolume >= 1000 ? `${(totalVolume / 1000).toFixed(1)}k` : `${Math.round(totalVolume)}`;
  const hr = session.heart_rate;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.overlay}>
        <SafeAreaView style={styles.sheet} edges={['bottom']}>
          <View style={styles.grabber} />

          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title} numberOfLines={1}>{session.title || 'Workout'}</Text>
              <Text style={styles.subtitle}>
                {dateLabel}{timeLabel ? ` · ${timeLabel}` : ''}
              </Text>
            </View>
            <TouchableOpacity onPress={onClose} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
              <Ionicons name="close" size={26} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>

          <View style={styles.statsRow}>
            <Stat value={`${order.length}`} label={order.length === 1 ? 'exercise' : 'exercises'} />
            <Stat value={`${totalSets}`} label={totalSets === 1 ? 'set' : 'sets'} />
            <Stat value={volumeLabel} label="lb volume" />
          </View>

          {hr?.avg_heart_rate ? (
            <View style={styles.hrCard}>
              <Ionicons name="heart" size={15} color="#ff5a3a" />
              <Text style={styles.hrText}>
                {hr.avg_heart_rate} avg{hr.max_heart_rate ? ` · ${hr.max_heart_rate} max bpm` : ' bpm'}
                {hr.calories ? ` · ${hr.calories} cal` : ''}
                {hr.distance_m ? ` · ${(hr.distance_m / 1609.34).toFixed(2)} mi` : ''}
              </Text>
              {hr.activity ? <Text style={styles.hrActivity}>{hr.activity}</Text> : null}
            </View>
          ) : null}

          <ScrollView style={styles.scroll} contentContainerStyle={{ paddingBottom: spacing.lg }}>
            {order.map((exId) => {
              const sets = [...groups[exId]].sort((a, b) => (a.set_index || 0) - (b.set_index || 0));
              const topWeight = Math.max(...sets.map((s) => Number(s.weight) || 0));
              return (
                <View key={exId} style={styles.exerciseCard}>
                  <View style={styles.exerciseHeader}>
                    <Text style={styles.exerciseName} numberOfLines={1}>{exId}</Text>
                    <Text style={styles.exerciseMeta}>
                      {sets.length} {sets.length === 1 ? 'set' : 'sets'}{topWeight > 0 ? ` · top ${topWeight} lb` : ''}
                    </Text>
                  </View>
                  {sets.map((s, i) => (
                    <View key={s.id || `${exId}-${i}`} style={styles.setRow}>
                      <Text style={styles.setIndex}>{i + 1}</Text>
                      <Text style={styles.setMain}>
                        {s.weight ?? '—'} lb × {s.reps ?? '—'}
                      </Text>
                      <Text style={styles.setRpe}>{s.rpe ? `RPE ${s.rpe}` : ''}</Text>
                    </View>
                  ))}
                </View>
              );
            })}
          </ScrollView>

          {onEdit ? (
            <TouchableOpacity style={styles.editBtn} onPress={() => onEdit(session)} activeOpacity={0.85}>
              <Ionicons name="create-outline" size={18} color={colors.background} />
              <Text style={styles.editBtnText}>Edit workout</Text>
            </TouchableOpacity>
          ) : null}
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    paddingHorizontal: spacing.md,
    maxHeight: '85%',
  },
  grabber: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: fontWeights.bold,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  statsRow: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: spacing.md,
    marginBottom: spacing.sm,
  },
  stat: {
    flex: 1,
    alignItems: 'center',
  },
  statValue: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
  },
  statLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  hrCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  hrText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
    flex: 1,
  },
  hrActivity: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  scroll: {
    flexGrow: 0,
  },
  exerciseCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  exerciseHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  exerciseName: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
    flex: 1,
    marginRight: spacing.sm,
  },
  exerciseMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  setRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 5,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  setIndex: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    width: 24,
  },
  setMain: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
    flex: 1,
  },
  setRpe: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  editBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.accent,
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.md,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  editBtnText: {
    color: colors.background,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
});
