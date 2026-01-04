import apiClient from './api';

export interface FoodLog {
  id: string;  // Composite ID for UI uniqueness (meal_log_id-index)
  meal_log_id: string;  // Actual database UUID for deletion
  user_id: number;
  logged_at: string;
  meal_type: string;
  food_name: string;
  quantity: number;
  unit: string;
  calories?: number;
  protein?: number;
  carbs?: number;
  fat?: number;
  notes?: string;
}

export interface WorkoutLog {
  id: number;
  user_id: number;
  logged_at: string;
  workout_type: string;
  duration_minutes: number;
  intensity?: string;
  calories_burned?: number;
  notes?: string;
  exercises?: Exercise[];
}

export interface Exercise {
  name: string;
  sets?: number;
  reps?: number;
  weight?: number;
  duration_minutes?: number;
}

export interface RecoveryLog {
  id: string;
  user_id: string;
  log_date: string;  // YYYY-MM-DD format
  logged_at?: string;
  hrv?: number;  // Heart Rate Variability
  heart_rate?: number;
  sleep_hours?: number;
  soreness_level?: number;  // 1-10 scale
  body_weight?: number;
  weight_unit?: string;  // 'lbs' or 'kg'
  notes?: string;
  created_at?: string;
  updated_at?: string;
}

export interface HabitLog {
  id: number;
  user_id: number;
  habit_name: string;
  logged_at: string;
  completed: boolean;
  notes?: string;
}

export interface HabitStreak {
  habit_name: string;
  current_streak: number;
  longest_streak: number;
  total_completions: number;
  completion_rate: number;
}

export interface CreateFoodLogParams {
  meal_type: string;
  food_items: Array<{ name: string; quantity: number; unit: string }>;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
  notes?: string;
  logged_at?: string;  // ISO timestamp for when food was logged
}

export interface CreateWorkoutLogParams {
  workout_type: string;
  duration_minutes: number;
  intensity?: string;
  calories_burned?: number;
  notes?: string;
  exercises?: Exercise[];
}

export interface CreateRecoveryLogParams {
  log_date?: string;  // YYYY-MM-DD format (defaults to today)
  hrv?: number;  // Heart Rate Variability
  heart_rate?: number;
  sleep_hours?: number;
  soreness_level?: number;  // 1-10 scale
  body_weight?: number;
  weight_unit?: string;  // 'lbs' or 'kg'
  notes?: string;
}

export interface LogHabitParams {
  habit_name: string;
  completed: boolean;
  notes?: string;
}

export interface Phase {
  id: string;
  user_id: string;
  name: string;
  goal?: string;
  parent_phase_id?: string;
  start_date?: string;  // YYYY-MM-DD
  end_date?: string;    // YYYY-MM-DD
  status: 'planned' | 'active' | 'completed' | 'archived';
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface CreatePhaseParams {
  name: string;
  goal?: string;
  parent_phase_id?: string;
  start_date?: string;
  end_date?: string;
  notes?: string;
}

export interface UpdatePhaseParams {
  name?: string;
  goal?: string;
  start_date?: string;
  end_date?: string;
  status?: 'planned' | 'active' | 'completed' | 'archived';
  notes?: string;
}

export interface WorkoutTemplate {
  id: string;
  user_id: string;
  phase_id?: string;
  name: string;
  scheduled_days: string[];  // ["monday", "thursday", "saturday"]
  exercises: TemplateExercise[];
  order_in_phase?: number;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export interface TemplateExercise {
  name: string;
  sets?: number;
  reps?: string;  // "8-10" or "AMRAP"
  rpe_target?: number;  // 1-10 RPE scale
  rest_seconds?: number;
  notes?: string;
}

export interface CreateTemplateParams {
  name: string;
  phase_id?: string;
  scheduled_days?: string[];
  exercises?: TemplateExercise[];
  notes?: string;
}

export interface UpdateTemplateParams {
  name?: string;
  phase_id?: string;
  scheduled_days?: string[];
  exercises?: TemplateExercise[];
  notes?: string;
}

export interface NutritionGoals {
  calories: number;
  protein: number;
  carbs: number;
  fats: number;
}

export interface WorkoutSet {
  id: string;
  workout_id?: string;
  exercise_id: string;
  exercise_name?: string;
  set_index: number;
  weight: number;
  reps: number;
  rpe?: number;
  notes?: string;
  session_date?: string;  // YYYY-MM-DD format
  session_time?: string;  // Full ISO timestamp
  created_at: string;
}

export interface WorkoutSession {
  id: string;
  title: string;
  phase?: string;
  week?: number;
  day_of_week?: string;
  duration_min?: number;
  status: string;
  session_date?: string;
  created_at: string;
  exercises: WorkoutSet[];
}

export interface CreateWorkoutSetParams {
  exercise_name: string;
  set_index: number;
  weight: number;
  reps: number;
  rpe?: number;
  notes?: string;
  session_date?: string;  // YYYY-MM-DD format
  session_time?: string;  // Full ISO timestamp
}

export interface WeightSuggestion {
  suggested_weight: number;
  reasoning: string;
  confidence?: string;
}

export interface FoodItem {
  id: string;
  name: string;
  brand?: string;
  serving_size: number;
  serving_unit: string;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
  fiber?: number;
  sugar?: number;
  sodium?: number;
  is_custom: boolean;
  source: string;
}

export interface CreateCustomFoodParams {
  name: string;
  brand?: string;
  serving_size: number;
  serving_unit: string;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
  fiber?: number;
  sugar?: number;
  sodium?: number;
}

export interface IngredientItem {
  food_name: string;
  quantity: number;
  unit: string;
}

export interface Recipe {
  id: string;
  user_id: string;
  name: string;
  description?: string;
  category?: string;
  ingredients: IngredientItem[];
  instructions: string;
  prep_time_minutes?: number;
  servings: number;
  calories?: number;
  protein?: number;
  carbs?: number;
  fats?: number;
  created_at: string;
  updated_at: string;
}

class FitnessService {
  // Food Logs
  async getFoodLogs(startDate?: string, endDate?: string): Promise<FoodLog[]> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    // Backend returns meal logs with food_items as JSON array
    const mealLogs: any[] = await apiClient.get(`/api/fitness/food-log?${params}`);

