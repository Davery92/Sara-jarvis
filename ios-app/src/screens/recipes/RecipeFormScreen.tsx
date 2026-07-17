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
import IngredientSearchModal from '../../components/fitness/IngredientSearchModal';

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
  const [showIngredientModal, setShowIngredientModal] = useState(false);

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

  const handleAddIngredient = (ingredient: IngredientItem) => {
    setIngredients([...ingredients, ingredient]);
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
                  onPress={() => setShowIngredientModal(true)}
                >
                  <Text style={styles.addButtonText}>+ Add</Text>
                </TouchableOpacity>
              </View>

              {ingredients.length === 0 ? (
                <Text style={styles.emptyIngredientsText}>
                  No ingredients added yet. Tap "+ Add" to search and add ingredients.
                </Text>
              ) : (
                ingredients.map((ingredient, index) => (
                  <View key={index} style={styles.ingredientRow}>
                    <View style={styles.ingredientInfo}>
                      <Text style={styles.ingredientText}>
                        {ingredient.quantity} {ingredient.unit} {ingredient.name}
                      </Text>
                      {(ingredient.calories || ingredient.protein || ingredient.carbs || ingredient.fats) && (
                        <Text style={styles.ingredientNutrition}>
                          {ingredient.calories ? `${ingredient.calories} cal` : ''}
                          {ingredient.protein ? ` • ${ingredient.protein}g P` : ''}
                          {ingredient.carbs ? ` • ${ingredient.carbs}g C` : ''}
                          {ingredient.fats ? ` • ${ingredient.fats}g F` : ''}
                        </Text>
                      )}
                    </View>
                    <TouchableOpacity
                      onPress={() => handleRemoveIngredient(index)}
                    >
                      <Text style={styles.removeText}>Remove</Text>
                    </TouchableOpacity>
                  </View>
                ))
              )}

              {/* Nutrition Summary */}
              {ingredients.length > 0 && ingredients.some(i => i.calories || i.protein || i.carbs || i.fats) && (
                <View style={styles.nutritionSummary}>
                  <Text style={styles.nutritionSummaryTitle}>Total Recipe Nutrition</Text>
                  <View style={styles.nutritionGrid}>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {Math.round(ingredients.reduce((sum, i) => sum + (i.calories || 0), 0))}
                      </Text>
                      <Text style={styles.nutritionLabel}>Calories</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {Math.round(ingredients.reduce((sum, i) => sum + (i.protein || 0), 0))}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Protein</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {Math.round(ingredients.reduce((sum, i) => sum + (i.carbs || 0), 0))}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Carbs</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {Math.round(ingredients.reduce((sum, i) => sum + (i.fats || 0), 0))}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Fat</Text>
                    </View>
                  </View>
                  {servings && parseInt(servings) > 0 && (
                    <Text style={styles.perServingText}>
                      Per serving ({servings} servings): {Math.round(ingredients.reduce((sum, i) => sum + (i.calories || 0), 0) / parseInt(servings))} cal
                    </Text>
                  )}
                </View>
              )}
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

      {/* Ingredient Search Modal */}
      <IngredientSearchModal
        visible={showIngredientModal}
        onClose={() => setShowIngredientModal(false)}
        onAddIngredient={handleAddIngredient}
      />
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
  emptyIngredientsText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
    textAlign: 'center',
    padding: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: 'dashed',
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
  ingredientInfo: {
    flex: 1,
    marginRight: spacing.sm,
  },
  ingredientText: {
    color: colors.text,
    fontSize: fontSizes.md,
  },
  ingredientNutrition: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  nutritionSummary: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  nutritionSummaryTitle: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    marginBottom: spacing.sm,
    textAlign: 'center',
  },
  nutritionGrid: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  nutritionItem: {
    alignItems: 'center',
  },
  nutritionValue: {
    color: colors.primary,
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
  nutritionLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  perServingText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    textAlign: 'center',
    marginTop: spacing.sm,
    fontStyle: 'italic',
  },
  removeText: {
    color: colors.error,
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
