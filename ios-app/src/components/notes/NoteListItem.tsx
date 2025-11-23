import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Note } from '../../types/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface NoteListItemProps {
  note: Note;
  onPress: (note: Note) => void;
  onLongPress?: (note: Note) => void;
}

export default function NoteListItem({ note, onPress, onLongPress }: NoteListItemProps) {
  const preview = note.content.substring(0, 100).replace(/\n/g, ' ');
  const date = new Date(note.updated_at);
  const dateStr = date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress(note)}
      onLongPress={() => onLongPress?.(note)}
      activeOpacity={0.7}
    >
      <View style={styles.content}>
        <Text style={styles.title} numberOfLines={1}>
          {note.title || 'Untitled'}
        </Text>
        {preview && (
          <Text style={styles.preview} numberOfLines={2}>
            {preview}
          </Text>
        )}
        <Text style={styles.date}>{dateStr}</Text>
      </View>
      <View style={styles.chevron}>
        <Text style={styles.chevronText}>›</Text>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  content: {
    flex: 1,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  preview: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: fontSizes.sm * 1.4,
    marginBottom: spacing.xs,
  },
  date: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  chevron: {
    marginLeft: spacing.sm,
  },
  chevronText: {
    color: colors.textMuted,
    fontSize: fontSizes.xl,
  },
});
