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
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import { Picker } from '@react-native-picker/picker';
import {
  fitnessService,
  FoodItem,
  FoodServing,
  CreateFoodLogParams,
  Recipe,
} from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
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

interface EditEntry {
  id: string; // food_log row id (meal_log_id) for PUT
  meal_type: string;
  logged_at: string;
  notes?: string;
  // Raw canonical detailed_item for the single item being edited (see
  // FoodLogCreate in backend/app/routes/fitness.py).
  item: any;
  // The OTHER detailed_items in this meal, when it has more than one (see
  // FitnessScreen.handleEditFood). A PUT replaces the whole row's items, so
  // saving without these would silently drop every other item in the meal -
  // undefined/empty means single-item meal, nothing to preserve.
  siblingItems?: any[];
}

interface Props {
  visible: boolean;
  onClose: () => void;
  onComplete: () => void;
  initialMealType?: string;
  editEntry?: EditEntry | null;
}

export default function FoodLogModal({
  visible,
  onClose,
  onComplete,
  initialMealType = 'snack',
  editEntry = null,
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
  const [notes, setNotes] = useState('');

  // Date/Time picker state
  const [loggedDate, setLoggedDate] = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);

  // Unit picker state
  const [showUnitPicker, setShowUnitPicker] = useState(false);
  // Real serving options for the selected food (FatSecret/custom). When present,
  // the unit picker offers these instead of generic units, and each carries its
  // own macros — so "1/2 cup" vs "1 oz" just swaps numbers, no conversion math.
  const [availableServings, setAvailableServings] = useState<FoodServing[]>([]);
  const [selectedServingIdx, setSelectedServingIdx] = useState(0);

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

  // Never let an edit save zeros: block submit until the stored detailed_item
  // (which may be another client's minimal snapshot) is rehydrated with real macros.
  const [isRehydrating, setIsRehydrating] = useState(false);

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

  // Brand foods often list only "1 serving" with no gram/oz option. When any
  // real serving carries metric_serving_amount/unit, derive synthetic "g"/"oz"
  // (and "ml" for liquids) options so gram-based logging stays possible without
  // guessing at cross-unit math. Each synthetic option's macros are per-1-unit,
  // so it slots into the same applyServing()/quantity-multiplier path as a real
  // serving — quantity then just means "how many grams/oz".
  const buildSyntheticWeightServings = (servings: FoodServing[]): FoodServing[] => {
    const metricServing = servings.find((s) => s.metric_serving_amount && s.metric_serving_unit);
    if (!metricServing) return [];

    const unit = metricServing.metric_serving_unit!.toLowerCase().trim();
    const amount = metricServing.metric_serving_amount!;
    const cal = metricServing.calories || 0;
    const protein = metricServing.protein || 0;
    const carbs = metricServing.carbs || 0;
    const fat = metricServing.fat || 0;

    const synthetic: FoodServing[] = [];

    if (WEIGHT_UNITS.includes(unit)) {
      const amountInGrams = amount * (UNIT_CONVERSIONS[unit] || 1);
      if (amountInGrams > 0) {
        const perGram = {
          calories: cal / amountInGrams,
          protein: protein / amountInGrams,
          carbs: carbs / amountInGrams,
          fat: fat / amountInGrams,
        };
        synthetic.push({
          serving_id: 'synthetic-g',
          serving_description: 'g',
          metric_serving_amount: 1,
          metric_serving_unit: 'g',
          ...perGram,
        });
        const gramsPerOz = UNIT_CONVERSIONS['oz'];
        synthetic.push({
          serving_id: 'synthetic-oz',
          serving_description: 'oz',
          metric_serving_amount: 1,
          metric_serving_unit: 'oz',
          calories: perGram.calories * gramsPerOz,
          protein: perGram.protein * gramsPerOz,
          carbs: perGram.carbs * gramsPerOz,
          fat: perGram.fat * gramsPerOz,
        });
      }
    } else if (VOLUME_UNITS.includes(unit)) {
      const amountInMl = amount * (UNIT_CONVERSIONS[unit] || 1);
      if (amountInMl > 0) {
        synthetic.push({
          serving_id: 'synthetic-ml',
          serving_description: 'ml',
          metric_serving_amount: 1,
          metric_serving_unit: 'ml',
          calories: cal / amountInMl,
          protein: protein / amountInMl,
          carbs: carbs / amountInMl,
          fat: fat / amountInMl,
        });
      }
    }

    return synthetic;
  };

  // Apply one of the food's real serving options. qty then means "number of
  // these servings", so the conversion machinery's qty-multiplier path yields
  // exactly serving.macros * qty — no cross-unit math, no silent failure.
  const applyServing = (serving: FoodServing, idx: number) => {
    setSelectedServingIdx(idx);
    setUnit(serving.serving_description || 'serving');
    setBaseNutrition({
      calories: serving.calories || 0,
      protein: serving.protein || 0,
      carbs: serving.carbs || 0,
      fats: serving.fat || 0,
      perAmount: 1,
      perUnit: serving.serving_description || 'serving',
    });
  };

  // Rehydrate an edit target: fetch the food's servings (rebuilding the same
  // synthetic g/oz/ml options handleSelectFood would offer), re-select the
  // serving the entry was originally logged with, and recompute macros from it.
  // If the food_id doesn't resolve, fall back to a manual per-unit base derived
  // from the stored line macros so quantity edits still scale correctly.
  const prefillForEdit = async (entry: EditEntry) => {
    setIsRehydrating(true);
    const item = entry.item || {};
    const rawQty = typeof item.quantity === 'number' ? item.quantity : parseFloat(item.quantity);
    const qty = rawQty && rawQty > 0 ? rawQty : 1;

    setMealType(entry.meal_type || 'snack');
    setLoggedDate(entry.logged_at ? new Date(entry.logged_at) : new Date());
    setNotes(entry.notes || '');
    setQuantity(String(qty));
    setSearchQuery(item.name || '');
    setSearchResults([]);
    setSelectedFood({
      id: item.food_id || '',
      name: item.name || '',
      serving_size: 1,
      serving_unit: item.unit || 'serving',
      is_custom: item.source !== 'fatsecret',
      source: item.source || 'user',
    });

    if (item.food_id) {
      try {
        const detail = await fitnessService.getFoodDetails(item.food_id);
        const realServings = (detail?.servings || []).filter(s => s && s.serving_description);
        const synthetic = buildSyntheticWeightServings(realServings);
        const allServings = [...realServings, ...synthetic];

        let matchIdx = -1;
        if (item.serving_id) matchIdx = allServings.findIndex(s => s.serving_id === item.serving_id);
        if (matchIdx < 0 && item.serving_description) matchIdx = allServings.findIndex(s => s.serving_description === item.serving_description);
        if (matchIdx < 0 && item.unit) matchIdx = allServings.findIndex(s => s.serving_description === item.unit);
        if (matchIdx < 0 && allServings.length > 0) matchIdx = 0;

        if (matchIdx >= 0) {
          setAvailableServings(allServings);
          applyServing(allServings[matchIdx], matchIdx);
          setIsRehydrating(false);
          return;
        }
      } catch (error) {
        console.error('Failed to rehydrate food item for edit, falling back to manual:', error);
      }
    }

    // Not resolvable - build a manual per-unit base from the stored line macros.
    setAvailableServings([]);
    setSelectedServingIdx(0);
    setUnit(item.unit || 'serving');
    setBaseNutrition({
      calories: (item.calories || 0) / qty,
      protein: (item.protein || 0) / qty,
      carbs: (item.carbs || 0) / qty,
      fats: (item.fats || 0) / qty,
      perAmount: 1,
      perUnit: item.unit || 'serving',
    });
    setIsRehydrating(false);
  };

  useEffect(() => {
    if (visible && editEntry) {
      prefillForEdit(editEntry);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, editEntry]);

  const handleSelectFood = async (food: FoodItem) => {
    setSelectedFood(food);
    setSearchQuery(food.name);
    setSearchResults([]);
    setBarcodeError(null);
    setQuantity('1');
    setAvailableServings([]);
    setSelectedServingIdx(0);

    // Prefer the food's real serving options (each carries its own macros).
    if (food.id) {
      const detail = await fitnessService.getFoodDetails(food.id);
      const servings = (detail?.servings || []).filter(s => s && s.serving_description);
      if (servings.length > 0) {
        const synthetic = buildSyntheticWeightServings(servings);
        setAvailableServings([...servings, ...synthetic]);
        applyServing(servings[0], 0);
        return;
      }
    }

    // Fallback (custom/recipe/no serving list): parse the single serving string.
    const parsed = parseServingDescription(food.serving_unit);
    if (parsed) {
      setUnit(parsed.unit);
      setBaseNutrition({
        calories: food.calories || 0,
        protein: food.protein || 0,
        carbs: food.carbs || 0,
        fats: food.fats || 0,
        perAmount: parsed.amount,
        perUnit: parsed.unit,
      });
    } else {
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
    setNotes('');
    setShowUnitPicker(false);
    setBaseNutrition(null);
    setAvailableServings([]);
    setSelectedServingIdx(0);
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

    if (isRehydrating) {
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
          detailed_items: [{
            food_id: customFood.id,
            name: String(customFood.name || ''),
            source: 'user',
            serving_id: null,
            serving_description: String(customFood.serving_unit || 'serving'),
            quantity: qty,
            unit: String(customFood.serving_unit || 'serving'),
            calories: customFood.calories,
            protein: customFood.protein,
            carbs: customFood.carbs,
            fats: customFood.fats,
          }],
          calories: customFood.calories,
          protein: customFood.protein,
          carbs: customFood.carbs,
          fats: customFood.fats,
          notes: notes || undefined,
          logged_at: formatLocalDateTime(loggedDate),
        });
      } else if (selectedFood && displayNutrition) {
        // Use the pre-calculated displayNutrition which handles unit conversion
        const foodName = String(selectedFood.name || '');

        const editedFoodItem = { name: foodName, quantity: qty, unit: String(unit || 'serving') };
        const editedDetailedItem = {
          food_id: selectedFood.id,
          name: foodName,
          source: selectedFood.source,
          serving_id: availableServings[selectedServingIdx]?.serving_id ?? null,
          serving_description: String(unit || selectedFood.serving_unit || ''),
          quantity: qty,
          unit: String(unit || 'serving'),
          calories: displayNutrition.calories || undefined,
          protein: displayNutrition.protein || undefined,
          carbs: displayNutrition.carbs || undefined,
          fats: displayNutrition.fats || undefined,
        };

        // Editing one item of a multi-item meal: a PUT replaces the whole
        // row's items, so the other items must ride along or they're
        // silently dropped. Backend re-derives calories/protein/carbs/fats
        // from the sum of detailed_items, so the top-level numbers here only
        // need to be a reasonable snapshot, not an exact sum.
        const siblings = editEntry?.siblingItems ?? [];
        const allDetailedItems = [...siblings, editedDetailedItem];
        const allFoodItems = [
          ...siblings.map((s: any) => ({ name: s.name, quantity: s.quantity, unit: s.unit })),
          editedFoodItem,
        ];
        const siblingCalories = siblings.reduce((sum: number, s: any) => sum + (s.calories || 0), 0);
        const siblingProtein = siblings.reduce((sum: number, s: any) => sum + (s.protein || 0), 0);
        const siblingCarbs = siblings.reduce((sum: number, s: any) => sum + (s.carbs || 0), 0);
        const siblingFats = siblings.reduce((sum: number, s: any) => sum + (s.fats || 0), 0);

        const logData = {
          meal_type: String(mealType || 'snack'),
          food_items: allFoodItems,
          detailed_items: allDetailedItems,
          calories: siblingCalories + (displayNutrition.calories || 0),
          protein: siblingProtein + (displayNutrition.protein || 0),
          carbs: siblingCarbs + (displayNutrition.carbs || 0),
          fats: siblingFats + (displayNutrition.fats || 0),
          notes: notes || undefined,
          logged_at: formatLocalDateTime(loggedDate),
        };

        console.log('📤 Sending food log:', logData.meal_type, foodName, displayNutrition.calories, 'cal');
        if (editEntry) {
          await fitnessService.updateFoodLog(editEntry.id, logData);
        } else {
          await fitnessService.createFoodLog(logData);
        }
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
            <Text style={styles.title}>{editEntry ? 'Edit Food' : 'Log Food'}</Text>
            <TouchableOpacity onPress={handleClose} style={styles.closeButtonContainer}>
              <Ionicons name="close" size={fontSizes.xxl} color={colors.textSecondary} />
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
                <Ionicons name="calendar-outline" size={16} color={colors.accent} />
                <Text style={styles.dateTimeText}>
                  {loggedDate.toLocaleDateString()}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => setShowTimePicker(true)}
                style={[styles.dateTimeButton, { flex: 1 }]}
              >
                <Ionicons name="time-outline" size={16} color={colors.accent} />
                <Text style={styles.dateTimeText}>
                  {loggedDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
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
                  <Ionicons name="barcode-outline" size={24} color={colors.background} />
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
                      <Ionicons
                        name="time-outline"
                        size={14}
                        color={activeQuickTab === 'recent' ? colors.accent : colors.textSecondary}
                      />
                      <Text
                        style={[
                          styles.quickTabText,
                          activeQuickTab === 'recent' && styles.quickTabTextActive,
                        ]}
                      >
                        Recent ({recentFoods.length})
                      </Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.quickTab,
                        activeQuickTab === 'yesterday' && styles.quickTabActive,
                      ]}
                      onPress={() => setActiveQuickTab('yesterday')}
                    >
                      <Ionicons
                        name="calendar-outline"
                        size={14}
                        color={activeQuickTab === 'yesterday' ? colors.accent : colors.textSecondary}
                      />
                      <Text
                        style={[
                          styles.quickTabText,
                          activeQuickTab === 'yesterday' && styles.quickTabTextActive,
                        ]}
                      >
                        Yesterday ({yesterdayFoods.length})
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
                              <Ionicons name="add-circle" size={26} color={colors.primary} style={styles.quickFoodAdd} />
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
                              <Ionicons name="add-circle" size={26} color={colors.primary} style={styles.quickFoodAdd} />
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
                            {food.serving_unit ? `Per ${food.serving_unit} • ` : ''}
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
                        <Ionicons name="chevron-down" size={16} color={colors.textSecondary} />
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
                <Ionicons name="create-outline" size={16} color={colors.accent} />
                <Text style={styles.manualEntryText}>
                  Can't find it? Enter manually
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
                <Ionicons name="arrow-back" size={14} color={colors.accent} />
                <Text style={styles.backToSearchText}>Back to Search</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Notes */}
          <View style={styles.notesContainer}>
            <Text style={styles.notesLabel}>Notes (optional)</Text>
            <TextInput
              style={styles.notesInput}
              value={notes}
              onChangeText={setNotes}
              placeholder="Add a note..."
              placeholderTextColor={colors.textMuted}
              multiline
            />
          </View>

          {/* Submit Button */}
          <View style={styles.buttonContainer}>
            <TouchableOpacity
              style={[styles.submitButton, (loading || isRehydrating) && styles.submitButtonDisabled]}
              onPress={handleSubmit}
              disabled={loading || isRehydrating}
            >
              {loading || isRehydrating ? (
                <ActivityIndicator color={colors.background} />
              ) : (
                <>
                  <Ionicons name="checkmark-circle" size={20} color={colors.background} />
                  <Text style={styles.submitButtonText}>{editEntry ? 'Update Food' : 'Log Food'}</Text>
                </>
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
              <Text style={styles.pickerTitle}>
                {availableServings.length > 0 ? 'Select Serving' : 'Select Unit'}
              </Text>
              <TouchableOpacity onPress={() => setShowUnitPicker(false)}>
                <Text style={styles.pickerDone}>Done</Text>
              </TouchableOpacity>
            </View>
            <Picker
              selectedValue={availableServings.length > 0 ? String(selectedServingIdx) : unit}
              onValueChange={(value) => {
                if (availableServings.length > 0) {
                  const idx = parseInt(String(value), 10) || 0;
                  const s = availableServings[idx];
                  if (s) applyServing(s, idx);
                } else {
                  setUnit(value as string);
                }
              }}
              style={styles.picker}
              itemStyle={styles.pickerItem}
            >
              {availableServings.length > 0
                ? availableServings.map((s, index) => (
                    <Picker.Item
                      key={`serving-${index}`}
                      label={
                        s.serving_id?.startsWith('synthetic-')
                          ? s.serving_description
                          : `${s.serving_description}${s.calories != null ? ` — ${Math.round(s.calories)} cal` : ''}`
                      }
                      value={String(index)}
                    />
                  ))
                : COMMON_UNITS.map((u, index) => (
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
    borderBottomColor: colors.border,
  },
  title: {
    fontSize: fontSizes.xl,
    fontWeight: fontWeights.bold,
    color: colors.text,
  },
  closeButtonContainer: {
    padding: spacing.sm,
    minWidth: 44,
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
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
    borderRadius: borderRadius.full,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xs,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  mealTypeButtonActive: {
    borderColor: colors.assistant.borderStrong,
    backgroundColor: colors.assistant.actionSoft,
  },
  mealTypeEmoji: {
    fontSize: fontSizes.xl,
    marginBottom: spacing.xs,
  },
  mealTypeLabel: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    fontWeight: fontWeights.semibold,
  },
  mealTypeLabelActive: {
    color: colors.accent,
  },
  dateTimeSection: {
    gap: spacing.xs,
  },
  sectionLabel: {
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  dateTimeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  dateTimeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
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
    borderRadius: borderRadius.lg,
    width: 52,
    height: 52,
    justifyContent: 'center',
    alignItems: 'center',
  },
  errorContainer: {
    backgroundColor: colors.assistant.errorSoft,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.error,
  },
  errorText: {
    color: colors.error,
    fontSize: fontSizes.sm,
    textAlign: 'center',
  },
  searchInput: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
  },
  searchLoader: {
    position: 'absolute',
    right: spacing.md,
    top: spacing.md,
  },
  resultsContainer: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    maxHeight: 300,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  resultsList: {
    maxHeight: 300,
  },
  resultItem: {
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  resultInfo: {
    gap: spacing.xs,
  },
  resultName: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
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
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.md,
  },
  selectedFoodHeader: {
    gap: spacing.xs,
  },
  selectedFoodName: {
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
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
    borderColor: colors.divider,
  },
  nutritionItem: {
    alignItems: 'center',
  },
  nutritionValue: {
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
    color: colors.accent,
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
    fontWeight: fontWeights.semibold,
    color: colors.text,
  },
  notesContainer: {
    gap: spacing.xs,
    marginTop: spacing.md,
  },
  notesLabel: {
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
    color: colors.text,
  },
  notesInput: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    minHeight: 44,
    textAlignVertical: 'top',
  },
  quantityRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  quantityInput: {
    flex: 1,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    textAlign: 'center',
  },
  unitInput: {
    flex: 2,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
  },
  unitSelector: {
    flex: 2,
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  unitSelectorText: {
    fontSize: fontSizes.md,
    color: colors.text,
  },
  // Unit Picker Modal Styles
  pickerOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  pickerContainer: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    paddingBottom: spacing.xl,
  },
  pickerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  pickerTitle: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
    color: colors.text,
  },
  pickerCancel: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
  pickerDone: {
    fontSize: fontSizes.md,
    color: colors.accent,
    fontWeight: fontWeights.semibold,
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
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    borderStyle: 'dashed',
  },
  manualEntryText: {
    fontSize: fontSizes.sm,
    color: colors.accent,
    fontWeight: fontWeights.semibold,
  },
  manualForm: {
    gap: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    color: colors.text,
    marginTop: spacing.sm,
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
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  halfWidth: {
    flex: 1,
    gap: spacing.xs,
  },
  backToSearchButton: {
    flexDirection: 'row',
    padding: spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
  },
  backToSearchText: {
    fontSize: fontSizes.sm,
    color: colors.accent,
    fontWeight: fontWeights.semibold,
  },
  buttonContainer: {
    marginTop: spacing.md,
  },
  submitButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    minHeight: 48,
  },
  submitButtonDisabled: {
    opacity: 0.5,
  },
  submitButtonText: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    color: colors.background,
  },
  // Quick Add Styles
  quickAddContainer: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  quickTabHeader: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  quickTab: {
    flex: 1,
    flexDirection: 'row',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
  },
  quickTabActive: {
    backgroundColor: colors.assistant.actionSoft,
    borderBottomWidth: 2,
    borderBottomColor: colors.accent,
  },
  quickTabText: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    fontWeight: fontWeights.medium,
  },
  quickTabTextActive: {
    color: colors.accent,
    fontWeight: fontWeights.semibold,
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
    borderBottomColor: colors.divider,
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
    fontWeight: fontWeights.semibold,
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
    paddingHorizontal: spacing.sm,
  },
  mealTypeBadge: {
    backgroundColor: colors.surfaceLight,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.border,
  },
  mealTypeBadgeText: {
    fontSize: 10,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    fontWeight: fontWeights.semibold,
  },
  emptyText: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textAlign: 'center',
    padding: spacing.lg,
  },
});
