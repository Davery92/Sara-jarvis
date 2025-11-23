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
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

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

  const [logDate, setLogDate] = useState(existingLog?.log_date || new Date().toISOString().split('T')[0]);
  const [sleepHours, setSleepHours] = useState(existingLog?.sleep_hours?.toString() || '');
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

      if (sleepHours) recoveryData.sleep_hours = parseFloat(sleepHours);
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

        {/* Sleep Hours */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Sleep Hours</Text>
          <TextInput
            style={styles.input}
            value={sleepHours}
            onChangeText={setSleepHours}
            placeholder="e.g., 7.5"
            placeholderTextColor={colors.textMuted}
            keyboardType="decimal-pad"
          />
          <Text style={styles.hint}>Total hours of sleep</Text>
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
    borderBottomColor: colors.surface,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  cancelButton: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  saveButton: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
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
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
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
  weightRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  weightInput: {
    flex: 1,
  },
  unitToggle: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    overflow: 'hidden',
  },
  unitButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    minWidth: 60,
    alignItems: 'center',
  },
  unitButtonActive: {
    backgroundColor: colors.primary,
  },
  unitButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  unitButtonTextActive: {
    color: colors.text,
  },
});
