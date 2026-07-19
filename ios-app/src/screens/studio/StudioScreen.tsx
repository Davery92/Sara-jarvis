import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { Artifact, artifactsService } from '../../services/artifacts';

const TYPE_ICON: Record<string, string> = {
  code: 'code-slash',
  diagram: 'git-network',
  document: 'document-text',
  mindmap: 'git-branch',
  note: 'reader',
  table: 'grid',
  file: 'document',
};

const TYPE_LABEL: Record<string, string> = {
  code: 'Code',
  diagram: 'Diagram',
  document: 'Document',
  mindmap: 'Mindmap',
  note: 'Note',
  table: 'Table',
  file: 'File',
};

function iconFor(t: string) {
  return TYPE_ICON[t] || 'sparkles';
}
function labelFor(t: string) {
  return TYPE_LABEL[t] || t;
}

function formatWhen(iso?: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export default function StudioScreen({ route }: any) {
  const deepId: string | undefined = route?.params?.id;
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await artifactsService.list({ limit: 100 });
      setArtifacts(data);
    } catch (e) {
      console.error('Failed to load artifacts:', e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const types = useMemo(() => {
    const s = new Set<string>();
    artifacts.forEach((a) => s.add(a.artifact_type));
    return Array.from(s);
  }, [artifacts]);

  const visible = useMemo(() => {
    return artifacts
      .filter((a) => (filter === 'all' ? true : a.artifact_type === filter))
      .slice()
      .sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
        return (b.updated_at || '').localeCompare(a.updated_at || '');
      });
  }, [artifacts, filter]);

  const handleShare = useCallback(async (a: Artifact) => {
    setDownloadingId(a.id);
    try {
      await artifactsService.downloadAndShare(a);
    } catch (e: any) {
      Alert.alert('Download failed', e?.message || 'Could not download the file.');
    } finally {
      setDownloadingId(null);
    }
  }, []);

  // Deep link: when arriving with ?id=<file>, jump straight to its share sheet.
  useEffect(() => {
    if (!deepId || loading) return;
    const target = artifacts.find((a) => a.id === deepId);
    if (target && target.artifact_type === 'file') {
      handleShare(target);
    }
  }, [deepId, loading, artifacts, handleShare]);

  const renderItem = ({ item }: { item: Artifact }) => {
    const isFile = item.artifact_type === 'file';
    return (
      <TouchableOpacity
        style={styles.row}
        activeOpacity={0.7}
        onPress={() => (isFile ? handleShare(item) : undefined)}
      >
        <View style={styles.iconWrap}>
          <Ionicons name={iconFor(item.artifact_type) as any} size={20} color={colors.primary} />
        </View>
        <View style={styles.info}>
          <View style={styles.titleRow}>
            <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
            {item.is_pinned ? (
              <Ionicons name="pin" size={13} color={colors.primary} />
            ) : null}
          </View>
          <Text style={styles.meta}>
            {labelFor(item.artifact_type)} · {formatWhen(item.updated_at)}
          </Text>
        </View>
        {isFile ? (
          downloadingId === item.id ? (
            <ActivityIndicator color={colors.primary} />
          ) : (
            <Ionicons name="share-outline" size={20} color={colors.primary} />
          )
        ) : null}
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {types.length > 1 && (
        <View style={styles.chipsRow}>
          <Chip active={filter === 'all'} label="All" onPress={() => setFilter('all')} />
          {types.map((t) => (
            <Chip key={t} active={filter === t} label={labelFor(t)} onPress={() => setFilter(t)} />
          ))}
        </View>
      )}

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : (
        <FlatList
          data={visible}
          keyExtractor={(a) => a.id}
          renderItem={renderItem}
          contentContainerStyle={visible.length === 0 ? styles.center : styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                load();
              }}
              tintColor={colors.primary}
            />
          }
          ListEmptyComponent={
            <Text style={styles.empty}>
              Nothing here yet. Anything Sara builds shows up in the Studio.
            </Text>
          }
        />
      )}
    </SafeAreaView>
  );
}

function Chip({ active, label, onPress }: { active: boolean; label: string; onPress: () => void }) {
  return (
    <TouchableOpacity
      style={[styles.chip, active && styles.chipActive]}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  list: { padding: spacing.md, gap: spacing.xs },
  chipsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  chip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { borderColor: colors.primary, backgroundColor: 'rgba(20, 184, 166, 0.12)' },
  chipText: { color: colors.textSecondary, fontSize: fontSizes.xs },
  chipTextActive: { color: colors.primary, fontWeight: '600' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.xs,
  },
  iconWrap: {
    width: 38,
    height: 38,
    borderRadius: borderRadius.md,
    backgroundColor: 'rgba(20, 184, 166, 0.12)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  info: { flex: 1, minWidth: 0 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  title: { color: colors.text, fontSize: fontSizes.md, fontWeight: '500', flexShrink: 1 },
  meta: { color: colors.textSecondary, fontSize: fontSizes.xs, marginTop: 2 },
  empty: { color: colors.textSecondary, fontSize: fontSizes.sm, textAlign: 'center' },
});
