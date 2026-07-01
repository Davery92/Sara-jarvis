import React, { useState } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  TextInput,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { fitnessService, RecoveryLog } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
import { getLocalDateString } from '../../utils/dateUtils';

interface RecoveryFormScreenProps {
  route?: {
    params?: {
      log?: RecoveryLog;
      onSave?: () => void;
    };
  };
  navigation: any;
}

export default function RecoveryFormScreen({ route, navigation }: RecoveryFormScreenProps) {
  const existingLog = route?.params?.log;
  const onSave = route?.params?.onSave;

  const [logDate, setLogDate] = useState(existingLog?.log_date || getLocalDateString());
  // Convert decimal hours to hours and minutes for display
  const existingSleepHours = existingLog?.sleep_hours ? Math.floor(existingLog.sleep_hours) : null;
  const existingSleepMinutes = existingLog?.sleep_hours
    ? Math.round((existingLog.sleep_hours - Math.floor(existingLog.sleep_hours)) * 60)
    : null;
  const [sleepHours, setSleepHours] = useState(existingSleepHours?.toString() || '');
  const [sleepMinutes, setSleepMinutes] = useState(existingSleepMinutes?.toString() || '');
  const [hrv, setHrv] = useState(existingLog?.hrv?.toString() || '');
  const [heartRate, setHeartRate] = useState(existingLog?.heart_rate?.toString() || '');
  const [sorenessLevel, setSorenessLevel] = useState(existingLog?.soreness_level?.toString() || '');
  const [bodyWeight, setBodyWeight] = useState(existingLog?.body_weight?.toString() || '');
  const [weightUnit, setWeightUnit] = useState(existingLog?.weight_unit || 'lbs');
  const [notes, setNotes] = useState(existingLog?.notes || '');

  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    try {
      setSaving(true);

      const recoveryData: any = {
        log_date: logDate,
      };

      // Convert hours and minutes to decimal hours
      if (sleepHours || sleepMinutes) {
        const hours = sleepHours ? parseInt(sleepHours) : 0;
        const minutes = sleepMinutes ? parseInt(sleepMinutes) : 0;
        recoveryData.sleep_hours = hours + (minutes / 60);
      }
      if (hrv) recoveryData.hrv = parseInt(hrv);
      if (heartRate) recoveryData.heart_rate = parseInt(heartRate);
      if (sorenessLevel) recoveryData.soreness_level = parseInt(sorenessLevel);
      if (bodyWeight) recoveryData.body_weight = parseFloat(bodyWeight);
      if (weightUnit) recoveryData.weight_unit = weightUnit;
      if (notes) recoveryData.notes = notes;

      await fitnessService.createRecoveryLog(recoveryData);

      Alert.alert('Success', 'Recovery log saved successfully', [
        {
          text: 'OK',
          onPress: () => {
            onSave?.();
            navigation.goBack();
          },
        },
      ]);
    } catch (error) {
      console.error('Failed to save recovery log:', error);
      Alert.alert('Error', 'Failed to save recovery log');
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={styles.cancelButton}>Cancel</Text>
        </TouchableOpacity>
        <Text style={styles.title}>
          {existingLog ? 'Edit Recovery' : 'Log Recovery'}
        </Text>
        <TouchableOpacity onPress={handleSave} disabled={saving}>
          <Text style={[styles.saveButton, saving && styles.saveButtonDisabled]}>
            {saving ? 'Saving...' : 'Save'}
          </Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.content}>
        {/* Date */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Date</Text>
          <TextInput
            style={styles.input}
            value={logDate}
            onChangeText={setLogDate}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.textMuted}
          />
        </View>

        {/* Sleep Hours and Minutes */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Sleep Duration</Text>
          <View style={styles.sleepRow}>
            <View style={styles.sleepInputGroup}>
              <TextInput
                style={[styles.input, styles.sleepInput]}
                value={sleepHours}
                onChangeText={setSleepHours}
                placeholder="7"
                placeholderTextColor={colors.textMuted}
                keyboardType="number-pad"
                maxLength={2}
              />
              <Text style={styles.sleepLabel}>hours</Text>
            </View>
            <View style={styles.sleepInputGroup}>
              <TextInput
                style={[styles.input, styles.sleepInput]}
                value={sleepMinutes}
                onChangeText={setSleepMinutes}
                placeholder="30"
                placeholderTextColor={colors.textMuted}
                keyboardType="number-pad"
                maxLength={2}
              />
              <Text style={styles.sleepLabel}>minutes</Text>
            </View>
          </View>
          <Text style={styles.hint}>Total time asleep</Text>
        </View>

        {/* HRV */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>HRV (Heart Rate Variability)</Text>
          <TextInput
            style={styles.input}
            value={hrv}
            onChangeText={setHrv}
            placeholder="e.g., 65"
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
          />
          <Text style={styles.hint}>In milliseconds (higher is generally better)</Text>
        </View>

        {/* Heart Rate */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Resting Heart Rate</Text>
          <TextInput
            style={styles.input}
            value={heartRate}
            onChangeText={setHeartRate}
            placeholder="e.g., 58"
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
          />
          <Text style={styles.hint}>In beats per minute (lower is generally better)</Text>
        </View>

        {/* Soreness Level */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Soreness Level</Text>
          <TextInput
            style={styles.input}
            value={sorenessLevel}
            onChangeText={setSorenessLevel}
            placeholder="1-10"
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
          />
          <Text style={styles.hint}>1 = no soreness, 10 = extremely sore</Text>
        </View>

        {/* Body Weight */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Body Weight</Text>
          <View style={styles.weightRow}>
            <TextInput
              style={[styles.input, styles.weightInput]}
              value={bodyWeight}
              onChangeText={setBodyWeight}
              placeholder="e.g., 175"
              placeholderTextColor={colors.textMuted}
              keyboardType="decimal-pad"
            />
            <View style={styles.unitToggle}>
              <TouchableOpacity
                style={[styles.unitButton, weightUnit === 'lbs' && styles.unitButtonActive]}
                onPress={() => setWeightUnit('lbs')}
              >
                <Text style={[styles.unitButtonText, weightUnit === 'lbs' && styles.unitButtonTextActive]}>
                  lbs
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.unitButton, weightUnit === 'kg' && styles.unitButtonActive]}
                onPress={() => setWeightUnit('kg')}
              >
                <Text style={[styles.unitButtonText, weightUnit === 'kg' && styles.unitButtonTextActive]}>
                  kg
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>

        {/* Notes */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Notes (Optional)</Text>
          <TextInput
            style={[styles.input, styles.notesInput]}
            value={notes}
            onChangeText={setNotes}
            placeholder="Any additional notes..."
            placeholderTextColor={colors.textMuted}
            multiline
            numberOfLines={4}
            textAlignVertical="top"
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
  },
  cancelButton: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  saveButton: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
  },
  saveButtonDisabled: {
    color: colors.textMuted,
  },
  content: {
    flex: 1,
    padding: spacing.md,
  },
  formGroup: {
    marginBottom: spacing.lg,
  },
  label: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
    marginBottom: spacing.sm,
  },
  input: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  hint: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
  notesInput: {
    minHeight: 100,
  },
  sleepRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  sleepInputGroup: {
    flex: 1,
    alignItems: 'center',
  },
  sleepInput: {
    width: '100%',
    textAlign: 'center',
  },
  sleepLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
  weightRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  weightInput: {
    flex: 1,
  },
  unitToggle: {
    flexDirection: 'row',
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  unitButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    minWidth: 60,
    alignItems: 'center',
    justifyContent: 'center',
  },
  unitButtonActive: {
    backgroundColor: colors.assistant.actionSoft,
  },
  unitButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  unitButtonTextActive: {
    color: colors.accent,
  },
});