    const foodLogs: FoodLog[] = [];
    mealLogs.forEach((meal) => {
      if (meal.food_items && Array.isArray(meal.food_items)) {
        // Check if this is a recipe - all detailed_items have source='recipe' with same recipe ID prefix
        const isRecipe = meal.detailed_items &&
          Array.isArray(meal.detailed_items) &&
          meal.detailed_items.length > 0 &&
          meal.detailed_items.every((item: any) => item.source === 'recipe');

        if (isRecipe && meal.food_items.length > 1) {
          // This is a recipe logged with ingredients - show as single recipe entry
          // Extract recipe name from the first detailed item's ID (format: recipe-UUID-ingredientName)
          const firstDetailedItem = meal.detailed_items[0];
          const recipeIdParts = firstDetailedItem.id?.split('-') || [];
          // Try to find recipe name, fallback to combined ingredient names
          const ingredientNames = meal.food_items.map((i: any) => i.name).join(', ');
          const displayName = `Recipe: ${ingredientNames.substring(0, 30)}${ingredientNames.length > 30 ? '...' : ''}`;

          foodLogs.push({
            id: meal.log_id,
            meal_log_id: meal.log_id,
            user_id: meal.user_id,
            logged_at: meal.logged_at,
            meal_type: meal.meal_type,
            food_name: displayName,
            quantity: 1,
            unit: 'serving',
            calories: Math.round(meal.calories || 0),
            protein: Math.round((meal.protein || 0) * 100) / 100,
            carbs: Math.round((meal.carbs || 0) * 100) / 100,
            fat: Math.round((meal.fats || 0) * 100) / 100,
            notes: meal.notes,
          });
        } else {
          // Regular food items - show each separately
          meal.food_items.forEach((item: any, index: number) => {
            foodLogs.push({
              id: `${meal.log_id}-${index}`,
              meal_log_id: meal.log_id,
              user_id: meal.user_id,
              logged_at: meal.logged_at,
              meal_type: meal.meal_type,
              food_name: item.name,
              quantity: item.quantity,
              unit: item.unit,
              // If single item, use full calories; if multiple non-recipe items, distribute
              calories: meal.food_items.length === 1
                ? Math.round(meal.calories || 0)
                : Math.round((meal.calories || 0) / meal.food_items.length),
              protein: meal.food_items.length === 1
                ? Math.round((meal.protein || 0) * 100) / 100
                : Math.round(((meal.protein || 0) / meal.food_items.length) * 100) / 100,
              carbs: meal.food_items.length === 1
                ? Math.round((meal.carbs || 0) * 100) / 100
                : Math.round(((meal.carbs || 0) / meal.food_items.length) * 100) / 100,
              fat: meal.food_items.length === 1
                ? Math.round((meal.fats || 0) * 100) / 100
                : Math.round(((meal.fats || 0) / meal.food_items.length) * 100) / 100,
              notes: meal.notes,
            });
          });
        }
      }
    });

