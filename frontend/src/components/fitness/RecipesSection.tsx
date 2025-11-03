import React, { useState, useEffect } from 'react'
import { Plus, Search, Filter, ChefHat } from 'lucide-react'
import { APP_CONFIG } from '../../config'
import RecipeCard from './RecipeCard'
import RecipeEditor from './RecipeEditor'

interface IngredientItem {
  name: string
  quantity: number
  unit: string
  calories?: number
  protein?: number
  carbs?: number
  fats?: number
}

export interface Recipe {
  id: string
  user_id: string
  name: string
  description?: string
  category?: string
  ingredients: IngredientItem[]
  instructions: string
  prep_time_minutes?: number
  servings: number
  calories?: number
  protein?: number
  carbs?: number
  fats?: number
  created_at: string
  updated_at: string
}

export default function RecipesSection() {
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('all')
  const [showEditor, setShowEditor] = useState(false)
  const [editingRecipe, setEditingRecipe] = useState<Recipe | null>(null)

  const categories = [
    { value: 'all', label: 'All Recipes' },
    { value: 'breakfast', label: 'Breakfast' },
    { value: 'lunch', label: 'Lunch' },
    { value: 'dinner', label: 'Dinner' },
    { value: 'snack', label: 'Snacks' },
    { value: 'dessert', label: 'Desserts' }
  ]

  useEffect(() => {
    fetchRecipes()
  }, [selectedCategory])

  const fetchRecipes = async () => {
    try {
      setLoading(true)
      const url = selectedCategory === 'all'
        ? `${APP_CONFIG.apiUrl}/api/fitness/recipes`
        : `${APP_CONFIG.apiUrl}/api/fitness/recipes?category=${selectedCategory}`

      const response = await fetch(url, {
        credentials: 'include'
      })

      if (response.ok) {
        const data = await response.json()
        setRecipes(data)
      }
    } catch (error) {
      console.error('Failed to fetch recipes:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleCreateRecipe = () => {
    setEditingRecipe(null)
    setShowEditor(true)
  }

  const handleEditRecipe = (recipe: Recipe) => {
    setEditingRecipe(recipe)
    setShowEditor(true)
  }

  const handleDeleteRecipe = async (recipeId: string) => {
    if (!confirm('Are you sure you want to delete this recipe?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/recipes/${recipeId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        fetchRecipes()
      }
    } catch (error) {
      console.error('Failed to delete recipe:', error)
    }
  }

  const handleSaveRecipe = () => {
    setShowEditor(false)
    setEditingRecipe(null)
    fetchRecipes()
  }

  const filteredRecipes = recipes.filter(recipe =>
    recipe.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    recipe.description?.toLowerCase().includes(searchTerm.toLowerCase())
  )

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-800 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <ChefHat className="w-6 h-6" />
              My Recipes
            </h1>
            <p className="text-gray-400 text-sm mt-1">
              Save your favorite recipes with automatic nutrition calculation
            </p>
          </div>
          <button
            onClick={handleCreateRecipe}
            className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg font-medium transition-colors flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            New Recipe
          </button>
        </div>

        {/* Search and Filter */}
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search recipes..."
              className="w-full pl-10 pr-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-teal-500"
            />
          </div>

          <div className="relative">
            <Filter className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="pl-10 pr-10 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white appearance-none focus:outline-none focus:border-teal-500 cursor-pointer"
            >
              {categories.map(cat => (
                <option key={cat.value} value={cat.value}>{cat.label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Recipes Grid */}
      <div className="flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center h-64 text-gray-400">
            Loading recipes...
          </div>
        ) : filteredRecipes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-gray-400">
            <ChefHat className="w-16 h-16 mb-4 opacity-50" />
            <p className="text-lg font-medium">No recipes yet</p>
            <p className="text-sm mt-1">Click "New Recipe" to create your first recipe</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredRecipes.map(recipe => (
              <RecipeCard
                key={recipe.id}
                recipe={recipe}
                onEdit={handleEditRecipe}
                onDelete={handleDeleteRecipe}
                onRefresh={fetchRecipes}
              />
            ))}
          </div>
        )}
      </div>

      {/* Recipe Editor Modal */}
      {showEditor && (
        <RecipeEditor
          recipe={editingRecipe}
          onClose={() => {
            setShowEditor(false)
            setEditingRecipe(null)
          }}
          onSave={handleSaveRecipe}
        />
      )}
    </div>
  )
}
