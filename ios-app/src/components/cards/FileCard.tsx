import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { artifactsService } from '../../services/artifacts';

interface FileCardProps {
  card: any;
  onAction: (action: any) => void;
}

function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export default function FileCard({ card }: FileCardProps) {
  const file = (card.items && card.items[0]) || {};
  const [busy, setBusy] = useState(false);

  const handleDownload = async () => {
    if (!file.artifact_id || busy) return;
    setBusy(true);
    try {
      await artifactsService.downloadAndShare({ id: file.artifact_id, content: file });
    } catch (e: any) {
      Alert.alert('Download failed', e?.message || 'Could not download the file.');
    } finally {
      setBusy(false);
    }
  };

  const isPdf = file.format === 'pdf';

  return (
    <View style={styles.container}>
      {card.title ? <Text style={styles.title}>{card.title}</Text> : null}
      <TouchableOpacity style={styles.row} activeOpacity={0.7} onPress={handleDownload} disabled={busy}>
        <View style={styles.iconWrap}>
          <Ionicons name={isPdf ? 'document-text' : 'document'} size={22} color={colors.primary} />
        </View>
        <View style={styles.info}>
          <Text style={styles.filename} numberOfLines={1}>{file.filename}</Text>
          <Text style={styles.meta}>
            {(file.format || '').toUpperCase()}
            {file.size_bytes ? ` · ${formatBytes(file.size_bytes)}` : ''}
          </Text>
        </View>
        {busy ? (
          <ActivityIndicator color={colors.primary} />
        ) : (
          <Ionicons name="share-outline" size={20} color={colors.primary} />
        )}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.md,
    backgroundColor: 'rgba(13, 127, 242, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  info: {
    flex: 1,
    minWidth: 0,
  },
  filename: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  meta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
});
