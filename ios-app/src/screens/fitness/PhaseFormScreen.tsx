import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  TouchableOpacity,
  Text,
  TextInput,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { RootStackScreenProps } from '../../types/navigation';
import { fitnessService } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

type Props = RootStackScreenProps<'PhaseForm'>;

const numOrNull = (s: string): number | null => {
  if (s === '' || s == null) return null;
  const n = parseInt(s, 10);
  return isNaN(n) ? null : n;
};

/**
 * One screen, two jobs:
 *   - mode "edit" (default): create/edit/delete a phase — mirrors the web
 *     PhaseManager modal (name, goal, dates, duration, flat targets,
 *     training/rest splits, steps target).
 *   - mode "block": start a dated cut/bulk/maintenance block via
 *     insert-block, which trims/shifts whatever it collides with.
 */
export default function PhaseFormScreen({ route, navigation }: Props) {
  const { phase, mode = 'edit', onSave } = route.params || {};
  const isBlockMode = mode === 'block';
  const isEditing = !!phase;

  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [name, setName] = useState(phase?.name || '');
  const [goal, setGoal] = useState(phase?.goal || (isBlockMode ? 'cut' : 'hypertrophy'));
  const [startDate, setStartDate] = useState(phase?.start_date || '');
  const [endDate, setEndDate] = useState(phase?.end_date || '');
  const [durationWeeks, setDurationWeeks] = useState(
    phase?.duration_weeks?.toString() || (isBlockMode ? '3' : '')
  );
  const [blockCollisionMode, setBlockCollisionMode] = useState<'overlay' | 'push'>('overlay');
  const [proteinTarget, setProteinTarget] = useState(phase?.protein_target?.toString() || '');
  const [caloriesTrainingDay, setCaloriesTrainingDay] = useState(phase?.calories_training_day?.toString() || '');
  const [caloriesRestDay, setCaloriesRestDay] = useState(phase?.calories_rest_day?.toString() || '');
  const [carbsTrainingDay, setCarbsTrainingDay] = useState(phase?.carbs_training_day?.toString() || '');
  const [carbsRestDay, setCarbsRestDay] = useState(phase?.carbs_rest_day?.toString() || '');
  const [fatTrainingDay, setFatTrainingDay] = useState(phase?.fat_training_day?.toString() || '');
  const [fatRestDay, setFatRestDay] = useState(phase?.fat_rest_day?.toString() || '');
  const [dailyStepsTarget, setDailyStepsTarget] = useState(phase?.daily_steps_target?.toString() || '');
  const [notes, setNotes] = useState(phase?.notes || '');

  const handleCancel = () => navigation.goBack();

  const handleSave = async () => {
    if (!name.trim()) {
      Alert.alert('Missing name', isBlockMode ? 'Give this block a name.' : 'Give this phase a name.');
      return;
    }

    setSaving(true);
    try {
      if (isBlockMode) {
        const summary = await fitnessService.insertPhaseBlock({
          name,
          goal,
          start_date: startDate || undefined,
          duration_weeks: numOrNull(durationWeeks) ?? undefined,
          mode: blockCollisionMode,
          protein_target: numOrNull(proteinTarget),
          calories_training_day: numOrNull(caloriesTrainingDay),
          calories_rest_day: numOrNull(caloriesRestDay),
          carbs_training_day: numOrNull(carbsTrainingDay),
          carbs_rest_day: numOrNull(carbsRestDay),
          fat_training_day: numOrNull(fatTrainingDay),
          fat_rest_day: numOrNull(fatRestDay),
          notes: notes || undefined,
        });
        onSave?.();
        const parts = [`"${summary.name}" runs ${summary.start_date} → ${summary.end_date}.`];
        if (summary.trimmed_phases?.length) parts.push(`Trimmed ${summary.trimmed_phases.length} phase(s).`);
        if (summary.shifted_phases?.length) parts.push(`Shifted ${summary.shifted_phases.length} phase(s).`);
        if (summary.shelved_phases?.length) parts.push(`Shelved ${summary.shelved_phases.length} phase(s).`);
        Alert.alert('Block started', parts.join(' '), [
          { text: 'OK', onPress: () => navigation.goBack() },
        ]);
        return;
      }

      const payload = {
        name,
        goal,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        duration_weeks: numOrNull(durationWeeks) ?? undefined,
        protein_target: numOrNull(proteinTarget),
        calories_training_day: numOrNull(caloriesTrainingDay),
        calories_rest_day: numOrNull(caloriesRestDay),
        carbs_training_day: numOrNull(carbsTrainingDay),
        carbs_rest_day: numOrNull(carbsRestDay),
        fat_training_day: numOrNull(fatTrainingDay),
        fat_rest_day: numOrNull(fatRestDay),
        daily_steps_target: numOrNull(dailyStepsTarget),
        notes,
      };

      if (isEditing) {
        await fitnessService.updatePhase(phase!.id, payload);
      } else {
        await fitnessService.createPhase(payload);
      }
      onSave?.();
      navigation.goBack();
    } catch (error) {
      console.error('Failed to save phase:', error);
      Alert.alert('Error', isBlockMode ? 'Failed to start block.' : 'Failed to save phase.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = () => {
    if (!phase) return;
    Alert.alert('Delete phase?', 'This will also delete its workout templates.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          setDeleting(true);
          try {
            await fitnessService.deletePhase(phase.id);
            onSave?.();
            navigation.goBack();
          } catch (error) {
            console.error('Failed to delete phase:', error);
            Alert.alert('Error', 'Failed to delete phase.');
          } finally {
            setDeleting(false);
          }
        },
      },
    ]);
  };

  const busy = saving || deleting;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <KeyboardAvoidingView style={styles.keyboardView} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <ScrollView style={styles.scrollView}>
          <View style={styles.header}>
            <Text style={styles.title}>
              {isBlockMode ? 'Start a Block' : isEditing ? 'Edit Phase' : 'New Phase'}
            </Text>
            <Text style={styles.subtitle}>
              {isBlockMode
                ? 'Drops a dated cut/bulk/maintenance block into the active program — surrounding phases trim or shift automatically.'
                : 'Training phases organize your program into structured blocks.'}
            </Text>
          </View>

          <View style={styles.form}>
            <View style={styles.inputGroup}>
              <Text style={styles.label}>{isBlockMode ? 'Block Name' : 'Phase Name'}</Text>
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder={isBlockMode ? 'e.g., Cut, 3-Week Cut' : 'e.g., Hypertrophy Block 1'}
                placeholderTextColor={colors.textMuted}
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Goal</Text>
              <TextInput
                style={styles.input}
                value={goal}
                onChangeText={setGoal}
                placeholder={isBlockMode ? 'cut, bulk, maintenance, recomp' : 'hypertrophy, strength, deload...'}
                placeholderTextColor={colors.textMuted}
              />
            </View>

            <View style={styles.row}>
              <View style={[styles.inputGroup, styles.rowItem]}>
                <Text style={styles.label}>Start Date</Text>
                <TextInput
                  style={styles.input}
                  value={startDate}
                  onChangeText={setStartDate}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.textMuted}
                />
                {isBlockMode ? <Text style={styles.hint}>Defaults to next Monday</Text> : null}
              </View>
              {isBlockMode ? (
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={styles.label}>Duration (wks)</Text>
                  <TextInput
                    style={styles.input}
                    value={durationWeeks}
                    onChangeText={setDurationWeeks}
                    keyboardType="number-pad"
                    placeholder="3"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              ) : (
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={styles.label}>End Date</Text>
                  <TextInput
                    style={styles.input}
                    value={endDate}
                    onChangeText={setEndDate}
                    placeholder="YYYY-MM-DD"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              )}
            </View>

            {!isBlockMode ? (
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Duration (weeks)</Text>
                <TextInput
                  style={styles.input}
                  value={durationWeeks}
                  onChangeText={setDurationWeeks}
                  keyboardType="number-pad"
                  placeholder="8"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
            ) : (
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Collision mode</Text>
                <View style={styles.segmented}>
                  {(['overlay', 'push'] as const).map((m) => (
                    <TouchableOpacity
                      key={m}
                      style={[styles.segment, blockCollisionMode === m && styles.segmentActive]}
                      onPress={() => setBlockCollisionMode(m)}
                    >
                      <Text style={[styles.segmentText, blockCollisionMode === m && styles.segmentTextActive]}>
                        {m === 'overlay' ? 'Overlay (trim/split)' : 'Push (shift later phases)'}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>
            )}

            <View style={styles.sectionCard}>
              <Text style={styles.sectionLabel}>Calorie Cycling</Text>
              <View style={styles.inputGroup}>
                <Text style={styles.labelSmall}>Protein (g/day, constant)</Text>
                <TextInput
                  style={styles.input}
                  value={proteinTarget}
                  onChangeText={setProteinTarget}
                  keyboardType="number-pad"
                  placeholder="230"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
              <View style={styles.row}>
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={[styles.labelSmall, { color: colors.hues.violet }]}>Training day kcal</Text>
                  <TextInput
                    style={styles.input}
                    value={caloriesTrainingDay}
                    onChangeText={setCaloriesTrainingDay}
                    keyboardType="number-pad"
                    placeholder={isBlockMode ? '2300' : '2650'}
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={[styles.labelSmall, { color: colors.hues.sky }]}>Rest day kcal</Text>
                  <TextInput
                    style={styles.input}
                    value={caloriesRestDay}
                    onChangeText={setCaloriesRestDay}
                    keyboardType="number-pad"
                    placeholder={isBlockMode ? '1900' : '2200'}
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>
              <View style={styles.row}>
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={[styles.labelSmall, { color: colors.hues.violet }]}>Training day carbs (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={carbsTrainingDay}
                    onChangeText={setCarbsTrainingDay}
                    keyboardType="number-pad"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={[styles.labelSmall, { color: colors.hues.sky }]}>Rest day carbs (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={carbsRestDay}
                    onChangeText={setCarbsRestDay}
                    keyboardType="number-pad"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>
              <View style={styles.row}>
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={[styles.labelSmall, { color: colors.hues.violet }]}>Training day fat (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={fatTrainingDay}
                    onChangeText={setFatTrainingDay}
                    keyboardType="number-pad"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <View style={[styles.inputGroup, styles.rowItem]}>
                  <Text style={[styles.labelSmall, { color: colors.hues.sky }]}>Rest day fat (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={fatRestDay}
                    onChangeText={setFatRestDay}
                    keyboardType="number-pad"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>
            </View>

            {!isBlockMode && (
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Daily steps target</Text>
                <TextInput
                  style={styles.input}
                  value={dailyStepsTarget}
                  onChangeText={setDailyStepsTarget}
                  keyboardType="number-pad"
                  placeholder="9000"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
            )}

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Notes</Text>
              <TextInput
                style={[styles.input, styles.textArea]}
                value={notes}
                onChangeText={setNotes}
                multiline
                numberOfLines={3}
                placeholder="Optional notes..."
                placeholderTextColor={colors.textMuted}
              />
            </View>

            {isEditing && !isBlockMode ? (
              <TouchableOpacity style={styles.deleteButton} onPress={handleDelete} disabled={busy}>
                {deleting ? (
                  <ActivityIndicator color={colors.error} />
                ) : (
                  <Text style={styles.deleteButtonText}>Delete Phase</Text>
                )}
              </TouchableOpacity>
            ) : null}
          </View>
        </ScrollView>

        <View style={styles.buttons}>
          <TouchableOpacity style={[styles.button, styles.cancelButton]} onPress={handleCancel} disabled={busy}>
            <Text style={styles.cancelButtonText}>Cancel</Text>
          </TouchableOpacity>
          <TouchableOpacity style={[styles.button, styles.saveButton]} onPress={handleSave} disabled={busy}>
            {saving ? (
              <ActivityIndicator color={colors.text} />
            ) : (
              <Text style={styles.saveButtonText}>{isBlockMode ? 'Start Block' : isEditing ? 'Save' : 'Create'}</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  keyboardView: { flex: 1 },
  scrollView: { flex: 1 },
  header: { padding: spacing.lg, paddingBottom: spacing.md },
  title: { color: colors.text, fontSize: fontSizes.xxl, fontWeight: '700', marginBottom: spacing.xs },
  subtitle: { color: colors.textSecondary, fontSize: fontSizes.sm },
  form: { padding: spacing.lg },
  row: { flexDirection: 'row', gap: spacing.md },
  rowItem: { flex: 1 },
  inputGroup: { marginBottom: spacing.lg },
  label: { color: colors.text, fontSize: fontSizes.md, fontWeight: '600', marginBottom: spacing.sm },
  labelSmall: { color: colors.textSecondary, fontSize: fontSizes.sm, fontWeight: '600', marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  textArea: { minHeight: 72, textAlignVertical: 'top' },
  hint: { color: colors.textMuted, fontSize: fontSizes.xs, marginTop: spacing.xs },
  sectionCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  sectionLabel: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '700',
    marginBottom: spacing.md,
  },
  segmented: { flexDirection: 'row', gap: spacing.sm },
  segment: {
    flex: 1,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  segmentActive: { backgroundColor: colors.assistant.actionSoft, borderColor: colors.primary },
  segmentText: { color: colors.textSecondary, fontSize: fontSizes.xs, fontWeight: '600', textAlign: 'center' },
  segmentTextActive: { color: colors.primary },
  deleteButton: {
    marginTop: spacing.sm,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.error,
    alignItems: 'center',
  },
  deleteButtonText: { color: colors.error, fontSize: fontSizes.md, fontWeight: '600' },
  buttons: {
    flexDirection: 'row',
    gap: spacing.md,
    padding: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  button: {
    flex: 1,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 48,
  },
  cancelButton: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  cancelButtonText: { color: colors.textSecondary, fontSize: fontSizes.md, fontWeight: '600' },
  saveButton: { backgroundColor: colors.primary },
  saveButtonText: { color: colors.text, fontSize: fontSizes.md, fontWeight: '600' },
});
