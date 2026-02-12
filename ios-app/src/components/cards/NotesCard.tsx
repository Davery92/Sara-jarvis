import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface NotesCardProps {
  card: any;
  onAction: (action: any) => void;
}

export default function NotesCard({ card, onAction }: NotesCardProps) {
  const items = card.items || [];

  const handleNotePress = (note: any) => {
    onAction({
      action: 'navigate',
      target: 'Notes',
      params: { noteId: note.id },
    });
  };

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {items.length === 0 ? (
        <Text style={styles.emptyText}>No notes</Text>
      ) : (
        items.map((note: any, index: number) => (
          <TouchableOpacity
            key={note.id ?? index}
            style={styles.row}
            activeOpacity={0.7}
            onPress={() => handleNotePress(note)}
          >
            <View style={styles.noteContent}>
              <View style={styles.titleRow}>
                <Text style={styles.noteTitle} numberOfLines={1}>
                  {note.title}
                </Text>
                {note.folder ? (
                  <View style={styles.folderBadge}>
                    <Text style={styles.folderText}>{note.folder}</Text>
                  </View>
                ) : null}
              </View>
              {note.preview ? (
                <Text style={styles.preview} numberOfLines={2}>
                  {note.preview}
                </Text>
              ) : null}
            </View>
          </TouchableOpacity>
        ))
      )}

      {card.summary ? (
        <Text style={styles.summary}>{card.summary}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  title: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingVertical: spacing.md,
  },
  row: {
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  noteContent: {
    flex: 1,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 2,
  },
  noteTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
    flex: 1,
  },
  folderBadge: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
    marginLeft: spacing.sm,
  },
  folderText: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
  },
  preview: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    lineHeight: 18,
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});
