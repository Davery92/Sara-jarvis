import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { weatherService, WeatherData } from '../../services/weather';

export default function WeatherWidget() {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchWeather();
  }, []);

  const fetchWeather = async () => {
    try {
      setLoading(true);
      const data = await weatherService.getCurrentWeather();
      setWeather(data);
    } catch (error) {
      console.error('Failed to fetch weather:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>☁️</Text>
          <Text style={styles.title}>Weather</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  if (!weather) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>☁️</Text>
          <Text style={styles.title}>Weather</Text>
        </View>
        <Text style={styles.emptyText}>Weather unavailable</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>☁️</Text>
        <Text style={styles.title}>Weather</Text>
      </View>

      <View style={styles.weatherCard}>
        <View style={styles.mainWeather}>
          <Text style={styles.weatherEmoji}>
            {weatherService.getWeatherEmoji(weather.condition)}
          </Text>
          <View style={styles.tempInfo}>
            <Text style={styles.temperature}>{weather.temperature}°F</Text>
            <Text style={styles.condition}>{weather.condition}</Text>
          </View>
        </View>

        <View style={styles.detailsRow}>
          <View style={styles.detail}>
            <Text style={styles.detailLabel}>Humidity</Text>
            <Text style={styles.detailValue}>{weather.humidity}%</Text>
          </View>
          <View style={styles.detail}>
            <Text style={styles.detailLabel}>Wind</Text>
            <Text style={styles.detailValue}>{weather.windSpeed} mph</Text>
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    margin: spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  icon: {
    fontSize: 20,
    marginRight: spacing.xs,
  },
  title: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginLeft: spacing.xs,
  },
  loader: {
    paddingVertical: spacing.lg,
  },
  emptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
  weatherCard: {
    padding: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
  },
  mainWeather: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  weatherEmoji: {
    fontSize: 48,
    marginRight: spacing.md,
  },
  tempInfo: {
    flex: 1,
  },
  temperature: {
    fontSize: 32,
    fontWeight: '700',
    color: colors.text,
  },
  condition: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
  },
  detailsRow: {
    flexDirection: 'row',
    gap: spacing.lg,
  },
  detail: {
    flex: 1,
  },
  detailLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginBottom: 4,
  },
  detailValue: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
  },
});
