import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Image } from 'react-native';
import { Document } from '../../services/documents';
import { documentsService } from '../../services/documents';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface DocumentListItemProps {
  document: Document;
  onPress: (document: Document) => void;
  onLongPress?: (document: Document) => void;
}

export default function DocumentListItem({
  document,
  onPress,
  onLongPress,
}: DocumentListItemProps) {
  const icon = documentsService.getFileTypeIcon(document.mime_type);
  const fileSize = documentsService.formatFileSize(document.file_size);
  const date = new Date(document.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  return (
    <TouchableOpacity
      style={styles.container}
      onPress={() => onPress(document)}
      onLongPress={() => onLongPress?.(document)}
      activeOpacity={0.7}
    >
      {/* Icon */}
      <View style={styles.thumbnail}>
        <Text style={styles.icon}>{icon}</Text>
      </View>

      {/* Document Info */}
      <View style={styles.content}>
        <Text style={styles.filename} numberOfLines={2}>
          {document.title || document.original_filename}
        </Text>

        {document.content_text && document.content_text.trim() && (
          <Text style={styles.summary} numberOfLines={2}>
            {document.content_text}
          </Text>
        )}

        <View style={styles.metadata}>
          <Text style={styles.metadataText}>{fileSize}</Text>
          <Text style={styles.metadataDot}>•</Text>
          <Text style={styles.metadataText}>{date}</Text>
          {document.is_processed === 'true' && (
            <>
              <Text style={styles.metadataDot}>•</Text>
              <Text style={styles.metadataText}>Processed</Text>
            </>
          )}
        </View>
      </View>

      {/* Chevron */}
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
  thumbnail: {
    width: 60,
    height: 60,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  thumbnailImage: {
    width: 60,
    height: 60,
    borderRadius: borderRadius.sm,
  },
  icon: {
    fontSize: 32,
  },
  content: {
    flex: 1,
  },
  filename: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  summary: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: fontSizes.sm * 1.4,
    marginBottom: spacing.xs,
  },
  metadata: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  metadataText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  metadataDot: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginHorizontal: spacing.xs,
  },
  tagsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  categoryBadge: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  categoryText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  tagBadge: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  tagText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  moreTagsText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    alignSelf: 'center',
  },
  chevron: {
    marginLeft: spacing.sm,
  },
  chevronText: {
    color: colors.textMuted,
    fontSize: fontSizes.xl,
  },
});
