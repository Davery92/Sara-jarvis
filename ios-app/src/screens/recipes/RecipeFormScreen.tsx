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
import { recipesService } from '../../services/recipes';
import { Recipe, IngredientItem } from '../../types/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

type Props = RootStackScreenProps<'RecipeForm'>;

export default function RecipeFormScreen({ route, navigation }: Props) {
  const existingRecipe = route?.params?.recipe;
  const onSave = route?.params?.onSave;

  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [instructions, setInstructions] = useState('');
  const [prepTime, setPrepTime] = useState('');
  const [servings, setServings] = useState('');
  const [ingredients, setIngredients] = useState<IngredientItem[]>([]);

  useEffect(() => {
    if (existingRecipe) {
      setName(existingRecipe.name || '');
      setDescription(existingRecipe.description || '');
      setCategory(existingRecipe.category || '');
      setInstructions(existingRecipe.instructions || '');
      setPrepTime(existingRecipe.prep_time_minutes?.toString() || '');
      setServings(existingRecipe.servings?.toString() || '');
      setIngredients(existingRecipe.ingredients || []);
    }
  }, [existingRecipe]);

  const handleAddIngredient = () => {
    Alert.prompt(
      'Add Ingredient',
      'Enter ingredient details (name, quantity, unit)',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Add',
          onPress: (text) => {
            if (text) {
              const parts = text.split(',').map(p => p.trim());
              if (parts.length >= 3) {
                const newIngredient: IngredientItem = {
                  name: parts[0],
                  quantity: parseFloat(parts[1]) || 0,
                  unit: parts[2],
                };
                setIngredients([...ingredients, newIngredient]);
              } else {
                Alert.alert('Invalid Format', 'Please use format: name, quantity, unit');
              }
            }
          },
        },
      ],
      'plain-text',
      ''
    );
  };

  const handleRemoveIngredient = (index: number) => {
    setIngredients(ingredients.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    if (!name.trim()) {
      Alert.alert('Invalid Input', 'Please enter a recipe name');
      return;
    }

    if (!instructions.trim()) {
      Alert.alert('Invalid Input', 'Please enter cooking instructions');
      return;
    }

    const servingsNum = parseInt(servings);
    if (isNaN(servingsNum) || servingsNum <= 0) {
      Alert.alert('Invalid Input', 'Please enter a valid number of servings');
      return;
    }

    try {
      setSaving(true);

      const recipeData = {
        name: name.trim(),
        description: description.trim() || undefined,
        category: category.trim() || undefined,
        instructions: instructions.trim(),
        prep_time_minutes: prepTime ? parseInt(prepTime) : undefined,
        servings: servingsNum,
        ingredients: ingredients.length > 0 ? ingredients : undefined,
      };

      if (existingRecipe) {
        await recipesService.updateRecipe(existingRecipe.id, recipeData);
      } else {
        await recipesService.createRecipe(recipeData);
      }

      if (onSave) {
        onSave();
      }

      navigation.goBack();
    } catch (error) {
      console.error('Failed to save recipe:', error);
      Alert.alert('Error', 'Failed to save recipe');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    navigation.goBack();
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <KeyboardAvoidingView
        style={styles.keyboardView}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView style={styles.scrollView}>
          {/* Header */}
          <View style={styles.header}>
            <Text style={styles.title}>
              {existingRecipe ? 'Edit Recipe' : 'New Recipe'}
            </Text>
            <Text style={styles.subtitle}>
              {existingRecipe ? 'Update your recipe details' : 'Create a new recipe'}
            </Text>
          </View>

          {/* Form */}
          <View style={styles.form}>
            {/* Name */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Recipe Name *</Text>
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder="e.g., Chicken Stir Fry"
                placeholderTextColor={colors.textMuted}
              />
            </View>

            {/* Description */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Description</Text>
              <TextInput
                style={[styles.input, styles.textArea]}
                value={description}
                onChangeText={setDescription}
                placeholder="Brief description of the recipe"
                placeholderTextColor={colors.textMuted}
                multiline
                numberOfLines={3}
              />
            </View>

            {/* Category */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Category</Text>
              <TextInput
                style={styles.input}
                value={category}
                onChangeText={setCategory}
                placeholder="e.g., Dinner, Breakfast, Snack"
                placeholderTextColor={colors.textMuted}
              />
            </View>

            {/* Prep Time */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Prep Time (minutes)</Text>
              <TextInput
                style={styles.input}
                value={prepTime}
                onChangeText={setPrepTime}
                keyboardType="number-pad"
                placeholder="30"
                placeholderTextColor={colors.textMuted}
              />
            </View>

            {/* Servings */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Servings *</Text>
              <TextInput
                style={styles.input}
                value={servings}
                onChangeText={setServings}
                keyboardType="number-pad"
                placeholder="4"
                placeholderTextColor={colors.textMuted}
              />
            </View>

            {/* Ingredients */}
            <View style={styles.inputGroup}>
              <View style={styles.sectionHeader}>
                <Text style={styles.label}>Ingredients</Text>
                <TouchableOpacity
                  style={styles.addButton}
                  onPress={handleAddIngredient}
                >
                  <Text style={styles.addButtonText}>+ Add</Text>
                </TouchableOpacity>
              </View>

              {ingredients.map((ingredient, index) => (
                <View key={index} style={styles.ingredientRow}>
                  <Text style={styles.ingredientText}>
                    {ingredient.quantity} {ingredient.unit} {ingredient.name}
                  </Text>
                  <TouchableOpacity
                    onPress={() => handleRemoveIngredient(index)}
                  >
                    <Text style={styles.removeText}>Remove</Text>
                  </TouchableOpacity>
                </View>
              ))}
            </View>

            {/* Instructions */}
            <View style={styles.inputGroup}>
              <Text style={styles.label}>Instructions *</Text>
              <TextInput
                style={[styles.input, styles.textArea, styles.instructionsInput]}
                value={instructions}
                onChangeText={setInstructions}
                placeholder="Step-by-step cooking instructions"
                placeholderTextColor={colors.textMuted}
                multiline
                numberOfLines={6}
              />
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
              <Text style={styles.saveButtonText}>
                {existingRecipe ? 'Update Recipe' : 'Create Recipe'}
              </Text>
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
    fontSize: fontSizes.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  textArea: {
    minHeight: 80,
    textAlignVertical: 'top',
  },
  instructionsInput: {
    minHeight: 120,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  addButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.sm,
  },
  addButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  ingredientRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: borderRadius.sm,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  ingredientText: {
    color: colors.text,
    fontSize: fontSizes.md,
    flex: 1,
  },
  removeText: {
    color: '#FF6B6B',
    fontSize: fontSizes.sm,
    fontWeight: '600',
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
