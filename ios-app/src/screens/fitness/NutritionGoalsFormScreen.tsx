import React, { useState, useEffect } from 'react';
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
import { fitnessService, NutritionGoals } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

type Props = RootStackScreenProps<'NutritionGoalsForm'>;

export default function NutritionGoalsFormScreen({ route, navigation }: Props) {
  const onSave = route?.params?.onSave;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [calories, setCalories] = useState('');
  const [protein, setProtein] = useState('');
  const [carbs, setCarbs] = useState('');
  const [fats, setFats] = useState('');

  useEffect(() => {
    loadCurrentGoals();
  }, []);

  const loadCurrentGoals = async () => {
    try {
      setLoading(true);
      const goals = await fitnessService.getNutritionGoals();
      setCalories(goals.calories?.toString() || '2000');
      setProtein(goals.protein?.toString() || '150');
      setCarbs(goals.carbs?.toString() || '200');
      setFats(goals.fats?.toString() || '70');
    } catch (error) {
      console.error('Failed to load goals:', error);
      // Use defaults
      setCalories('2000');
      setProtein('150');
      setCarbs('200');
      setFats('70');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    const caloriesNum = parseInt(calories);
    const proteinNum = parseInt(protein);
    const carbsNum = parseInt(carbs);
    const fatsNum = parseInt(fats);

    if (isNaN(caloriesNum) || caloriesNum <= 0) {
      Alert.alert('Invalid Input', 'Please enter a valid calorie goal');
      return;
    }
    if (isNaN(proteinNum) || proteinNum < 0) {
      Alert.alert('Invalid Input', 'Please enter a valid protein goal');
      return;
    }
    if (isNaN(carbsNum) || carbsNum < 0) {
      Alert.alert('Invalid Input', 'Please enter a valid carbs goal');
      return;
    }
    if (isNaN(fatsNum) || fatsNum < 0) {
      Alert.alert('Invalid Input', 'Please enter a valid fat goal');
      return;
    }

    try {
      setSaving(true);
      await fitnessService.updateNutritionGoals({
        calories: caloriesNum,
        protein: proteinNum,
        carbs: carbsNum,
        fats: fatsNum,
      });

      if (onSave) {
        onSave();
      }

      navigation.goBack();
    } catch (error) {
      console.error('Failed to save goals:', error);
      Alert.alert('Error', 'Failed to save nutrition goals');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    navigation.goBack();
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <KeyboardAvoidingView
        style={styles.keyboardView}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView style={styles.scrollView}>
          {/* Header */}
          <View style={styles.header}>
            <Text style={styles.title}>Nutrition Goals</Text>
            <Text style={styles.subtitle}>Set your daily macro and calorie targets</Text>
          </View>

          {/* Form */}
          <View style={styles.form}>
            {/* Calories */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Daily Calories</Text>
              <TextInput
                style={styles.input}
                value={calories}
                onChangeText={setCalories}
                keyboardType="number-pad"
                placeholder="2000"
                placeholderTextColor={colors.textMuted}
              />
              <Text style={styles.hint}>Total calories per day</Text>
            </View>

            {/* Protein */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Protein (grams)</Text>
              <TextInput
                style={styles.input}
                value={protein}
                onChangeText={setProtein}
                keyboardType="number-pad"
                placeholder="150"
                placeholderTextColor={colors.textMuted}
              />
              <Text style={styles.hint}>4 calories per gram</Text>
            </View>

            {/* Carbs */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Carbohydrates (grams)</Text>
              <TextInput
                style={styles.input}
                value={carbs}
                onChangeText={setCarbs}
                keyboardType="number-pad"
                placeholder="200"
                placeholderTextColor={colors.textMuted}
              />
              <Text style={styles.hint}>4 calories per gram</Text>
            </View>

            {/* Fat */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Fat (grams)</Text>
              <TextInput
                style={styles.input}
                value={fats}
                onChangeText={setFats}
                keyboardType="number-pad"
                placeholder="70"
                placeholderTextColor={colors.textMuted}
              />
              <Text style={styles.hint}>9 calories per gram</Text>
            </View>
          </View>
        </ScrollView>

        {/* Buttons */}
        <View style={styles.buttons}>
          <TouchableOpacity
            style={[styles.button, styles.cancelButton]}
            onPress={handleCancel}
            disabled={saving}
          >
            <Text style={styles.cancelButtonText}>Cancel</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.button, styles.saveButton]}
            onPress={handleSave}
            disabled={saving}
          >
            {saving ? (
              <ActivityIndicator color={colors.text} />
            ) : (
              <Text style={styles.saveButtonText}>Save Goals</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  keyboardView: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  header: {
    padding: spacing.lg,
    paddingBottom: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  form: {
    padding: spacing.lg,
  },
  inputGroup: {
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
    fontSize: fontSizes.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  hint: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
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
  cancelButton: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  saveButton: {
    backgroundColor: colors.primary,
  },
  saveButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
});
