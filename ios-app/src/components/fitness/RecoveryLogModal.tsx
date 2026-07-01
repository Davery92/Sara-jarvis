import React, { useState } from 'react';
import {
  View,
  Modal,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { fitnessService } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
import { getLocalDateString } from '../../utils/dateUtils';

interface Props {
  visible: boolean;
  onClose: () => void;
  onComplete: () => void;
}

export default function RecoveryLogModal({ visible, onClose, onComplete }: Props) {
  const [loading, setLoading] = useState(false);
  const [sleepHours, setSleepHours] = useState('');
  const [hrv, setHrv] = useState('');
  const [heartRate, setHeartRate] = useState('');
  const [sorenessLevel, setSorenessLevel] = useState('');
  const [bodyWeight, setBodyWeight] = useState('');
  const [weightUnit, setWeightUnit] = useState<'lbs' | 'kg'>('lbs');
  const [notes, setNotes] = useState('');

  const handleSubmit = async () => {
    // Validate that at least one field is filled
    if (
      !sleepHours &&
      !hrv &&
      !heartRate &&
      !sorenessLevel &&
      !bodyWeight &&
      !notes
    ) {
      Alert.alert('Error', 'Please enter at least one recovery metric');
      return;
    }

    // Validate soreness level if provided
    if (sorenessLevel) {
      const level = parseInt(sorenessLevel, 10);
      if (isNaN(level) || level < 1 || level > 10) {
        Alert.alert('Error', 'Soreness level must be between 1 and 10');
        return;
      }
    }

    try {
      setLoading(true);
      const today = getLocalDateString();

      await fitnessService.createRecoveryLog({
        log_date: today,
        sleep_hours: sleepHours ? parseFloat(sleepHours) : undefined,
        hrv: hrv ? parseInt(hrv, 10) : undefined,
        heart_rate: heartRate ? parseInt(heartRate, 10) : undefined,
        soreness_level: sorenessLevel ? parseInt(sorenessLevel, 10) : undefined,
        body_weight: bodyWeight ? parseFloat(bodyWeight) : undefined,
        weight_unit: bodyWeight ? weightUnit : undefined,
        notes: notes || undefined,
      });

      Alert.alert('Success', 'Recovery metrics logged successfully');
      resetForm();
      onComplete();
    } catch (error: any) {
      console.error('Failed to log recovery:', error);
      Alert.alert(
        'Error',
        error.response?.data?.detail || 'Failed to log recovery metrics'
      );
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setSleepHours('');
    setHrv('');
    setHeartRate('');
    setSorenessLevel('');
    setBodyWeight('');
    setWeightUnit('lbs');
    setNotes('');
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
    >
      <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
        <View style={styles.header}>
          <TouchableOpacity onPress={handleClose}>
            <Text style={styles.cancelButton}>Cancel</Text>
          </TouchableOpacity>
          <Text style={styles.title}>Log Recovery</Text>
          <TouchableOpacity onPress={handleSubmit} disabled={loading}>
            {loading ? (
              <ActivityIndicator color={colors.primary} />
            ) : (
              <Text style={styles.saveButton}>Save</Text>
            )}
          </TouchableOpacity>
        </View>

        <ScrollView style={styles.content} contentContainerStyle={styles.scrollContent}>
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Sleep & Recovery</Text>

            <View style={styles.field}>
              <Text style={styles.label}>Sleep Hours</Text>
              <TextInput
                style={styles.input}
                placeholder="e.g., 7.5"
                placeholderTextColor={colors.textMuted}
                value={sleepHours}
                onChangeText={setSleepHours}
                keyboardType="decimal-pad"
              />
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>HRV (ms)</Text>
              <TextInput
                style={styles.input}
                placeholder="e.g., 65"
                placeholderTextColor={colors.textMuted}
                value={hrv}
                onChangeText={setHrv}
                keyboardType="number-pad"
              />
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>Resting Heart Rate (bpm)</Text>
              <TextInput
                style={styles.input}
                placeholder="e.g., 60"
                placeholderTextColor={colors.textMuted}
                value={heartRate}
                onChangeText={setHeartRate}
                keyboardType="number-pad"
              />
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Physical Status</Text>

            <View style={styles.field}>
              <Text style={styles.label}>Soreness Level (1-10)</Text>
              <View style={styles.sorenessScale}>
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((level) => (
                  <TouchableOpacity
                    key={level}
                    style={[
                      styles.sorenessButton,
                      sorenessLevel === level.toString() && styles.sorenessButtonActive,
                    ]}
                    onPress={() => setSorenessLevel(level.toString())}
                  >
                    <Text
                      style={[
                        styles.sorenessText,
                        sorenessLevel === level.toString() && styles.sorenessTextActive,
                      ]}
                    >
                      {level}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>Body Weight</Text>
              <View style={styles.weightRow}>
                <TextInput
                  style={[styles.input, styles.weightInput]}
                  placeholder="e.g., 185"
                  placeholderTextColor={colors.textMuted}
                  value={bodyWeight}
                  onChangeText={setBodyWeight}
                  keyboardType="decimal-pad"
                />
                <View style={styles.unitSelector}>
                  <TouchableOpacity
                    style={[
                      styles.unitButton,
                      weightUnit === 'lbs' && styles.unitButtonActive,
                    ]}
                    onPress={() => setWeightUnit('lbs')}
                  >
                    <Text
                      style={[
                        styles.unitText,
                        weightUnit === 'lbs' && styles.unitTextActive,
                      ]}
                    >
                      lbs
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[
                      styles.unitButton,
                      weightUnit === 'kg' && styles.unitButtonActive,
                    ]}
                    onPress={() => setWeightUnit('kg')}
                  >
                    <Text
                      style={[
                        styles.unitText,
                        weightUnit === 'kg' && styles.unitTextActive,
                      ]}
                    >
                      kg
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Notes</Text>
            <TextInput
              style={[styles.input, styles.notesInput]}
              placeholder="How are you feeling? Any pain or issues?"
              placeholderTextColor={colors.textMuted}
              value={notes}
              onChangeText={setNotes}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />
          </View>
        </ScrollView>
      </SafeAreaView>
    </Modal>
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
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: {
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
    color: colors.text,
  },
  cancelButton: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
  saveButton: {
    fontSize: fontSizes.md,
    color: colors.primary,
    fontWeight: fontWeights.bold,
  },
  content: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
  },
  section: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
    color: colors.text,
    marginBottom: spacing.md,
  },
  field: {
    marginBottom: spacing.md,
  },
  label: {
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  input: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
  },
  notesInput: {
    height: 100,
  },
  sorenessScale: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  sorenessButton: {
    width: 45,
    height: 45,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surfaceLight,
    borderWidth: 1,
    borderColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sorenessButtonActive: {
    backgroundColor: colors.assistant.actionSoft,
    borderColor: colors.assistant.borderStrong,
  },
  sorenessText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
    fontWeight: fontWeights.semibold,
  },
  sorenessTextActive: {
    color: colors.accent,
  },
  weightRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  weightInput: {
    flex: 1,
  },
  unitSelector: {
    flexDirection: 'row',
    borderRadius: borderRadius.lg,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
  },
  unitButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surfaceLight,
    justifyContent: 'center',
    alignItems: 'center',
    minWidth: 50,
  },
  unitButtonActive: {
    backgroundColor: colors.assistant.actionSoft,
  },
  unitText: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
    fontWeight: fontWeights.semibold,
  },
  unitTextActive: {
    color: colors.accent,
  },
});
