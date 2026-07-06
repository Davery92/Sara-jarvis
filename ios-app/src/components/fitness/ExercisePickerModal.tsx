import React, { useState, useEffect } from 'react';
import {
  View,
  Modal,
  ScrollView,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { fitnessService } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';

interface ExerciseVariant {
  exercise_id: string;
  name: string;
  movement_pattern: string;
  equipment: string[];
  last_performed: string | null;
  last_weight: number | null;
  last_reps: number | null;
  pr_weight: number | null;
  pr_reps: number | null;
  total_sets: number;
}

interface Props {
  visible: boolean;
  onClose: () => void;
  exerciseName: string; // the current slot's name — resolves the movement pattern server-side
  onSelectVariant: (name: string) => void;
}

// SARA_UNLEASHED Phase U.7 layer 3: every variant ever logged for this
// movement ("what did I do last time — iso, dumbbell, barbell?"), backed by
// GET /api/fitness/exercises?for_exercise_name=... (U.7 layer 2), plus an
// inline "Add exercise..." that creates a new exercise_library row without
// leaving the workout.
export default function ExercisePickerModal({ visible, onClose, exerciseName, onSelectVariant }: Props) {
  const [loading, setLoading] = useState(false);
  const [movement, setMovement] = useState<string | null>(null);
  const [variants, setVariants] = useState<ExerciseVariant[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible) {
      loadVariants();
    }
  }, [visible, exerciseName]);

  const loadVariants = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fitnessService.getExerciseVariants(exerciseName);
      setMovement(result.movement);
      setVariants(result.variants || []);
    } catch (err: any) {
      console.error('[ExercisePickerModal] Failed to load variants:', err);
      setError('Could not load exercise history.');
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = (variant: ExerciseVariant) => {
    onSelectVariant(variant.name);
    onClose();
  };

  const handleAddExercise = () => {
    Alert.prompt(
      'Add exercise',
      `New variant for this movement${movement ? ` (${movement.replace(/_/g, ' ')})` : ''}`,
      async (name?: string) => {
        const trimmed = (name || '').trim();
        if (!trimmed) return;
        try {
          const created = await fitnessService.createExerciseVariant(
            trimmed,
            movement || 'other',
          );
          onSelectVariant(created.name);
          onClose();
        } catch (err: any) {
          console.error('[ExercisePickerModal] Failed to create exercise:', err);
          Alert.alert('Error', 'Could not add that exercise. Please try again.');
        }
      },
      'plain-text',
    );
  };

  const formatLastSession = (v: ExerciseVariant): string => {
    if (!v.last_performed) return 'Never logged';
    const parts: string[] = [];
    if (v.last_weight != null && v.last_reps != null) {
      parts.push(`${v.last_weight} × ${v.last_reps}`);
    }
    const date = new Date(v.last_performed + 'T00:00:00');
    const dateStr = isNaN(date.getTime())
      ? v.last_performed
      : date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' });
    parts.push(`(${dateStr})`);
    return parts.join(' ');
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.overlay}>
        <SafeAreaView style={styles.container}>
          <View style={styles.header}>
            <Text style={styles.title}>Choose a variant</Text>
            <TouchableOpacity onPress={onClose} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
              <Ionicons name="close" size={24} color={colors.text} />
            </TouchableOpacity>
          </View>

          {loading ? (
            <View style={styles.centerBox}>
              <ActivityIndicator color={colors.accent} />
            </View>
          ) : error ? (
            <View style={styles.centerBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : (
            <ScrollView style={styles.list}>
              {variants.length === 0 ? (
                <Text style={styles.emptyText}>No variants logged yet for this movement.</Text>
              ) : (
                variants.map((v) => (
                  <TouchableOpacity
                    key={v.exercise_id}
                    style={styles.row}
                    onPress={() => handleSelect(v)}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rowName}>{v.name}</Text>
                      <Text style={styles.rowSub}>{formatLastSession(v)}</Text>
                    </View>
                    {v.pr_weight != null && (
                      <Text style={styles.rowPr}>PR {v.pr_weight}×{v.pr_reps}</Text>
                    )}
                  </TouchableOpacity>
                ))
              )}

              <TouchableOpacity style={styles.addRow} onPress={handleAddExercise}>
                <Ionicons name="add-circle-outline" size={20} color={colors.accent} />
                <Text style={styles.addRowText}>Add exercise…</Text>
              </TouchableOpacity>
            </ScrollView>
          )}
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
  container: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.lg,
    borderTopRightRadius: borderRadius.lg,
    maxHeight: '75%',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: {
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
    color: colors.text,
  },
  centerBox: {
    padding: spacing.xl,
    alignItems: 'center',
  },
  errorText: {
    color: colors.error,
    fontSize: fontSizes.md,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    padding: spacing.lg,
    textAlign: 'center',
  },
  list: {
    padding: spacing.md,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  rowName: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
    color: colors.text,
  },
  rowSub: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: 2,
  },
  rowPr: {
    fontSize: fontSizes.sm,
    color: colors.accent,
    fontWeight: fontWeights.semibold,
  },
  addRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.md,
    gap: spacing.xs,
  },
  addRowText: {
    color: colors.accent,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
});
