import React, { useState, useEffect } from 'react';
import { View, TouchableOpacity, StyleSheet, ActivityIndicator, Text } from 'react-native';
import { apiClient } from '../../services/api';
import { colors } from '../../styles/theme';

interface StarRatingProps {
  episodeId: string;
  size?: number;
}

interface RatingData {
  rated: boolean;
  user_rating?: number;
  rating_count?: number;
  average_rating?: number;
}

const StarRating: React.FC<StarRatingProps> = ({ episodeId, size = 18 }) => {
  const [rating, setRating] = useState<number>(0);
  const [hasRated, setHasRated] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Load existing rating
  useEffect(() => {
    const loadRating = async () => {
      try {
        // apiClient.get returns response.data directly, not the full AxiosResponse
        const data = await apiClient.get<RatingData>(`/api/episodes/${episodeId}/rating`);

        if (data && data.rated && data.user_rating) {
          setRating(data.user_rating);
          setHasRated(true);
        }
      } catch (error) {
        console.log('Failed to load rating:', error);
      }
    };

    if (episodeId) {
      loadRating();
    }
  }, [episodeId]);

  const handleRating = async (newRating: number) => {
    if (isLoading) return;

    setIsLoading(true);
    const previousRating = rating;

    // Optimistic update
    setRating(newRating);
    setHasRated(true);

    try {
      // apiClient.post returns response.data directly, throws on error
      await apiClient.post(`/api/episodes/${episodeId}/rate`, {
        rating: newRating,
      });
      // If we reach here, the request was successful
    } catch (error) {
      console.error('Failed to submit rating:', error);
      // Rollback on error
      setRating(previousRating);
      setHasRated(previousRating > 0);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      {[1, 2, 3, 4, 5].map((star) => {
        const isFilled = rating >= star;

        return (
          <TouchableOpacity
            key={star}
            onPress={() => handleRating(star)}
            disabled={isLoading}
            style={[styles.starButton, { width: size, height: size }]}
            activeOpacity={0.7}
          >
            {isLoading && star === rating ? (
              <ActivityIndicator size="small" color={colors.primary} />
            ) : (
              <Text style={[styles.star, { fontSize: size, color: isFilled ? colors.hues.amber : colors.textMuted }]}>
                {isFilled ? '★' : '☆'}
              </Text>
            )}
          </TouchableOpacity>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 6,
    marginLeft: 2,
  },
  starButton: {
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 2,
  },
  star: {
    lineHeight: 20,
  },
});

export default StarRating;
