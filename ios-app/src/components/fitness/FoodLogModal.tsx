import React, { useState, useEffect } from 'react';
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
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import DateTimePicker from '@react-native-community/datetimepicker';
import {
  fitnessService,
  FoodItem,
  CreateFoodLogParams,
  Recipe,
} from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface Props {
  visible: boolean;
  onClose: () => void;
  onComplete: () => void;
  initialMealType?: string;
}

export default function FoodLogModal({
  visible,
  onClose,
  onComplete,
  initialMealType = 'snack',
}: Props) {
  const [mealType, setMealType] = useState(initialMealType);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<FoodItem[]>([]);
  const [selectedFood, setSelectedFood] = useState<FoodItem | null>(null);
  const [quantity, setQuantity] = useState('1');
  const [unit, setUnit] = useState('serving');
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [showManualEntry, setShowManualEntry] = useState(false);

  // Date/Time picker state
  const [loggedDate, setLoggedDate] = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);

  // Manual entry fields
  const [manualName, setManualName] = useState('');
  const [manualBrand, setManualBrand] = useState('');
  const [manualServingSize, setManualServingSize] = useState('1');
  const [manualServingUnit, setManualServingUnit] = useState('serving');
  const [manualCalories, setManualCalories] = useState('');
  const [manualProtein, setManualProtein] = useState('');
  const [manualCarbs, setManualCarbs] = useState('');
  const [manualFats, setManualFats] = useState('');

  useEffect(() => {
    if (initialMealType) {
      setMealType(initialMealType);
    }
  }, [initialMealType]);

  useEffect(() => {
    if (searchQuery.length >= 2) {
      const timeoutId = setTimeout(() => {
        handleSearch();
      }, 500);
      return () => clearTimeout(timeoutId);
    } else {
      setSearchResults([]);
    }
  }, [searchQuery]);

  const handleSearch = async () => {
    if (searchQuery.length < 2) return;

    setSearching(true);
    try {
      // Search both foods and recipes in parallel
      const [foodResults, recipes] = await Promise.all([
        fitnessService.searchFoods(searchQuery, 20),
        fitnessService.getRecipes(),
      ]);

      // Filter recipes by search query (case-insensitive)
      const matchingRecipes = recipes.filter((recipe) =>
        recipe.name.toLowerCase().includes(searchQuery.toLowerCase())
      );

      // Convert recipes to FoodItem format for display
      const recipeAsFoods: FoodItem[] = matchingRecipes.map((recipe) => ({
        id: `recipe-${recipe.id}`,
        name: `${recipe.name} (Recipe)`,
        brand: recipe.category || undefined,
        serving_size: recipe.servings,
        serving_unit: 'serving',
        calories: recipe.calories,
        protein: recipe.protein,
        carbs: recipe.carbs,
        fats: recipe.fats,
        is_custom: true,
        source: 'recipe',
      }));

      // Separate custom foods from USDA foods
      const customFoods = foodResults.filter((food) => food.source === 'user');
      const usdaFoods = foodResults.filter((food) => food.source !== 'user');

      // Prioritize: Recipes first, then custom foods, then USDA foods
      setSearchResults([...recipeAsFoods, ...customFoods, ...usdaFoods]);
    } catch (error) {
      console.error('Failed to search foods:', error);
    } finally {
      setSearching(false);
    }
  };

  const handleSelectFood = (food: FoodItem) => {
    setSelectedFood(food);
    setUnit(food.serving_unit);
    setSearchQuery(food.name);
    setSearchResults([]);
  };

  const handleClose = () => {
    setSearchQuery('');
    setSelectedFood(null);
    setQuantity('1');
    setUnit('serving');
    setSearchResults([]);
    setShowManualEntry(false);
    setLoggedDate(new Date());
    resetManualFields();
    onClose();
  };

  const resetManualFields = () => {
    setManualName('');
    setManualBrand('');
    setManualServingSize('1');
    setManualServingUnit('serving');
    setManualCalories('');
    setManualProtein('');
    setManualCarbs('');
    setManualFats('');
  };

  // Format date in local timezone without converting to UTC
  const formatLocalDateTime = (date: Date): string => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`;
  };

  const handleSubmit = async () => {
    if (!selectedFood && !showManualEntry) {
      Alert.alert('Error', 'Please select a food or enter manually');
      return;
    }

    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) {
      Alert.alert('Error', 'Please enter a valid quantity');
      return;
    }

    setLoading(true);
    try {
      if (showManualEntry) {
        // Create custom food first
        const customFood = await fitnessService.createCustomFood({
          name: manualName,
          brand: manualBrand || undefined,
          serving_size: parseFloat(manualServingSize) || 1,
          serving_unit: manualServingUnit,
          calories: manualCalories ? parseFloat(manualCalories) : undefined,
          protein: manualProtein ? parseFloat(manualProtein) : undefined,
          carbs: manualCarbs ? parseFloat(manualCarbs) : undefined,
          fats: manualFats ? parseFloat(manualFats) : undefined,
        });

        // Log the custom food
        await fitnessService.createFoodLog({
          meal_type: mealType,
          food_items: [{
            name: customFood.name,
            quantity: qty,
            unit: customFood.serving_unit,
          }],
          calories: customFood.calories,
          protein: customFood.protein,
          carbs: customFood.carbs,
          fats: customFood.fats,
          logged_at: formatLocalDateTime(loggedDate),
        });
      } else if (selectedFood) {
        // For recipes, nutrition is already per serving, just multiply by quantity
        // For other foods, use the serving size ratio
        const multiplier = qty;

        await fitnessService.createFoodLog({
          meal_type: mealType,
          food_items: [{
            name: selectedFood.name,
            quantity: qty,
            unit: unit,
          }],
          calories: selectedFood.calories ? Math.round(selectedFood.calories * multiplier) : undefined,
          protein: selectedFood.protein ? parseFloat((selectedFood.protein * multiplier).toFixed(1)) : undefined,
          carbs: selectedFood.carbs ? parseFloat((selectedFood.carbs * multiplier).toFixed(1)) : undefined,
          fats: selectedFood.fats ? parseFloat((selectedFood.fats * multiplier).toFixed(1)) : undefined,
          logged_at: formatLocalDateTime(loggedDate),
        });
      }

      onComplete();
      handleClose();
    } catch (error) {
      console.error('Failed to log food:', error);
      Alert.alert('Error', 'Failed to log food');
    } finally {
      setLoading(false);
    }
  };

  const mealTypes = [
    { value: 'breakfast', label: 'Breakfast', emoji: '🌅' },
    { value: 'lunch', label: 'Lunch', emoji: '☀️' },
    { value: 'dinner', label: 'Dinner', emoji: '🌙' },
    { value: 'snack', label: 'Snack', emoji: '🍎' },
  ];

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={handleClose}
      presentationStyle="pageSheet"
    >
      <View style={styles.container}>
        <SafeAreaView edges={['top']}>
          <View style={styles.header}>
            <Text style={styles.title}>Log Food</Text>
            <TouchableOpacity onPress={handleClose} style={styles.closeButtonContainer}>
              <Text style={styles.closeButton}>✕</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>

        <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
          {/* Meal Type Selector */}
          <View style={styles.mealTypeContainer}>
            {mealTypes.map((meal) => (
              <TouchableOpacity
                key={meal.value}
                style={[
                  styles.mealTypeButton,
                  mealType === meal.value && styles.mealTypeButtonActive,
                ]}
                onPress={() => setMealType(meal.value)}
              >
                <Text style={styles.mealTypeEmoji}>{meal.emoji}</Text>
                <Text
                  style={[
                    styles.mealTypeLabel,
                    mealType === meal.value && styles.mealTypeLabelActive,
                  ]}
                >
                  {meal.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Date/Time Picker */}
          <View style={styles.dateTimeSection}>
            <Text style={styles.sectionLabel}>When did you eat this?</Text>
            <View style={styles.dateTimeRow}>
              <TouchableOpacity
                onPress={() => setShowDatePicker(true)}
                style={[styles.dateTimeButton, { flex: 1, marginRight: spacing.sm }]}
              >
                <Text style={styles.dateTimeText}>
                  📅 {loggedDate.toLocaleDateString()}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => setShowTimePicker(true)}
                style={[styles.dateTimeButton, { flex: 1 }]}
              >
                <Text style={styles.dateTimeText}>
                  🕐 {loggedDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          {showDatePicker && (
            <DateTimePicker
              value={loggedDate}
              mode="date"
              display={Platform.OS === 'ios' ? 'spinner' : 'default'}
              onChange={(event, selectedDate) => {
                setShowDatePicker(Platform.OS === 'ios');
                if (selectedDate) {
                  // Preserve the time from current loggedDate
                  const newDate = new Date(selectedDate);
                  newDate.setHours(loggedDate.getHours());
                  newDate.setMinutes(loggedDate.getMinutes());
                  newDate.setSeconds(loggedDate.getSeconds());
                  setLoggedDate(newDate);
                }
              }}
            />
          )}

          {showTimePicker && (
            <DateTimePicker
              value={loggedDate}
              mode="time"
              display={Platform.OS === 'ios' ? 'spinner' : 'default'}
              onChange={(event, selectedTime) => {
                setShowTimePicker(Platform.OS === 'ios');
                if (selectedTime) {
                  // Preserve the date from current loggedDate
                  const newDate = new Date(loggedDate);
                  newDate.setHours(selectedTime.getHours());
                  newDate.setMinutes(selectedTime.getMinutes());
                  newDate.setSeconds(selectedTime.getSeconds());
                  setLoggedDate(newDate);
                }
              }}
            />
          )}

          {!showManualEntry ? (
            <>
              {/* Search Input */}
              <View style={styles.searchContainer}>
                <TextInput
                  style={styles.searchInput}
                  value={searchQuery}
                  onChangeText={setSearchQuery}
                  placeholder="Search for food..."
                  placeholderTextColor={colors.textMuted}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
                {searching && (
                  <ActivityIndicator
                    size="small"
                    color={colors.primary}
                    style={styles.searchLoader}
                  />
                )}
              </View>

              {/* Search Results Dropdown */}
              {searchResults.length > 0 && (
                <View style={styles.resultsContainer}>
                  <ScrollView
                    style={styles.resultsList}
                    nestedScrollEnabled={true}
                    keyboardShouldPersistTaps="handled"
                  >
                    {searchResults.map((food) => (
                      <TouchableOpacity
                        key={food.id}
                        style={styles.resultItem}
                        onPress={() => handleSelectFood(food)}
                      >
                        <View style={styles.resultInfo}>
                          <Text style={styles.resultName}>{food.name}</Text>
                          {food.brand && (
                            <Text style={styles.resultBrand}>{food.brand}</Text>
                          )}
                          <Text style={styles.resultDetails}>
                            {food.calories || '?'} cal • {food.protein || '?'}g protein •{' '}
                            {food.source === 'recipe'
                              ? '🍽️ Recipe'
                              : food.source === 'user'
                              ? '⭐ Custom'
                              : '🇺🇸 USDA'}
                          </Text>
                        </View>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>
                </View>
              )}

              {/* Selected Food */}
              {selectedFood && (
                <View style={styles.selectedFoodContainer}>
                  <View style={styles.selectedFoodHeader}>
                    <Text style={styles.selectedFoodName}>{selectedFood.name}</Text>
                    {selectedFood.brand && (
                      <Text style={styles.selectedFoodBrand}>{selectedFood.brand}</Text>
                    )}
                  </View>

                  <View style={styles.nutritionGrid}>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {selectedFood.calories || '?'}
                      </Text>
                      <Text style={styles.nutritionLabel}>Calories</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {selectedFood.protein || '?'}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Protein</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {selectedFood.carbs || '?'}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Carbs</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {selectedFood.fats || '?'}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Fat</Text>
                    </View>
                  </View>

                  <View style={styles.quantityContainer}>
                    <Text style={styles.label}>Quantity</Text>
                    <View style={styles.quantityRow}>
                      <TextInput
                        style={styles.quantityInput}
                        value={quantity}
                        onChangeText={setQuantity}
                        keyboardType="decimal-pad"
                      />
                      <TextInput
                        style={styles.unitInput}
                        value={unit}
                        onChangeText={setUnit}
                      />
                    </View>
                  </View>
                </View>
              )}

              {/* Manual Entry Button */}
              <TouchableOpacity
                style={styles.manualEntryButton}
                onPress={() => setShowManualEntry(true)}
              >
                <Text style={styles.manualEntryText}>
                  ✏️ Can't find it? Enter manually
                </Text>
              </TouchableOpacity>
            </>
          ) : (
            /* Manual Entry Form */
            <View style={styles.manualForm}>
              <Text style={styles.sectionTitle}>Manual Entry</Text>

              <Text style={styles.label}>Food Name *</Text>
              <TextInput
                style={styles.input}
                value={manualName}
                onChangeText={setManualName}
                placeholder="e.g., Homemade Chicken Salad"
                placeholderTextColor={colors.textMuted}
              />

              <Text style={styles.label}>Brand (optional)</Text>
              <TextInput
                style={styles.input}
                value={manualBrand}
                onChangeText={setManualBrand}
                placeholder="e.g., Trader Joe's"
                placeholderTextColor={colors.textMuted}
              />

              <View style={styles.row}>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Serving Size</Text>
                  <TextInput
                    style={styles.input}
                    value={manualServingSize}
                    onChangeText={setManualServingSize}
                    keyboardType="decimal-pad"
                  />
                </View>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Unit</Text>
                  <TextInput
                    style={styles.input}
                    value={manualServingUnit}
                    onChangeText={setManualServingUnit}
                    placeholder="serving, cup, oz"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>

              <Text style={styles.sectionTitle}>Nutrition (per serving)</Text>

              <View style={styles.row}>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Calories</Text>
                  <TextInput
                    style={styles.input}
                    value={manualCalories}
                    onChangeText={setManualCalories}
                    keyboardType="numeric"
                    placeholder="0"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Protein (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={manualProtein}
                    onChangeText={setManualProtein}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>

              <View style={styles.row}>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Carbs (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={manualCarbs}
                    onChangeText={setManualCarbs}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Fat (g)</Text>
                  <TextInput
                    style={styles.input}
                    value={manualFats}
                    onChangeText={setManualFats}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>

              <TouchableOpacity
                style={styles.backToSearchButton}
                onPress={() => {
                  setShowManualEntry(false);
                  resetManualFields();
                }}
              >
                <Text style={styles.backToSearchText}>← Back to Search</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Submit Button */}
          <View style={styles.buttonContainer}>
            <TouchableOpacity
              style={[styles.submitButton, loading && styles.submitButtonDisabled]}
              onPress={handleSubmit}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color={colors.text} />
              ) : (
                <Text style={styles.submitButtonText}>Log Food</Text>
              )}
            </TouchableOpacity>
          </View>
        </ScrollView>
      </View>
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
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.surface,
  },
  title: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
  },
  closeButtonContainer: {
    padding: spacing.sm,
    minWidth: 44,
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButton: {
    fontSize: fontSizes.xxl,
    color: colors.textSecondary,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    padding: spacing.md,
    gap: spacing.md,
  },
  mealTypeContainer: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  mealTypeButton: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: colors.surface,
  },
  mealTypeButtonActive: {
    borderColor: colors.primary,
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
  },
  mealTypeEmoji: {
    fontSize: fontSizes.xl,
    marginBottom: spacing.xs,
  },
  mealTypeLabel: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    fontWeight: '600',
  },
  mealTypeLabelActive: {
    color: colors.primary,
  },
  dateTimeSection: {
    gap: spacing.xs,
  },
  sectionLabel: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  dateTimeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  dateTimeButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.surface,
  },
  dateTimeText: {
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
  },
  searchContainer: {
    position: 'relative',
  },
  searchInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.surface,
  },
  searchLoader: {
    position: 'absolute',
    right: spacing.md,
    top: spacing.md,
  },
  resultsContainer: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    maxHeight: 300,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  resultsList: {
    maxHeight: 300,
  },
  resultItem: {
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.background,
  },
  resultInfo: {
    gap: spacing.xs,
  },
  resultName: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  resultBrand: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  resultDetails: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  selectedFoodContainer: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    gap: spacing.md,
  },
  selectedFoodHeader: {
    gap: spacing.xs,
  },
  selectedFoodName: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
  },
  selectedFoodBrand: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  nutritionGrid: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.background,
  },
  nutritionItem: {
    alignItems: 'center',
  },
  nutritionValue: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.primary,
  },
  nutritionLabel: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: spacing.xs,
  },
  quantityContainer: {
    gap: spacing.xs,
  },
  label: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
  },
  quantityRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  quantityInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    textAlign: 'center',
  },
  unitInput: {
    flex: 2,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
  },
  manualEntryButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.primary,
    borderStyle: 'dashed',
  },
  manualEntryText: {
    fontSize: fontSizes.sm,
    color: colors.primary,
    fontWeight: '600',
  },
  manualForm: {
    gap: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.md,
    fontWeight: '700',
    color: colors.text,
    marginTop: spacing.sm,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.surface,
  },
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  halfWidth: {
    flex: 1,
    gap: spacing.xs,
  },
  backToSearchButton: {
    padding: spacing.sm,
    alignItems: 'center',
  },
  backToSearchText: {
    fontSize: fontSizes.sm,
    color: colors.primary,
    fontWeight: '600',
  },
  buttonContainer: {
    marginTop: spacing.md,
  },
  submitButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    minHeight: 48,
    justifyContent: 'center',
  },
  submitButtonDisabled: {
    opacity: 0.5,
  },
  submitButtonText: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
});
