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
  KeyboardAvoidingView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { fitnessService, FoodItem } from '../../services/fitness';
import { IngredientItem } from '../../types/api';
import { colors, spacing, borderRadius, fontSizes, fontWeights } from '../../styles/theme';
import BarcodeScanner from './BarcodeScanner';

interface Props {
  visible: boolean;
  onClose: () => void;
  onAddIngredient: (ingredient: IngredientItem) => void;
  editIngredient?: IngredientItem | null;
}

export default function IngredientSearchModal({
  visible,
  onClose,
  onAddIngredient,
  editIngredient = null,
}: Props) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<FoodItem[]>([]);
  const [selectedFood, setSelectedFood] = useState<FoodItem | null>(null);
  const [quantity, setQuantity] = useState('1');
  const [unit, setUnit] = useState('serving');
  const [searching, setSearching] = useState(false);
  const [showManualEntry, setShowManualEntry] = useState(false);
  const [showBarcodeScanner, setShowBarcodeScanner] = useState(false);
  const [barcodeError, setBarcodeError] = useState<string | null>(null);
  // Never let an edit save stale/zero macros: block Add/Update until a
  // resolvable ingredient's fresh per-unit macros are fetched.
  const [isRehydrating, setIsRehydrating] = useState(false);

  // Manual entry fields
  const [manualName, setManualName] = useState('');
  const [manualQuantity, setManualQuantity] = useState('1');
  const [manualUnit, setManualUnit] = useState('serving');
  const [manualCalories, setManualCalories] = useState('');
  const [manualProtein, setManualProtein] = useState('');
  const [manualCarbs, setManualCarbs] = useState('');
  const [manualFats, setManualFats] = useState('');

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
      const foodResults = await fitnessService.searchFoods(searchQuery, 20);
      setSearchResults(foodResults);
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
    setBarcodeError(null);
  };

  // Rehydrate an ingredient row for editing. FatSecret-backed ingredients
  // re-fetch details to re-select the matching serving (falling back to the
  // stored line macros divided by quantity if that fails); manual/unresolved
  // ingredients reopen directly in the manual entry form.
  const prefillForEdit = async (ingredient: IngredientItem) => {
    const rawQty = ingredient.quantity;
    const qty = rawQty && rawQty > 0 ? rawQty : 1;

    if (ingredient.food_id && ingredient.source === 'fatsecret') {
      setIsRehydrating(true);
      setShowManualEntry(false);
      setQuantity(String(qty));
      setSearchQuery(ingredient.name || '');
      setSearchResults([]);

      let perUnitFood: FoodItem = {
        id: ingredient.food_id,
        name: ingredient.name || '',
        serving_size: 1,
        serving_unit: ingredient.serving_description || ingredient.unit || 'serving',
        calories: (ingredient.calories || 0) / qty,
        protein: (ingredient.protein || 0) / qty,
        carbs: (ingredient.carbs || 0) / qty,
        fats: (ingredient.fats || 0) / qty,
        is_custom: false,
        source: 'fatsecret',
      };
      setUnit(perUnitFood.serving_unit);

      try {
        const detail = await fitnessService.getFoodDetails(ingredient.food_id);
        const servings = (detail?.servings || []).filter(s => s && s.serving_description);
        const matched = servings.find(s => s.serving_description === ingredient.serving_description) || servings[0];
        if (matched) {
          perUnitFood = {
            ...perUnitFood,
            calories: matched.calories ?? perUnitFood.calories,
            protein: matched.protein ?? perUnitFood.protein,
            carbs: matched.carbs ?? perUnitFood.carbs,
            fats: matched.fat ?? perUnitFood.fats,
            serving_unit: matched.serving_description || perUnitFood.serving_unit,
          };
          setUnit(matched.serving_description || perUnitFood.serving_unit);
        }
      } catch (error) {
        console.error('Failed to rehydrate ingredient for edit, using stored macros:', error);
      }

      setSelectedFood(perUnitFood);
      setIsRehydrating(false);
    } else {
      // Manual/unresolved ingredient - reopen directly in the manual entry form.
      setShowManualEntry(true);
      setManualName(ingredient.name || '');
      setManualQuantity(String(qty));
      setManualUnit(ingredient.unit || 'serving');
      setManualCalories(ingredient.calories != null ? String(ingredient.calories) : '');
      setManualProtein(ingredient.protein != null ? String(ingredient.protein) : '');
      setManualCarbs(ingredient.carbs != null ? String(ingredient.carbs) : '');
      setManualFats(ingredient.fats != null ? String(ingredient.fats) : '');
    }
  };

  useEffect(() => {
    if (visible && editIngredient) {
      prefillForEdit(editIngredient);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, editIngredient]);

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
    resetForm();
    onClose();
  };

  const resetForm = () => {
    setSearchQuery('');
    setSelectedFood(null);
    setQuantity('1');
    setUnit('serving');
    setSearchResults([]);
    setShowManualEntry(false);
    setShowBarcodeScanner(false);
    setBarcodeError(null);
    resetManualFields();
  };

  const resetManualFields = () => {
    setManualName('');
    setManualQuantity('1');
    setManualUnit('serving');
    setManualCalories('');
    setManualProtein('');
    setManualCarbs('');
    setManualFats('');
  };

  // Macros scaled to the chosen quantity (shown in the preview + used on add).
  const scaled = (() => {
    const qty = parseFloat(quantity);
    if (!selectedFood || isNaN(qty) || qty <= 0) {
      return { calories: undefined, protein: undefined, carbs: undefined, fats: undefined } as {
        calories?: number; protein?: number; carbs?: number; fats?: number;
      };
    }
    return {
      calories: selectedFood.calories != null ? Math.round(selectedFood.calories * qty) : undefined,
      protein: selectedFood.protein != null ? parseFloat((selectedFood.protein * qty).toFixed(1)) : undefined,
      carbs: selectedFood.carbs != null ? parseFloat((selectedFood.carbs * qty).toFixed(1)) : undefined,
      fats: selectedFood.fats != null ? parseFloat((selectedFood.fats * qty).toFixed(1)) : undefined,
    };
  })();

  const handleAddFromSearch = () => {
    if (!selectedFood) {
      Alert.alert('Error', 'Please select a food item');
      return;
    }

    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) {
      Alert.alert('Error', 'Please enter a valid quantity');
      return;
    }

    const ingredient: IngredientItem = {
      name: selectedFood.name,
      quantity: qty,
      unit: unit,
      calories: scaled.calories,
      protein: scaled.protein,
      carbs: scaled.carbs,
      fats: scaled.fats,
      // Provenance so macros can be re-resolved/audited server-side (R1/R3)
      food_id: selectedFood.id,
      source: selectedFood.source === 'user' ? 'user' : 'fatsecret',
      serving_description: selectedFood.serving_unit,
    };

    onAddIngredient(ingredient);
    handleClose();
  };

  const handleAddManual = () => {
    if (!manualName.trim()) {
      Alert.alert('Error', 'Please enter an ingredient name');
      return;
    }

    const qty = parseFloat(manualQuantity);
    if (isNaN(qty) || qty <= 0) {
      Alert.alert('Error', 'Please enter a valid quantity');
      return;
    }

    const hasManualMacros = !!(manualCalories || manualProtein || manualCarbs || manualFats);
    const ingredient: IngredientItem = {
      name: manualName.trim(),
      quantity: qty,
      unit: manualUnit,
      calories: manualCalories ? parseFloat(manualCalories) : undefined,
      protein: manualProtein ? parseFloat(manualProtein) : undefined,
      carbs: manualCarbs ? parseFloat(manualCarbs) : undefined,
      fats: manualFats ? parseFloat(manualFats) : undefined,
      // Manual macros are provenance 'manual'; a name-only entry stays
      // unresolved so the backend estimates it against FatSecret on save.
      source: hasManualMacros ? 'manual' : undefined,
    };

    onAddIngredient(ingredient);
    handleClose();
  };

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
            <Text style={styles.title}>{editIngredient ? 'Edit Ingredient' : 'Add Ingredient'}</Text>
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
          {!showManualEntry ? (
            <>
              {/* Search Input with Barcode Button */}
              <View style={styles.searchRow}>
                <View style={styles.searchContainer}>
                  <TextInput
                    style={styles.searchInput}
                    value={searchQuery}
                    onChangeText={setSearchQuery}
                    placeholder="Search for ingredient..."
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
                            {food.source === 'user'
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

                  {/* Macros scaled to the chosen quantity, shown before adding */}
                  <Text style={styles.scaledHint}>
                    For {parseFloat(quantity) || 0} {unit}:
                  </Text>
                  <View style={styles.nutritionGrid}>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>{scaled.calories ?? '?'}</Text>
                      <Text style={styles.nutritionLabel}>Calories</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>{scaled.protein ?? '?'}g</Text>
                      <Text style={styles.nutritionLabel}>Protein</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>{scaled.carbs ?? '?'}g</Text>
                      <Text style={styles.nutritionLabel}>Carbs</Text>
                    </View>
                    <View style={styles.nutritionItem}>
                      <Text style={styles.nutritionValue}>{scaled.fats ?? '?'}g</Text>
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

                  {/* Add Button */}
                  <TouchableOpacity
                    style={[styles.addButton, isRehydrating && styles.addButtonDisabled]}
                    onPress={handleAddFromSearch}
                    disabled={isRehydrating}
                  >
                    {isRehydrating ? (
                      <ActivityIndicator size="small" color={colors.background} />
                    ) : (
                      <>
                        <Ionicons name="add" size={20} color={colors.background} />
                        <Text style={styles.addButtonText}>{editIngredient ? 'Update Ingredient' : 'Add Ingredient'}</Text>
                      </>
                    )}
                  </TouchableOpacity>
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

              <Text style={styles.label}>Ingredient Name *</Text>
              <TextInput
                style={styles.input}
                value={manualName}
                onChangeText={setManualName}
                placeholder="e.g., Chicken Breast"
                placeholderTextColor={colors.textMuted}
              />

              <View style={styles.row}>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Quantity *</Text>
                  <TextInput
                    style={styles.input}
                    value={manualQuantity}
                    onChangeText={setManualQuantity}
                    keyboardType="decimal-pad"
                    placeholder="1"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <View style={styles.halfWidth}>
                  <Text style={styles.label}>Unit</Text>
                  <TextInput
                    style={styles.input}
                    value={manualUnit}
                    onChangeText={setManualUnit}
                    placeholder="serving, cup, oz"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
              </View>

              <Text style={styles.sectionTitle}>Nutrition (optional)</Text>

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

              {/* Add Button */}
              <TouchableOpacity
                style={styles.addButton}
                onPress={handleAddManual}
              >
                <Ionicons name="add" size={20} color={colors.background} />
                <Text style={styles.addButtonText}>{editIngredient ? 'Update Ingredient' : 'Add Ingredient'}</Text>
              </TouchableOpacity>

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
        </ScrollView>
      </KeyboardAvoidingView>

      {/* Barcode Scanner Modal */}
      <BarcodeScanner
        visible={showBarcodeScanner}
        onClose={() => setShowBarcodeScanner(false)}
        onBarcodeScanned={handleBarcodeScanned}
      />
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
  scaledHint: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    fontWeight: fontWeights.semibold,
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
  addButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    minHeight: 48,
  },
  addButtonDisabled: {
    opacity: 0.6,
  },
  addButtonText: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.bold,
    color: colors.background,
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
});
