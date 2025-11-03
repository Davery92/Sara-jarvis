import React, { useState } from 'react'
import { Clock, Users, Edit, Trash2, X } from 'lucide-react'
import type { Recipe } from './RecipesSection'

interface RecipeCardProps {
  recipe: Recipe
  onEdit: (recipe: Recipe) => void
  onDelete: (recipeId: string) => void
  onRefresh: () => void
}

export default function RecipeCard({ recipe, onEdit, onDelete, onRefresh }: RecipeCardProps) {
  const [showDetails, setShowDetails] = useState(false)

  const getCategoryColor = (category?: string) => {
    switch (category?.toLowerCase()) {
      case 'breakfast': return 'bg-yellow-600'
      case 'lunch': return 'bg-blue-600'
      case 'dinner': return 'bg-purple-600'
      case 'snack': return 'bg-green-600'
      case 'dessert': return 'bg-pink-600'
      default: return 'bg-gray-600'
    }
  }

  return (
    <>
      <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden hover:border-teal-500 transition-colors">
        {/* Header */}
        <div className="p-4 border-b border-gray-700">
          <div className="flex items-start justify-between mb-2">
            <h3 className="text-lg font-semibold text-white flex-1 cursor-pointer hover:text-teal-400 transition-colors"
                onClick={() => setShowDetails(true)}>
              {recipe.name}
            </h3>
            {recipe.category && (
              <span className={`px-2 py-1 rounded text-xs font-medium text-white ${getCategoryColor(recipe.category)}`}>
                {recipe.category}
              </span>
            )}
          </div>
          {recipe.description && (
            <p className="text-sm text-gray-400 line-clamp-2">{recipe.description}</p>
          )}
        </div>

        {/* Nutrition Info */}
        <div className="grid grid-cols-4 gap-2 p-4 bg-gray-900">
          <div className="text-center">
            <div className="text-lg font-bold text-white">{recipe.calories?.toFixed(0) || '--'}</div>
            <div className="text-xs text-gray-400">Cal</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-green-400">{recipe.protein?.toFixed(0) || '--'}</div>
            <div className="text-xs text-gray-400">Pro</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-blue-400">{recipe.carbs?.toFixed(0) || '--'}</div>
            <div className="text-xs text-gray-400">Carb</div>
          </div>
          <div className="text-center">
            <div className="text-lg font-bold text-yellow-400">{recipe.fats?.toFixed(0) || '--'}</div>
            <div className="text-xs text-gray-400">Fat</div>
          </div>
        </div>

        {/* Metadata */}
        <div className="p-4 flex items-center gap-4 text-sm text-gray-400">
          {recipe.prep_time_minutes && (
            <div className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              {recipe.prep_time_minutes} min
            </div>
          )}
          <div className="flex items-center gap-1">
            <Users className="w-4 h-4" />
            {recipe.servings} serving{recipe.servings !== 1 ? 's' : ''}
          </div>
        </div>

        {/* Actions */}
        <div className="p-4 pt-0 flex gap-2">
          <button
            onClick={() => onEdit(recipe)}
            className="flex-1 px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
          >
            <Edit className="w-4 h-4" />
          </button>
          <button
            onClick={() => onDelete(recipe.id)}
            className="px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Recipe Details Modal */}
      {showDetails && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-auto border border-gray-700">
            {/* Modal Header */}
            <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-6 flex items-center justify-between">
              <h2 className="text-2xl font-bold text-white">{recipe.name}</h2>
              <button
                onClick={() => setShowDetails(false)}
                className="p-2 hover:bg-gray-700 rounded transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 space-y-6">
              {recipe.description && (
                <div>
                  <h3 className="text-lg font-semibold text-white mb-2">Description</h3>
                  <p className="text-gray-300">{recipe.description}</p>
                </div>
              )}

              {/* Nutrition Summary */}
              <div>
                <h3 className="text-lg font-semibold text-white mb-3">Nutrition (per serving)</h3>
                <div className="grid grid-cols-4 gap-4">
                  <div className="bg-gray-900 p-4 rounded-lg text-center">
                    <div className="text-2xl font-bold text-white">{recipe.calories?.toFixed(0)}</div>
                    <div className="text-sm text-gray-400">Calories</div>
                  </div>
                  <div className="bg-gray-900 p-4 rounded-lg text-center">
                    <div className="text-2xl font-bold text-green-400">{recipe.protein?.toFixed(1)}g</div>
                    <div className="text-sm text-gray-400">Protein</div>
                  </div>
                  <div className="bg-gray-900 p-4 rounded-lg text-center">
                    <div className="text-2xl font-bold text-blue-400">{recipe.carbs?.toFixed(1)}g</div>
                    <div className="text-sm text-gray-400">Carbs</div>
                  </div>
                  <div className="bg-gray-900 p-4 rounded-lg text-center">
                    <div className="text-2xl font-bold text-yellow-400">{recipe.fats?.toFixed(1)}g</div>
                    <div className="text-sm text-gray-400">Fats</div>
                  </div>
                </div>
              </div>

              {/* Ingredients */}
              <div>
                <h3 className="text-lg font-semibold text-white mb-3">Ingredients</h3>
                <ul className="space-y-2">
                  {recipe.ingredients.map((ing, idx) => (
                    <li key={idx} className="text-gray-300 flex items-start">
                      <span className="text-teal-400 mr-2">•</span>
                      <span>{ing.quantity} {ing.unit} {ing.name}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Instructions */}
              <div>
                <h3 className="text-lg font-semibold text-white mb-3">Instructions</h3>
                <p className="text-gray-300 whitespace-pre-wrap">{recipe.instructions}</p>
              </div>

              {/* Meta Info */}
              <div className="flex gap-6 text-sm text-gray-400 pt-4 border-t border-gray-700">
                {recipe.prep_time_minutes && (
                  <div className="flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Prep: {recipe.prep_time_minutes} minutes
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <Users className="w-4 h-4" />
                  Servings: {recipe.servings}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
