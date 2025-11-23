import apiClient from './api';
import { Recipe, IngredientItem } from '../types/api';

export interface RecipeCreate {
  name: string;
  description?: string;
  category?: string;
  ingredients: IngredientItem[];
  instructions: string;
  prep_time_minutes?: number;
  servings: number;
}

export interface RecipeUpdate {
  name?: string;
  description?: string;
  category?: string;
  ingredients?: IngredientItem[];
  instructions?: string;
  prep_time_minutes?: number;
  servings?: number;
}

class RecipesService {
  async getAllRecipes(category?: string): Promise<Recipe[]> {
    const params = category ? `?category=${encodeURIComponent(category)}` : '';
    return apiClient.get<Recipe[]>(`/api/fitness/recipes${params}`);
  }

  async getRecipe(id: string): Promise<Recipe> {
    return apiClient.get<Recipe>(`/api/fitness/recipes/${id}`);
  }

  async createRecipe(data: RecipeCreate): Promise<Recipe> {
    return apiClient.post<Recipe>('/api/fitness/recipes', data);
  }

  async updateRecipe(id: string, data: RecipeUpdate): Promise<Recipe> {
    return apiClient.patch<Recipe>(`/api/fitness/recipes/${id}`, data);
  }

  async deleteRecipe(id: string): Promise<void> {
    return apiClient.delete<void>(`/api/fitness/recipes/${id}`);
  }
}

export const recipesService = new RecipesService();
export default recipesService;
