import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../config'

interface StarRatingProps {
  episodeId: string
  onRatingChange?: (rating: number) => void
  size?: 'sm' | 'md' | 'lg'
  readonly?: boolean
}

interface RatingData {
  rated: boolean
  user_rating?: number
  rating_count?: number
  average_rating?: number
}

const StarRating: React.FC<StarRatingProps> = ({
  episodeId,
  onRatingChange,
  size = 'md',
  readonly = false
}) => {
  const [rating, setRating] = useState<number>(0)
  const [hoverRating, setHoverRating] = useState<number>(0)
  const [isLoading, setIsLoading] = useState(false)
  const [hasRated, setHasRated] = useState(false)

  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-5 h-5',
    lg: 'w-6 h-6'
  }

  // Load existing rating
  useEffect(() => {
    const loadRating = async () => {
      try {
        const response = await fetch(
          `${APP_CONFIG.apiUrl}/api/episodes/${episodeId}/rating`,
          { credentials: 'include' }
        )

        if (response.ok) {
          const data: RatingData = await response.json()
          if (data.rated && data.user_rating) {
            setRating(data.user_rating)
            setHasRated(true)
          }
        }
      } catch (error) {
        console.error('Failed to load rating:', error)
      }
    }

    if (episodeId) {
      loadRating()
    }
  }, [episodeId])

  const handleRating = async (newRating: number) => {
    if (readonly || isLoading) return

    setIsLoading(true)
    const previousRating = rating

    // Optimistic update
    setRating(newRating)
    setHasRated(true)

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/episodes/${episodeId}/rate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ rating: newRating })
        }
      )

      if (!response.ok) {
        throw new Error('Failed to submit rating')
      }

      const data = await response.json()
      if (data.success && onRatingChange) {
        onRatingChange(newRating)
      }
    } catch (error) {
      console.error('Failed to submit rating:', error)
      // Rollback on error
      setRating(previousRating)
      setHasRated(previousRating > 0)
    } finally {
      setIsLoading(false)
    }
  }

  const handleClearRating = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (readonly || isLoading || !hasRated) return

    setIsLoading(true)
    const previousRating = rating

    // Optimistic update
    setRating(0)
    setHasRated(false)

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/episodes/${episodeId}/rating`,
        {
          method: 'DELETE',
          credentials: 'include'
        }
      )

      if (!response.ok) {
        throw new Error('Failed to delete rating')
      }

      if (onRatingChange) {
        onRatingChange(0)
      }
    } catch (error) {
      console.error('Failed to delete rating:', error)
      // Rollback on error
      setRating(previousRating)
      setHasRated(true)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-1">
      {[1, 2, 3, 4, 5].map((star) => {
        const isFilled = (hoverRating || rating) >= star

        return (
          <button
            key={star}
            type="button"
            disabled={readonly || isLoading}
            className={`
              ${sizeClasses[size]}
              transition-all duration-150
              ${readonly ? 'cursor-default' : 'cursor-pointer hover:scale-110'}
              ${isLoading ? 'opacity-50' : 'opacity-100'}
            `}
            onMouseEnter={() => !readonly && setHoverRating(star)}
            onMouseLeave={() => !readonly && setHoverRating(0)}
            onClick={() => handleRating(star)}
            aria-label={`Rate ${star} stars`}
          >
            <svg
              viewBox="0 0 24 24"
              fill={isFilled ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth="2"
              className={`
                ${isFilled
                  ? 'text-yellow-400'
                  : 'text-gray-500'
                }
                transition-colors duration-150
              `}
            >
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
          </button>
        )
      })}

      {hasRated && !readonly && (
        <button
          type="button"
          onClick={handleClearRating}
          disabled={isLoading}
          className={`
            ml-1 text-gray-500 hover:text-gray-300 transition-colors
            ${sizeClasses[size]}
            ${isLoading ? 'opacity-50' : 'opacity-100'}
          `}
          aria-label="Clear rating"
          title="Clear rating"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  )
}

export default StarRating
