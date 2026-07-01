// ProgressPhotosView — the "Photos" sub-tab of Progress. Upload physique photos
// (camera or gallery), view them in a grid, and tap one to get an inline AI
// critique from the configured vision model. Images are served from an
// auth-protected route, so every <Image> carries the bearer token.
import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  Image,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Alert,
  Dimensions,
  RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Card } from '../ui';
import apiClient from '../../../services/api';
import imagePickerService from '../../../services/imagePicker';
import { progressPhotosService, ProgressPhoto } from '../../../services/progressPhotos';
import { colors, spacing, fontSizes, fontWeights, borderRadius } from '../../../styles/theme';

const SCREEN_W = Dimensions.get('window').width;
const GRID_GAP = spacing.sm;
const GRID_COLS = 3;
// screen padding (md*2) + gaps between columns
const THUMB = Math.floor((SCREEN_W - spacing.md * 2 - GRID_GAP * (GRID_COLS - 1)) / GRID_COLS);

function formatDate(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function ProgressPhotosView() {
  const [token, setToken] = useState<string | null>(null);
  const [photos, setPhotos] = useState<ProgressPhoto[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selected, setSelected] = useState<ProgressPhoto | null>(null);
  const [critiquing, setCritiquing] = useState(false);

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined;

  const load = useCallback(async () => {
    try {
      const items = await progressPhotosService.list();
      setPhotos(items);
    } catch (e) {
      console.warn('[ProgressPhotos] load failed', e);
    }
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setToken(await apiClient.getToken());
      await load();
      setLoading(false);
    })();
  }, [load]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const doUpload = async (img: { uri: string; type?: string } | null) => {
    if (!img) return;
    setUploading(true);
    try {
      const created = await progressPhotosService.upload(img);
      setPhotos(prev => [created, ...prev]);
    } catch (e) {
      console.error('[ProgressPhotos] upload failed', e);
      Alert.alert('Upload failed', 'Could not upload the photo. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  const handleAdd = () => {
    Alert.alert('Add progress photo', 'Choose a source', [
      { text: 'Take Photo', onPress: async () => doUpload(await imagePickerService.takePhoto()) },
      { text: 'Choose from Library', onPress: async () => doUpload(await imagePickerService.pickFromGallery()) },
      { text: 'Cancel', style: 'cancel' },
    ]);
  };

  const handleCritique = async (photo: ProgressPhoto) => {
    setCritiquing(true);
    try {
      const result = await progressPhotosService.critique(photo.id);
      const updated: ProgressPhoto = {
        ...photo,
        critique: result.critique,
        critique_model: result.critique_model,
        critiqued_at: result.critiqued_at,
        has_critique: true,
      };
      setSelected(updated);
      setPhotos(prev => prev.map(p => (p.id === photo.id ? updated : p)));
    } catch (e) {
      console.error('[ProgressPhotos] critique failed', e);
      Alert.alert('Critique failed', 'The vision model could not be reached. Please try again.');
    } finally {
      setCritiquing(false);
    }
  };

  const handleDelete = (photo: ProgressPhoto) => {
    Alert.alert('Delete photo', 'Remove this progress photo?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await progressPhotosService.remove(photo.id);
            setPhotos(prev => prev.filter(p => p.id !== photo.id));
            if (selected?.id === photo.id) setSelected(null);
          } catch (e) {
            console.error('[ProgressPhotos] delete failed', e);
            Alert.alert('Delete failed', 'Could not delete the photo.');
          }
        },
      },
    ]);
  };

  if (loading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <TouchableOpacity style={styles.addBtn} onPress={handleAdd} activeOpacity={0.85} disabled={uploading}>
        {uploading ? (
          <ActivityIndicator size="small" color={colors.accent} />
        ) : (
          <Ionicons name="camera" size={18} color={colors.accent} />
        )}
        <Text style={styles.addBtnText}>{uploading ? 'Uploading…' : 'Add Progress Photo'}</Text>
      </TouchableOpacity>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      >
        {photos.length === 0 ? (
          <Card style={styles.emptyCard}>
            <Ionicons name="images-outline" size={40} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>No progress photos yet</Text>
            <Text style={styles.emptyHint}>
              Add a photo to track your physique over time and get an AI critique.
            </Text>
          </Card>
        ) : (
          <View style={styles.grid}>
            {photos.map(photo => (
              <TouchableOpacity
                key={photo.id}
                style={styles.thumbWrap}
                activeOpacity={0.85}
                onPress={() => setSelected(photo)}
                onLongPress={() => handleDelete(photo)}
              >
                <Image
                  source={{ uri: progressPhotosService.fileUrl(photo.id, 'thumb'), headers: authHeaders }}
                  style={styles.thumb}
                />
                {photo.has_critique ? (
                  <View style={styles.critiqueBadge}>
                    <Ionicons name="sparkles" size={11} color={colors.accent} />
                  </View>
                ) : null}
                <Text style={styles.thumbDate}>{formatDate(photo.created_at)}</Text>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </ScrollView>

      {/* Detail modal */}
      <Modal
        visible={selected != null}
        animationType="slide"
        transparent={false}
        onRequestClose={() => setSelected(null)}
      >
        {selected ? (
          <View style={styles.modalContainer}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setSelected(null)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                <Ionicons name="close" size={26} color={colors.text} />
              </TouchableOpacity>
              <Text style={styles.modalTitle}>{formatDate(selected.created_at)}</Text>
              <TouchableOpacity onPress={() => handleDelete(selected)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
                <Ionicons name="trash-outline" size={22} color={colors.error} />
              </TouchableOpacity>
            </View>

            <ScrollView contentContainerStyle={styles.modalScroll}>
              <Image
                source={{ uri: progressPhotosService.fileUrl(selected.id, 'full'), headers: authHeaders }}
                style={styles.fullImage}
                resizeMode="contain"
              />

              {selected.bodyweight != null ? (
                <Text style={styles.metaLine}>
                  {selected.bodyweight} {selected.bodyweight_unit || 'lbs'}
                </Text>
              ) : null}
              {selected.notes ? <Text style={styles.notes}>{selected.notes}</Text> : null}

              <Card style={styles.critiqueCard}>
                <View style={styles.critiqueHeader}>
                  <Ionicons name="sparkles" size={16} color={colors.accent} />
                  <Text style={styles.critiqueTitle}>AI Critique</Text>
                </View>
                {selected.critique ? (
                  <>
                    <Text style={styles.critiqueText}>{selected.critique}</Text>
                    <TouchableOpacity
                      style={styles.recritiqueBtn}
                      onPress={() => handleCritique(selected)}
                      disabled={critiquing}
                    >
                      {critiquing ? (
                        <ActivityIndicator size="small" color={colors.accent} />
                      ) : (
                        <Text style={styles.recritiqueText}>Re-critique</Text>
                      )}
                    </TouchableOpacity>
                  </>
                ) : critiquing ? (
                  <View style={styles.critiqueLoading}>
                    <ActivityIndicator size="small" color={colors.accent} />
                    <Text style={styles.critiqueLoadingText}>Analyzing your physique…</Text>
                  </View>
                ) : (
                  <TouchableOpacity
                    style={styles.critiqueBtn}
                    onPress={() => handleCritique(selected)}
                    activeOpacity={0.85}
                  >
                    <Ionicons name="sparkles" size={16} color={colors.background} />
                    <Text style={styles.critiqueBtnText}>Critique this photo</Text>
                  </TouchableOpacity>
                )}
              </Card>
            </ScrollView>
          </View>
        ) : null}
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  addBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.assistant?.borderStrong || colors.border,
    backgroundColor: colors.assistant?.actionSoft || colors.surface,
  },
  addBtnText: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  scrollContent: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: GRID_GAP,
  },
  thumbWrap: {
    width: THUMB,
  },
  thumb: {
    width: THUMB,
    height: THUMB,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  critiqueBadge: {
    position: 'absolute',
    top: 6,
    right: 6,
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background + 'cc',
  },
  thumbDate: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 4,
    textAlign: 'center',
  },
  emptyCard: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xl,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  emptyHint: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingHorizontal: spacing.lg,
  },
  // Modal
  modalContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.xxl,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  modalScroll: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.md,
  },
  fullImage: {
    width: '100%',
    height: SCREEN_W * 1.2,
    borderRadius: borderRadius.xl,
    backgroundColor: colors.surface,
  },
  metaLine: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
  },
  notes: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  critiqueCard: {
    gap: spacing.sm,
  },
  critiqueHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  critiqueTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  critiqueText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 21,
  },
  critiqueBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.full,
    backgroundColor: colors.accent,
  },
  critiqueBtnText: {
    color: colors.background,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.semibold,
  },
  critiqueLoading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  critiqueLoadingText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
  recritiqueBtn: {
    alignSelf: 'flex-start',
    paddingVertical: spacing.xs,
  },
  recritiqueText: {
    color: colors.accent,
    fontSize: fontSizes.sm,
    fontWeight: fontWeights.medium,
  },
});
