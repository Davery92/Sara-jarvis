import React, { useState, useEffect, useMemo } from 'react';
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
  KeyboardAvoidingView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import DateTimePicker from '@react-native-community/datetimepicker';
import { Picker } from '@react-native-picker/picker';
import {
  fitnessService,
  FoodItem,
  CreateFoodLogParams,
  Recipe,
} from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import BarcodeScanner from './BarcodeScanner';

// Unit conversion constants
const UNIT_CONVERSIONS: Record<string, number> = {
  // Weight units (base: grams)
  'g': 1,
  'gram': 1,
  'grams': 1,
  'oz': 28.3495,
  'ounce': 28.3495,
  'ounces': 28.3495,
  'lb': 453.592,
  'lbs': 453.592,
  'pound': 453.592,
  'pounds': 453.592,
  // Volume units (base: ml)
  'ml': 1,
  'milliliter': 1,
  'milliliters': 1,
  'cup': 240,
  'cups': 240,
  'tbsp': 15,
  'tablespoon': 15,
  'tablespoons': 15,
  'tsp': 5,
  'teaspoon': 5,
  'teaspoons': 5,
  'fl oz': 29.5735,
  'fluid oz': 29.5735,
  'fluid ounce': 29.5735,
  'fluid ounces': 29.5735,
};

const WEIGHT_UNITS = ['g', 'gram', 'grams', 'oz', 'ounce', 'ounces', 'lb', 'lbs', 'pound', 'pounds'];
const VOLUME_UNITS = ['ml', 'milliliter', 'milliliters', 'cup', 'cups', 'tbsp', 'tablespoon', 'tablespoons', 'tsp', 'teaspoon', 'teaspoons', 'fl oz', 'fluid oz', 'fluid ounce', 'fluid ounces'];

const COMMON_UNITS = [
  { label: 'serving', value: 'serving' },
  { label: 'g', value: 'g' },
  { label: 'oz', value: 'oz' },
  { label: 'cup', value: 'cup' },
  { label: 'tbsp', value: 'tbsp' },
  { label: 'tsp', value: 'tsp' },
  { label: 'ml', value: 'ml' },
  { label: 'fl oz', value: 'fl oz' },
  { label: 'lb', value: 'lb' },
  { label: 'piece', value: 'piece' },
  { label: 'slice', value: 'slice' },
];