    return foodLogs;
  }

  async createFoodLog(params: CreateFoodLogParams): Promise<FoodLog> {
    return await apiClient.post<FoodLog>('/api/fitness/food-log', params);
  }

  async deleteFoodLog(id: string): Promise<void> {
    await apiClient.delete(`/api/fitness/food-log/${id}`);
  }

  // Workout Logs
  async getWorkoutLogs(startDate?: string, endDate?: string): Promise<WorkoutLog[]> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response: any = await apiClient.get(`/api/fitness/workouts?${params}`);
    // Backend returns {workouts: [...], total: N}, extract the array
    return response.workouts || [];
  }

  // Workout Sessions (grouped sets)
  async getWorkoutSessions(startDate?: string, endDate?: string): Promise<WorkoutSession[]> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const response: any = await apiClient.get(`/api/fitness/workouts?${params}`);
    // Backend returns {workouts: [...], total: N}, workouts are now grouped sessions
    return response.workouts || [];
  }

  async createWorkoutLog(params: CreateWorkoutLogParams): Promise<WorkoutLog> {
    return await apiClient.post<WorkoutLog>('/api/fitness/workouts', params);
  }

  async deleteWorkoutLog(id: number): Promise<void> {
    await apiClient.delete(`/api/fitness/workouts/${id}`);
  }

  async deleteWorkoutSession(id: string): Promise<void> {
    // Delete workout session by UUID - this should cascade delete all associated workout_log entries
    await apiClient.delete(`/api/fitness/workouts/${id}`);
  }

  // Recovery Logs
  async getRecoveryLogs(startDate?: string, endDate?: string): Promise<RecoveryLog[]> {
    // Backend only has /recovery/recent/list endpoint, no date filtering
    return await apiClient.get<RecoveryLog[]>(`/api/fitness/recovery/recent/list`);
  }

  async createRecoveryLog(params: CreateRecoveryLogParams): Promise<RecoveryLog> {
    return await apiClient.post<RecoveryLog>('/api/fitness/recovery', params);
  }

  async deleteRecoveryLog(id: string | number): Promise<void> {
    await apiClient.delete(`/api/fitness/recovery/${id}`);
  }

  // Habits
  async getHabitLogs(startDate?: string, endDate?: string): Promise<HabitLog[]> {
    // No habits endpoint in backend yet
    return [];
  }

  async logHabit(params: LogHabitParams): Promise<HabitLog> {
    // No habits endpoint in backend yet
    throw new Error('Habits feature not implemented yet');
  }

  async getHabitStreaks(): Promise<HabitStreak[]> {
    // No habits endpoint in backend yet
    return [];
  }

  // Summary/Stats
  async getDailySummary(date?: string): Promise<any> {
    const params = date ? `?date=${date}` : '';
    return await apiClient.get(`/api/fitness/food-log/summary${params}`);
  }

  // Phases
  async getPhases(): Promise<{ phases: Phase[] }> {
    return await apiClient.get('/api/fitness/phases');
  }

  async getActivePhases(): Promise<{ phases: Phase[] }> {
    return await apiClient.get('/api/fitness/phases/active');
  }

  async createPhase(params: CreatePhaseParams): Promise<{ success: boolean; phase_id: string; message: string }> {
    return await apiClient.post('/api/fitness/phases', params);
  }

  async updatePhase(id: string, params: UpdatePhaseParams): Promise<{ success: boolean; message: string }> {
    return await apiClient.patch(`/api/fitness/phases/${id}`, params);
  }

  async deletePhase(id: string): Promise<{ success: boolean; message: string }> {
    return await apiClient.delete(`/api/fitness/phases/${id}`);
  }

  async activatePhase(id: string): Promise<{ success: boolean; message: string; summary: any }> {
    return await apiClient.post(`/api/fitness/phases/${id}/activate`, {});
  }

  // Templates
  async getTemplates(phaseId?: string): Promise<{ templates: WorkoutTemplate[] }> {
    const params = phaseId ? `?phase_id=${phaseId}` : '';
    return await apiClient.get(`/api/fitness/templates${params}`);
  }

  async getTodaysTemplates(): Promise<{ templates: WorkoutTemplate[] }> {
    return await apiClient.get('/api/fitness/templates/today');
  }

  async createTemplate(params: CreateTemplateParams): Promise<{ success: boolean; template_id: string; message: string }> {
    return await apiClient.post('/api/fitness/templates', params);
  }

  async updateTemplate(id: string, params: UpdateTemplateParams): Promise<{ success: boolean; message: string }> {
    return await apiClient.patch(`/api/fitness/templates/${id}`, params);
  }

  async deleteTemplate(id: string): Promise<{ success: boolean; message: string }> {
    return await apiClient.delete(`/api/fitness/templates/${id}`);
  }

  // Nutrition Goals
  async getNutritionGoals(): Promise<NutritionGoals> {
    return await apiClient.get<NutritionGoals>('/api/fitness/goals');
  }

  async updateNutritionGoals(goals: Partial<NutritionGoals>): Promise<{ success: boolean; message: string; goals: NutritionGoals }> {
    return await apiClient.put('/api/fitness/goals', goals);
  }

  // Workout Sets (for detailed workout logging)
  async getWorkoutSets(startDate?: string, endDate?: string): Promise<{ workouts: WorkoutSet[] }> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    return await apiClient.get(`/api/fitness/workouts?${params}`);
  }

  async createWorkoutSet(params: CreateWorkoutSetParams): Promise<WorkoutSet> {
    return await apiClient.post<WorkoutSet>('/api/fitness/workout-log', params);
  }

  async deleteWorkoutSet(id: string): Promise<void> {
    await apiClient.delete(`/api/fitness/workouts/${id}`);
  }

  async updateWorkoutSet(id: string, params: Partial<CreateWorkoutSetParams>): Promise<WorkoutSet> {
    return await apiClient.patch<WorkoutSet>(`/api/fitness/workout-log/${id}`, params);
  }

  // Weight Suggestions
  async getWeightSuggestion(
    exerciseName: string,
    templateId?: string,
    targetReps: number = 10
  ): Promise<WeightSuggestion> {
    const params = new URLSearchParams({
      exercise_name: exerciseName,
      target_reps: targetReps.toString(),
    });
    if (templateId) params.append('template_id', templateId);

    return await apiClient.get(`/api/fitness/weight-suggestion?${params}`);
  }

  // Food Database
  async searchFoods(query: string, limit: number = 20): Promise<FoodItem[]> {
    const params = new URLSearchParams({
      q: query,
      limit: limit.toString(),
    });
    return await apiClient.get(`/api/fitness/foods/search?${params}`);
  }

  async createCustomFood(params: CreateCustomFoodParams): Promise<FoodItem> {
    return await apiClient.post<FoodItem>('/api/fitness/foods', params);
  }

  // Recipes
  async getRecipes(category?: string): Promise<Recipe[]> {
    const params = category ? `?category=${category}` : '';
    return await apiClient.get<Recipe[]>(`/api/fitness/recipes${params}`);
  }

  // Recent Foods (frequently logged in last 30 days)
  async getRecentFoods(limit: number = 20): Promise<any[]> {
    try {
      const response: any = await apiClient.get(`/api/fitness/food-log/recent-foods?limit=${limit}`);
      return response.recent_foods || [];
    } catch (error) {
      console.error('Failed to fetch recent foods:', error);
      return [];
    }
  }

  // Yesterday's Foods
  async getYesterdayFoods(): Promise<{ meals: Record<string, any[]>; all_foods: any[] }> {
    try {
      return await apiClient.get('/api/fitness/food-log/yesterday');
    } catch (error) {
      console.error('Failed to fetch yesterday foods:', error);
      return { meals: {}, all_foods: [] };
    }
  }

  // Barcode lookup
  async lookupBarcode(barcode: string, region: string = 'US'): Promise<FoodItem | null> {
    try {
      const response: any = await apiClient.get(`/api/fitness/foods/barcode/${barcode}?region=${region}`);

      if (!response || !response.servings || response.servings.length === 0) {
        return null;
      }

      // Get the first serving as default
      const defaultServing = response.servings[0];

      return {
        id: response.id,
        name: response.name,
        brand: response.brand,
        serving_size: defaultServing.metric_serving_amount || 1,
        serving_unit: defaultServing.serving_description || 'serving',
        calories: defaultServing.calories,
        protein: defaultServing.protein,
        carbs: defaultServing.carbs,
        fats: defaultServing.fat,
        fiber: defaultServing.fiber,
        sugar: defaultServing.sugar,
        sodium: defaultServing.sodium,
        is_custom: false,
        source: 'fatsecret',
      };
    } catch (error: any) {
      if (error?.response?.status === 404) {
        return null; // Barcode not found
      }
      throw error;
    }
  }
}

export const fitnessService = new FitnessService();
export default fitnessService;
