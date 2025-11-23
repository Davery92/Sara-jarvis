import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Episode } from '../../services/settings';
import { settingsService } from '../../services/settings';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface MemoryListItemProps {
  episode: Episode;
  onPress: (episode: Episode) => void;
  onLongPress?: (episode: Episode) => void;
}

export default function MemoryListItem({
  episode,
  onPress,
  onLongPress,
}: MemoryListItemProps) {
  const emoji = settingsService.getEpisodeTypeEmoji(episode.episode_type);
  const timeAgo = settingsService.formatEpisodeTime(episode.timestamp);
  const importanceColor = settingsService.getImportanceColor(episode.importance_score);
  const importanceScore = settingsService.formatImportanceScore(episode.importance_score);

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress(episode)}
      onLongPress={() => onLongPress?.(episode)}
      activeOpacity={0.7}
    >
      {/* Emoji Icon */}
      <View style={styles.iconContainer}>
        <Text style={styles.emoji}>{emoji}</Text>
      </View>

      {/* Episode Content */}
      <View style={styles.content}>
        <View style={styles.header}>
          <Text style={styles.type}>{episode.episode_type.replace('_', ' ')}</Text>
          <Text style={styles.time}>{timeAgo}</Text>
        </View>

        <Text style={styles.text} numberOfLines={3}>
          {episode.content}
        </Text>

        {/* Importance Badge */}
        <View style={styles.footer}>
          <View style={[styles.importanceBadge, { backgroundColor: importanceColor }]}>
            <Text style={styles.importanceText}>{importanceScore}</Text>
          </View>
        </View>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  iconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  emoji: {
    fontSize: fontSizes.lg,
  },
  content: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  type: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  time: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  text: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: fontSizes.sm * 1.4,
    marginBottom: spacing.xs,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  importanceBadge: {
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  importanceText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },
});