// Parse serving description like "292g", "1 cup (185g)", "100 ml" into { amount, unit }
function parseServingDescription(description: string): { amount: number; unit: string } | null {
  if (!description) return null;

  const desc = description.toLowerCase().trim();

  // Pattern 1: "292g" or "100ml" (number directly followed by unit)
  const directMatch = desc.match(/^(\d+(?:\.\d+)?)\s*(g|gram|grams|oz|ounce|ounces|ml|cup|cups|tbsp|tsp|lb|lbs)$/i);
  if (directMatch) {
    return { amount: parseFloat(directMatch[1]), unit: directMatch[2] };
  }

  // Pattern 2: "1 cup (185g)" - extract the gram equivalent in parentheses
  const parenMatch = desc.match(/\((\d+(?:\.\d+)?)\s*(g|gram|grams|ml)\)/i);
  if (parenMatch) {
    return { amount: parseFloat(parenMatch[1]), unit: parenMatch[2] };
  }

  // Pattern 3: "100 g" or "8 oz" (number space unit)
  const spaceMatch = desc.match(/^(\d+(?:\.\d+)?)\s+(g|gram|grams|oz|ounce|ounces|ml|cup|cups|tbsp|tsp|lb|lbs|fl\s*oz)$/i);
  if (spaceMatch) {
    return { amount: parseFloat(spaceMatch[1]), unit: spaceMatch[2].replace(/\s+/g, ' ') };
  }

  return null;
}

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
  const [showBarcodeScanner, setShowBarcodeScanner] = useState(false);
  const [barcodeError, setBarcodeError] = useState<string | null>(null);

  // Date/Time picker state
  const [loggedDate, setLoggedDate] = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);

  // Unit picker state
  const [showUnitPicker, setShowUnitPicker] = useState(false);

  // Base nutrition for conversion calculations
  const [baseNutrition, setBaseNutrition] = useState<{
    calories: number;
    protein: number;
    carbs: number;
    fats: number;
    perAmount: number;
    perUnit: string;
  } | null>(null);

  // Manual entry fields
  const [manualName, setManualName] = useState('');
  const [manualBrand, setManualBrand] = useState('');
  const [manualServingSize, setManualServingSize] = useState('1');
  const [manualServingUnit, setManualServingUnit] = useState('serving');
  const [manualCalories, setManualCalories] = useState('');
  const [manualProtein, setManualProtein] = useState('');
  const [manualCarbs, setManualCarbs] = useState('');
  const [manualFats, setManualFats] = useState('');

  // Recent foods state
  const [recentFoods, setRecentFoods] = useState<any[]>([]);
  const [yesterdayFoods, setYesterdayFoods] = useState<any[]>([]);
  const [activeQuickTab, setActiveQuickTab] = useState<'recent' | 'yesterday'>('recent');
  const [loadingQuickFoods, setLoadingQuickFoods] = useState(true);

  useEffect(() => {
    if (initialMealType) {
      setMealType(initialMealType);
    }
  }, [initialMealType]);

  // Load recent and yesterday foods when modal opens
  useEffect(() => {
    if (visible) {
      loadQuickFoods();
    }
  }, [visible]);

  const loadQuickFoods = async () => {
    setLoadingQuickFoods(true);
    try {
      const [recent, yesterday] = await Promise.all([
        fitnessService.getRecentFoods(20),
        fitnessService.getYesterdayFoods(),
      ]);
      setRecentFoods(recent);
      setYesterdayFoods(yesterday.all_foods || []);
    } catch (error) {
      console.error('Failed to load quick foods:', error);
    } finally {
      setLoadingQuickFoods(false);
    }
  };

  const handleSelectQuickFood = (food: any) => {
    // Convert quick food to FoodItem format and select it
    const foodItem: FoodItem = {
      id: food.id || `quick-${Date.now()}`,
      name: food.name,
      brand: food.brand,
      serving_size: food.serving_size || 1,
      serving_unit: food.serving_unit || 'serving',
      calories: food.calories,
      protein: food.protein,
      carbs: food.carbs,
      fats: food.fats,
      is_custom: food.is_custom || false,
      source: food.source || 'recent',
    };
    handleSelectFood(foodItem);
  };

  useEffect(() => {
    // Don't trigger search if user already selected a food
    if (selectedFood) {
      setSearchResults([]);
      return;
    }
    if (searchQuery.length >= 2) {
      const timeoutId = setTimeout(() => {
        handleSearch();
      }, 500);
      return () => clearTimeout(timeoutId);
    } else {
      setSearchResults([]);
    }
  }, [searchQuery, selectedFood]);

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
    setSearchQuery(food.name);
    setSearchResults([]);
    setBarcodeError(null);

    // Try to parse the serving description to extract numeric amount and unit
    // E.g., "292g" -> { amount: 292, unit: 'g' }
    // E.g., "1 cup (185g)" -> { amount: 185, unit: 'g' }
    const parsed = parseServingDescription(food.serving_unit);

    if (parsed) {
      // We successfully parsed the serving - use the extracted unit
      console.log(`📊 Parsed serving "${food.serving_unit}" -> ${parsed.amount} ${parsed.unit}`);
      setUnit(parsed.unit);
      setBaseNutrition({
        calories: food.calories || 0,
        protein: food.protein || 0,
        carbs: food.carbs || 0,
        fats: food.fats || 0,
        perAmount: parsed.amount,
        perUnit: parsed.unit,
      });
      // Set initial quantity to 1 (user will type their amount in the chosen unit)
      setQuantity('1');
    } else {
      // Couldn't parse - treat as generic serving
      console.log(`📊 Couldn't parse serving "${food.serving_unit}", using as-is`);
      setUnit(food.serving_unit || 'serving');
      setBaseNutrition({
        calories: food.calories || 0,
        protein: food.protein || 0,
        carbs: food.carbs || 0,
        fats: food.fats || 0,
        perAmount: food.serving_size || 1,
        perUnit: food.serving_unit || 'serving',
      });
    }
  };

  const handleBarcodeScanned = async (barcode: string) => {
    setShowBarcodeScanner(false);
    setSearching(true);
    setBarcodeError(null);

    try {
      const food = await fitnessService.lookupBarcode(barcode);

      if (food) {
        handleSelectFood(food);
      } else {
        setBarcodeError(`No product found for barcode: ${barcode}`);
      }
    } catch (error: any) {
      console.error('Barcode lookup error:', error);
      setBarcodeError('Failed to look up barcode. Please try again.');
    } finally {
      setSearching(false);
    }
  };

  const handleClose = () => {
    setSearchQuery('');
    setSelectedFood(null);
    setQuantity('1');
    setUnit('serving');
    setSearchResults([]);
    setShowManualEntry(false);
    setShowBarcodeScanner(false);
    setBarcodeError(null);
    setLoggedDate(new Date());
    setShowUnitPicker(false);
    setBaseNutrition(null);
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

  // Calculate scaled nutrition based on quantity and unit conversion
  const displayNutrition = useMemo(() => {
    if (!baseNutrition || !selectedFood) {
      return null;
    }

    const qty = parseFloat(quantity) || 0;
    if (qty <= 0) {
      return { calories: 0, protein: 0, carbs: 0, fats: 0 };
    }

    const sourceUnit = baseNutrition.perUnit.toLowerCase().trim();
    const targetUnit = unit.toLowerCase().trim();

    // Check if units are convertible (same category)
    const sourceIsWeight = WEIGHT_UNITS.includes(sourceUnit);
    const targetIsWeight = WEIGHT_UNITS.includes(targetUnit);
    const sourceIsVolume = VOLUME_UNITS.includes(sourceUnit);
    const targetIsVolume = VOLUME_UNITS.includes(targetUnit);

    let multiplier = qty;
    let conversionType = 'none (using qty as multiplier)';

    if (sourceIsWeight && targetIsWeight) {
      // Both are weight units - convert
      const targetInGrams = qty * (UNIT_CONVERSIONS[targetUnit] || 1);
      const sourceInGrams = baseNutrition.perAmount * (UNIT_CONVERSIONS[sourceUnit] || 1);
      multiplier = targetInGrams / sourceInGrams;
      conversionType = `weight: ${qty} ${targetUnit} (${targetInGrams.toFixed(1)}g) / ${baseNutrition.perAmount} ${sourceUnit} (${sourceInGrams.toFixed(1)}g)`;
    } else if (sourceIsVolume && targetIsVolume) {
      // Both are volume units - convert
      const targetInMl = qty * (UNIT_CONVERSIONS[targetUnit] || 1);
      const sourceInMl = baseNutrition.perAmount * (UNIT_CONVERSIONS[sourceUnit] || 1);
      multiplier = targetInMl / sourceInMl;
      conversionType = `volume: ${qty} ${targetUnit} (${targetInMl.toFixed(1)}ml) / ${baseNutrition.perAmount} ${sourceUnit} (${sourceInMl.toFixed(1)}ml)`;
    }
    // If units are incompatible or non-convertible (serving, piece, slice), just use qty as multiplier

    console.log(`🧮 Nutrition calc: source="${sourceUnit}" (isWeight=${sourceIsWeight}, isVolume=${sourceIsVolume}), target="${targetUnit}" (isWeight=${targetIsWeight}, isVolume=${targetIsVolume})`);
    console.log(`🧮 Conversion: ${conversionType}, multiplier=${multiplier.toFixed(3)}`);
    console.log(`🧮 Result: ${baseNutrition.calories} * ${multiplier.toFixed(3)} = ${Math.round(baseNutrition.calories * multiplier)} cal`);

    return {
      calories: Math.round(baseNutrition.calories * multiplier),
      protein: parseFloat((baseNutrition.protein * multiplier).toFixed(1)),
      carbs: parseFloat((baseNutrition.carbs * multiplier).toFixed(1)),
      fats: parseFloat((baseNutrition.fats * multiplier).toFixed(1)),
    };
  }, [baseNutrition, selectedFood, quantity, unit]);

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
          meal_type: String(mealType || 'snack'),
          food_items: [{
            name: String(customFood.name || ''),
            quantity: qty,
            unit: String(customFood.serving_unit || 'serving'),
          }],
          calories: customFood.calories,
          protein: customFood.protein,
          carbs: customFood.carbs,
          fats: customFood.fats,
          logged_at: formatLocalDateTime(loggedDate),
        });
      } else if (selectedFood && displayNutrition) {
        // Use the pre-calculated displayNutrition which handles unit conversion
        const foodName = String(selectedFood.name || '');

        const logData = {
          meal_type: String(mealType || 'snack'),
          food_items: [{
            name: foodName,
            quantity: qty,
            unit: String(unit || 'serving'),
          }],
          calories: displayNutrition.calories || undefined,
          protein: displayNutrition.protein || undefined,
          carbs: displayNutrition.carbs || undefined,
          fats: displayNutrition.fats || undefined,
          logged_at: formatLocalDateTime(loggedDate),
        };

        console.log('📤 Sending food log:', logData.meal_type, foodName, displayNutrition.calories, 'cal');
        await fitnessService.createFoodLog(logData);
      }

      onComplete();
      handleClose();
    } catch (error: any) {
      // Avoid circular reference issues when logging axios errors
      let errorMessage = error?.response?.data?.detail || error?.message || 'Unknown error';
      // Handle Pydantic validation errors (array of objects)
      if (Array.isArray(errorMessage)) {
        errorMessage = errorMessage.map((e: any) => `${e.loc?.join('.')}: ${e.msg}`).join(', ');
      } else if (typeof errorMessage === 'object') {
        errorMessage = JSON.stringify(errorMessage);
      }
      console.error('Failed to log food:', errorMessage);
      if (error?.response?.status) {
        console.error('Status:', error.response.status);
      }
      Alert.alert('Error', `Failed to log food: ${errorMessage}`);
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
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 0}
      >
        <SafeAreaView edges={['top']} style={styles.safeArea}>
          <View style={styles.header}>
            <Text style={styles.title}>Log Food</Text>
            <TouchableOpacity onPress={handleClose} style={styles.closeButtonContainer}>
              <Text style={styles.closeButton}>✕</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>

        <ScrollView
          style={styles.content}
          contentContainerStyle={styles.contentContainer}
          keyboardShouldPersistTaps="handled"
        >
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
              {/* Search Input with Barcode Button */}
              <View style={styles.searchRow}>
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
                <TouchableOpacity
                  style={styles.barcodeButton}
                  onPress={() => setShowBarcodeScanner(true)}
                >
                  <Text style={styles.barcodeButtonText}>📷</Text>
                </TouchableOpacity>
              </View>

              {/* Barcode Error Message */}
              {barcodeError && (
                <View style={styles.errorContainer}>
                  <Text style={styles.errorText}>{barcodeError}</Text>
                </View>
              )}

              {/* Quick Add Section - Recent & Yesterday Foods */}
              {searchQuery.length < 2 && !selectedFood && (
                <View style={styles.quickAddContainer}>
                  {/* Tab Headers */}
                  <View style={styles.quickTabHeader}>
                    <TouchableOpacity
                      style={[
                        styles.quickTab,
                        activeQuickTab === 'recent' && styles.quickTabActive,
                      ]}
                      onPress={() => setActiveQuickTab('recent')}
                    >
                      <Text
                        style={[
                          styles.quickTabText,
                          activeQuickTab === 'recent' && styles.quickTabTextActive,
                        ]}
                      >
                        🕐 Recent ({recentFoods.length})
                      </Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.quickTab,
                        activeQuickTab === 'yesterday' && styles.quickTabActive,
                      ]}
                      onPress={() => setActiveQuickTab('yesterday')}
                    >
                      <Text
                        style={[
                          styles.quickTabText,
                          activeQuickTab === 'yesterday' && styles.quickTabTextActive,
                        ]}
                      >
                        📅 Yesterday ({yesterdayFoods.length})
                      </Text>
                    </TouchableOpacity>
                  </View>

                  {/* Tab Content */}
                  <View style={styles.quickTabContent}>
                    {loadingQuickFoods ? (
                      <ActivityIndicator size="small" color={colors.primary} style={{ padding: spacing.md }} />
                    ) : activeQuickTab === 'recent' ? (
                      recentFoods.length === 0 ? (
                        <Text style={styles.emptyText}>
                          No recent foods. Start logging to see your frequently used items here.
                        </Text>
                      ) : (
                        <ScrollView
                          style={styles.quickFoodsList}
                          nestedScrollEnabled={true}
                          showsVerticalScrollIndicator={false}
                        >
                          {recentFoods.map((food, idx) => (
                            <TouchableOpacity
                              key={`recent-${food.name}-${idx}`}
                              style={styles.quickFoodItem}
                              onPress={() => handleSelectQuickFood(food)}
                            >
                              <View style={styles.quickFoodInfo}>
                                <Text style={styles.quickFoodName} numberOfLines={1}>
                                  {food.name}
                                </Text>
                                <Text style={styles.quickFoodDetails}>
                                  {food.serving_size} {food.serving_unit}
                                  {food.calories && ` • ${Math.round(food.calories)} cal`}
                                  {food.protein && ` • ${Math.round(food.protein)}g protein`}
                                </Text>
                                <Text style={styles.quickFoodCount}>
                                  Logged {food.count}x in last 30 days
                                </Text>
                              </View>
                              <Text style={styles.quickFoodAdd}>+</Text>
                            </TouchableOpacity>
                          ))}
                        </ScrollView>
                      )
                    ) : (
                      yesterdayFoods.length === 0 ? (
                        <Text style={styles.emptyText}>No foods logged yesterday.</Text>
                      ) : (
                        <ScrollView
                          style={styles.quickFoodsList}
                          nestedScrollEnabled={true}
                          showsVerticalScrollIndicator={false}
                        >
                          {yesterdayFoods.map((food, idx) => (
                            <TouchableOpacity
                              key={`yesterday-${food.name}-${idx}`}
                              style={styles.quickFoodItem}
                              onPress={() => handleSelectQuickFood(food)}
                            >
                              <View style={styles.quickFoodInfo}>
                                <View style={styles.quickFoodNameRow}>
                                  <Text style={styles.quickFoodName} numberOfLines={1}>
                                    {food.name}
                                  </Text>
                                  <View style={styles.mealTypeBadge}>
                                    <Text style={styles.mealTypeBadgeText}>
                                      {food.meal_type}
                                    </Text>
                                  </View>
                                </View>
                                <Text style={styles.quickFoodDetails}>
                                  {food.serving_size} {food.serving_unit}
                                  {food.calories && ` • ${Math.round(food.calories)} cal`}
                                  {food.protein && ` • ${Math.round(food.protein)}g protein`}
                                </Text>
                              </View>
                              <Text style={styles.quickFoodAdd}>+</Text>
                            </TouchableOpacity>
                          ))}
                        </ScrollView>
                      )
                    )}
                  </View>
                </View>
              )}

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
                              : food.source === 'fatsecret'
                              ? '🟢 FatSecret'
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
                        {displayNutrition?.calories ?? selectedFood.calories ?? '?'}
                      </Text>
                      <Text style={styles.nutritionLabel}>Calories</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {displayNutrition?.protein ?? selectedFood.protein ?? '?'}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Protein</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {displayNutrition?.carbs ?? selectedFood.carbs ?? '?'}g
                      </Text>
                      <Text style={styles.nutritionLabel}>Carbs</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>
                        {displayNutrition?.fats ?? selectedFood.fats ?? '?'}g
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
                      <TouchableOpacity
                        style={styles.unitSelector}
                        onPress={() => setShowUnitPicker(true)}
                      >
                        <Text style={styles.unitSelectorText}>{unit}</Text>
                        <Text style={styles.unitSelectorIcon}>▼</Text>
                      </TouchableOpacity>
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
      </KeyboardAvoidingView>

      {/* Barcode Scanner Modal */}
      <BarcodeScanner
        visible={showBarcodeScanner}
        onClose={() => setShowBarcodeScanner(false)}
        onBarcodeScanned={handleBarcodeScanned}
      />

      {/* Unit Picker Modal */}
      <Modal
        visible={showUnitPicker}
        transparent
        animationType="slide"
        onRequestClose={() => setShowUnitPicker(false)}
      >
        <TouchableOpacity
          style={styles.pickerOverlay}
          activeOpacity={1}
          onPress={() => setShowUnitPicker(false)}
        >
          <View style={styles.pickerContainer}>
            <View style={styles.pickerHeader}>
              <TouchableOpacity onPress={() => setShowUnitPicker(false)}>
                <Text style={styles.pickerCancel}>Cancel</Text>
              </TouchableOpacity>
              <Text style={styles.pickerTitle}>Select Unit</Text>
              <TouchableOpacity onPress={() => setShowUnitPicker(false)}>
                <Text style={styles.pickerDone}>Done</Text>
              </TouchableOpacity>
            </View>
            <Picker
              selectedValue={unit}
              onValueChange={(value) => setUnit(value as string)}
              style={styles.picker}
              itemStyle={styles.pickerItem}
            >
              {COMMON_UNITS.map((u, index) => (
                <Picker.Item key={`unit-${index}`} label={u.label} value={u.value} />
              ))}
            </Picker>
          </View>
        </TouchableOpacity>
      </Modal>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  safeArea: {
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
  searchRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  searchContainer: {
    flex: 1,
    position: 'relative',
  },
  barcodeButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    width: 52,
    height: 52,
    justifyContent: 'center',
    alignItems: 'center',
  },
  barcodeButtonText: {
    fontSize: 24,
  },
  errorContainer: {
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
    borderRadius: borderRadius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.3)',
  },
  errorText: {
    color: '#ef4444',
    fontSize: fontSizes.sm,
    textAlign: 'center',
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
  unitSelector: {
    flex: 2,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    padding: spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  unitSelectorText: {
    fontSize: fontSizes.md,
    color: colors.text,
  },
  unitSelectorIcon: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
  },
  // Unit Picker Modal Styles
  pickerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  pickerContainer: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.lg,
    borderTopRightRadius: borderRadius.lg,
    paddingBottom: spacing.xl,
  },
  pickerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.background,
  },
  pickerTitle: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  pickerCancel: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
  pickerDone: {
    fontSize: fontSizes.md,
    color: colors.primary,
    fontWeight: '600',
  },
  picker: {
    height: 200,
    backgroundColor: colors.surface,
  },
  pickerItem: {
    fontSize: fontSizes.lg,
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
  // Quick Add Styles
  quickAddContainer: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    overflow: 'hidden',
  },
  quickTabHeader: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: colors.background,
  },
  quickTab: {
    flex: 1,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  quickTabActive: {
    backgroundColor: colors.background,
    borderBottomWidth: 2,
    borderBottomColor: colors.primary,
  },
  quickTabText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontWeight: '500',
  },
  quickTabTextActive: {
    color: colors.text,
    fontWeight: '600',
  },
  quickTabContent: {
    maxHeight: 200,
  },
  quickFoodsList: {
    maxHeight: 200,
  },
  quickFoodItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.background,
  },
  quickFoodInfo: {
    flex: 1,
    gap: 2,
  },
  quickFoodNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  quickFoodName: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    flex: 1,
  },
  quickFoodDetails: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  quickFoodCount: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  quickFoodAdd: {
    fontSize: fontSizes.xl,
    color: colors.primary,
    fontWeight: '700',
    paddingHorizontal: spacing.sm,
  },
  mealTypeBadge: {
    backgroundColor: colors.background,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  mealTypeBadgeText: {
    fontSize: 10,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    fontWeight: '600',
  },
  emptyText: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textAlign: 'center',
    padding: spacing.lg,
  },
});
