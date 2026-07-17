import React, { useState, useEffect } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  RefreshControl,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MainTabScreenProps } from '../../types/navigation';
import { Recipe } from '../../types/api';
import { recipesService } from '../../services/recipes';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { useToast } from '../../context/ToastContext';

type Props = MainTabScreenProps<'Recipes'>;

export default function RecipesScreen({ navigation }: Props) {
  const { showToast } = useToast();
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadRecipes();
  }, []);

  const loadRecipes = async () => {
    try {
      setLoading(true);
      const data = await recipesService.getAllRecipes();
      setRecipes(data);
    } catch (error) {
      console.error('Failed to load recipes:', error);
      showToast('error', 'Failed to load recipes');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadRecipes();
    setRefreshing(false);
  };

  const handleRecipePress = (recipe: Recipe) => {
    const ingredientsList = recipe.ingredients
      .map((ing, i) => {
        const amount = ing.quantity != null && ing.unit ? ` - ${ing.quantity} ${ing.unit}` : '';
        return `${i + 1}. ${ing.name}${amount}`;
      })
      .join('\n');

    const nutritionInfo = recipe.calories
      ? `\n\nNutrition (per serving):\nCalories: ${recipe.calories}cal\nProtein: ${recipe.protein}g\nCarbs: ${recipe.carbs}g\nFat: ${recipe.fats}g`
      : '';

    const prepTime = recipe.prep_time_minutes
      ? `\nPrep Time: ${recipe.prep_time_minutes} minutes`
      : '';

    Alert.alert(
      recipe.name,
      `${recipe.description || ''}\n\nServings: ${recipe.servings}${prepTime}\n\nIngredients:\n${ingredientsList}\n\nInstructions:\n${recipe.instructions}${nutritionInfo}`,
      [{ text: 'OK' }]
    );
  };

  const handleRecipeLongPress = (recipe: Recipe) => {
    Alert.alert(
      recipe.name,
      'Choose an action',
      [
        {
          text: 'Edit',
          onPress: () => {
            navigation.navigate('RecipeForm', {
              recipe: recipe,
              onSave: () => {
                loadRecipes();
              },
            });
          },
        },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () => handleDeleteRecipe(recipe),
        },
        { text: 'Cancel', style: 'cancel' },
      ]
    );
  };

  const handleDeleteRecipe = async (recipe: Recipe) => {
    Alert.alert(
      'Delete Recipe',
      `Are you sure you want to delete "${recipe.name}"?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await recipesService.deleteRecipe(recipe.id);
              await loadRecipes();
            } catch (error) {
              showToast('error', 'Failed to delete recipe');
            }
          },
        },
      ]
    );
  };

  const handleAddRecipe = () => {
    navigation.navigate('RecipeForm', {
      onSave: () => {
        loadRecipes();
      },
    });
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
      <ScrollView
        style={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        <View style={styles.header}>
          <Text style={styles.title}>Recipes</Text>
          <Text style={styles.subtitle}>Your personal recipe collection</Text>
        </View>

        <View style={styles.actions}>
          <TouchableOpacity style={styles.actionButton} onPress={handleAddRecipe}>
            <Text style={styles.actionButtonText}>+ Add Recipe</Text>
          </TouchableOpacity>
        </View>

        {recipes.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyIcon}>🍳</Text>
            <Text style={styles.emptyTitle}>No Recipes Yet</Text>
            <Text style={styles.emptyText}>
              Add your first recipe by tapping the button above, or ask Sara to help you save recipes!
            </Text>
          </View>
        ) : (
          <View style={styles.recipeList}>
            {recipes.map((recipe) => (
              <TouchableOpacity
                key={recipe.id}
                style={styles.recipeCard}
                onPress={() => handleRecipePress(recipe)}
                onLongPress={() => handleRecipeLongPress(recipe)}
              >
                <View style={styles.recipeHeader}>
                  <Text style={styles.recipeName}>{recipe.name}</Text>
                  {recipe.category && (
                    <Text style={styles.recipeCategory}>{recipe.category}</Text>
                  )}
                </View>
                {recipe.description && (
                  <Text style={styles.recipeDescription} numberOfLines={2}>
                    {recipe.description}
                  </Text>
                )}
                <View style={styles.recipeFooter}>
                  <Text style={styles.recipeInfo}>
                    🍽️ {recipe.servings} serving{recipe.servings > 1 ? 's' : ''}
                  </Text>
                  {recipe.prep_time_minutes && (
                    <Text style={styles.recipeInfo}>⏱️ {recipe.prep_time_minutes} min</Text>
                  )}
                  {recipe.calories && (
                    <Text style={styles.recipeInfo}>🔥 {Math.round(recipe.calories)} cal</Text>
                  )}
                </View>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </ScrollView>
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
  content: {
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
  actions: {
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.md,
  },
  actionButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
  },
  actionButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  emptyCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.xl,
    margin: spacing.lg,
    alignItems: 'center',
  },
  emptyIcon: {
    fontSize: 64,
    marginBottom: spacing.md,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
    marginBottom: spacing.sm,
  },
  emptyText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    textAlign: 'center',
  },
  recipeList: {
    padding: spacing.lg,
  },
  recipeCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  recipeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  recipeName: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  recipeCategory: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    textTransform: 'capitalize',
    marginLeft: spacing.sm,
  },
  recipeDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.sm,
  },
  recipeFooter: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  recipeInfo: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
});
