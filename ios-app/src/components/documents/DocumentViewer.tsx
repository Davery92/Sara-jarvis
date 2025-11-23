import React from 'react';
import { View, Text, StyleSheet, Image, ScrollView, Linking } from 'react-native';
import { Document } from '../../services/documents';
import { documentsService } from '../../services/documents';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface DocumentViewerProps {
  document: Document;
}

export default function DocumentViewer({ document }: DocumentViewerProps) {
  const icon = documentsService.getFileTypeIcon(document.mime_type);
  const fileSize = documentsService.formatFileSize(document.file_size);
  const downloadUrl = documentsService.getDocumentUrl(document);

  const isImage = document.mime_type.includes('image');
  const isPDF = document.mime_type.includes('pdf');

  const handleOpenExternal = () => {
    Linking.openURL(downloadUrl).catch((err) =>
      console.error('Failed to open document:', err)
    );
  };

  return (
    <ScrollView style={styles.container}>
      {/* Document Header */}
      <View style={styles.header}>
        <Text style={styles.icon}>{icon}</Text>
        <View style={styles.headerInfo}>
          <Text style={styles.filename}>{document.original_filename}</Text>
          <Text style={styles.fileSize}>{fileSize}</Text>
        </View>
      </View>

      {/* Content */}
      {document.content_text && document.content_text.trim() && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Content</Text>
          <Text style={styles.summaryText}>{document.content_text}</Text>
        </View>
      )}

      {/* Processing Status */}
      {document.is_processed && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Processing</Text>
          <View style={styles.metadataRow}>
            <Text style={styles.metadataLabel}>Status:</Text>
            <View style={[
              styles.categoryBadge,
              { backgroundColor: document.is_processed === 'true' ? '#10b981' : document.is_processed === 'error' ? '#ef4444' : '#f59e0b' }
            ]}>
              <Text style={styles.categoryText}>
                {document.is_processed === 'true' ? 'Processed' : document.is_processed === 'error' ? 'Error' : 'Processing'}
              </Text>
            </View>
          </View>
        </View>
      )}

      {/* Preview */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Preview</Text>
        {isImage ? (
          <Image
            source={{ uri: downloadUrl }}
            style={styles.imagePreview}
            resizeMode="contain"
          />
        ) : isPDF ? (
          <View style={styles.previewPlaceholder}>
            <Text style={styles.placeholderIcon}>📄</Text>
            <Text style={styles.placeholderText}>PDF Preview</Text>
            <Text style={styles.placeholderSubtext}>
              Tap to open in external viewer
            </Text>
          </View>
        ) : (
          <View style={styles.previewPlaceholder}>
            <Text style={styles.placeholderIcon}>{icon}</Text>
            <Text style={styles.placeholderText}>No preview available</Text>
            <Text style={styles.placeholderSubtext}>
              Tap to open in external viewer
            </Text>
          </View>
        )}
      </View>

      {/* Document Info */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Information</Text>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>File Type:</Text>
          <Text style={styles.infoValue}>{document.mime_type}</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Size:</Text>
          <Text style={styles.infoValue}>{fileSize}</Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Created:</Text>
          <Text style={styles.infoValue}>
            {new Date(document.created_at).toLocaleString()}
          </Text>
        </View>
        <View style={styles.infoRow}>
          <Text style={styles.infoLabel}>Updated:</Text>
          <Text style={styles.infoValue}>
            {new Date(document.updated_at).toLocaleString()}
          </Text>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  icon: {
    fontSize: 48,
    marginRight: spacing.md,
  },
  headerInfo: {
    flex: 1,
  },
  filename: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  fileSize: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  section: {
    backgroundColor: colors.surface,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    marginBottom: spacing.md,
  },
  summaryText: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: fontSizes.md * 1.6,
  },
  metadataRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  metadataLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginRight: spacing.sm,
    minWidth: 70,
  },
  categoryBadge: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  categoryText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  tagsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    flex: 1,
  },
  tagBadge: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  tagText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  imagePreview: {
    width: '100%',
    height: 300,
    borderRadius: borderRadius.md,
    backgroundColor: colors.background,
  },
  previewPlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    minHeight: 200,
  },
  placeholderIcon: {
    fontSize: 64,
    marginBottom: spacing.md,
  },
  placeholderText: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  placeholderSubtext: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  infoLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  infoValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    flex: 1,
    textAlign: 'right',
  },
});
