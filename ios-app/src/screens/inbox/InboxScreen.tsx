import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  TextInput,
  Alert,
  ActivityIndicator,
  Modal,
  ScrollView,
  RefreshControl,
} from 'react-native';
import * as ExpoClipboard from 'expo-clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import * as ExpoLinking from 'expo-linking';
import apiClient from '../../services/api';
import { navigateToChat } from '../../services/navigation';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface InboxItem {
  id: string;
  content_type: string;
  title: string | null;
  description: string | null;
  thumbnail_url: string | null;
  original_url: string | null;
  status: string;
  extraction_status: string;
  word_count: number | null;
  shared_at: string;
  extracted_text?: string;
  meta?: any;
  discussed?: boolean;
}

interface InboxStats {
  unread: number;
  read: number;
  kept: number;
  total: number;
}

const CONTENT_TYPE_ICONS: Record<string, string> = {
  url: '🔗',
  reddit: '🟠',
  pdf: '📄',
  text: '📝',
  document: '📎',
};

const STATUS_COLORS: Record<string, string> = {
  unread: colors.info,
  read: colors.textMuted,
  kept: colors.success,
  discarded: colors.error,
};

function timeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function getDomain(url: string | null): string {
  if (!url) return '';
  try {
    return new URL(url).hostname.replace('www.', '');
  } catch {
    return '';
  }
}

export default function InboxScreen() {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [stats, setStats] = useState<InboxStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  const [shareInput, setShareInput] = useState('');
  const [sharing, setSharing] = useState(false);
  const [selectedItem, setSelectedItem] = useState<InboxItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadItems = useCallback(async () => {
    try {
      const statusParam = filter === 'all' ? undefined : filter;
      const [itemsData, statsData] = await Promise.all([
        apiClient.getInboxItems(statusParam),
        apiClient.getInboxStats(),
      ]);
      setItems(itemsData);
      setStats(statsData);
    } catch (error) {
      console.error('Failed to load inbox:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  // Reload when screen comes into focus
  useFocusEffect(
    useCallback(() => {
      loadItems();
    }, [loadItems])
  );

  // Handle deep links from share extension (sara://inbox/share?url=...)
  useEffect(() => {
    const handleDeepLink = async (event: { url: string }) => {
      try {
        const parsed = ExpoLinking.parse(event.url);
        const sharedUrl = parsed.queryParams?.url as string | undefined;
        const sharedText = parsed.queryParams?.text as string | undefined;

        if (sharedUrl) {
          setSharing(true);
          await apiClient.shareToInbox(sharedUrl);
          setSharing(false);
          loadItems();
        } else if (sharedText) {
          setSharing(true);
          await apiClient.shareTextToInbox(sharedText);
          setSharing(false);
          loadItems();
        }
      } catch (error) {
        console.error('Deep link share failed:', error);
        setSharing(false);
      }
    };

    // Check if opened with a URL
    ExpoLinking.getInitialURL().then(url => {
      if (url && url.includes('inbox/share')) {
        handleDeepLink({ url });
      }
    });

    // Listen for future URLs
    const subscription = ExpoLinking.addEventListener('url', handleDeepLink);
    return () => subscription.remove();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    loadItems();
  };

  const handleShare = async () => {
    const input = shareInput.trim();
    if (!input) return;

    setSharing(true);
    try {
      // Detect if it's a URL
      const isUrl = /^https?:\/\//i.test(input) || /^[a-z0-9-]+\.[a-z]{2,}/i.test(input);
      if (isUrl) {
        const url = input.startsWith('http') ? input : `https://${input}`;
        await apiClient.shareToInbox(url);
      } else {
        await apiClient.shareTextToInbox(input);
      }
      setShareInput('');
      await loadItems();
    } catch (error) {
      console.error('Share failed:', error);
      Alert.alert('Error', 'Failed to share content');
    } finally {
      setSharing(false);
    }
  };

  const handlePasteAndShare = async () => {
    try {
      const text = await ExpoClipboard.getStringAsync();
      if (text) {
        setShareInput(text);
      }
    } catch {
      // ignore
    }
  };

  const handleItemPress = async (item: InboxItem) => {
    setSelectedItem(item);
    if (!item.extracted_text) {
      setDetailLoading(true);
      try {
        const detail = await apiClient.getInboxItem(item.id);
        setSelectedItem(detail);
        // Update item in list (now marked as read)
        setItems(prev => prev.map(i => i.id === item.id ? { ...i, status: 'read' } : i));
      } catch (error) {
        console.error('Failed to load item detail:', error);
      } finally {
        setDetailLoading(false);
      }
    }
  };

  const handleStatusUpdate = async (id: string, status: 'kept' | 'discarded') => {
    try {
      await apiClient.updateInboxItemStatus(id, status);
      setItems(prev => prev.map(i => i.id === id ? { ...i, status } : i));
      if (selectedItem?.id === id) {
        setSelectedItem(prev => prev ? { ...prev, status } : null);
      }
      // Refresh stats
      const statsData = await apiClient.getInboxStats();
      setStats(statsData);
    } catch (error) {
      Alert.alert('Error', 'Failed to update status');
    }
  };

  const handleDelete = async (id: string) => {
    Alert.alert('Delete Item', 'Are you sure you want to delete this item?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.deleteInboxItem(id);
            setItems(prev => prev.filter(i => i.id !== id));
            if (selectedItem?.id === id) setSelectedItem(null);
            const statsData = await apiClient.getInboxStats();
            setStats(statsData);
          } catch (error) {
            Alert.alert('Error', 'Failed to delete item');
          }
        },
      },
    ]);
  };

  const handleDiscuss = (item: InboxItem) => {
    setSelectedItem(null);
    // Navigate to Chat with inboxItem context
    navigateToChat({
      inboxItem: {
        id: item.id,
        title: item.title || 'Shared content',
      },
    });
  };

  const handleOpenUrl = (url: string) => {
    ExpoLinking.openURL(url).catch(() => {
      Alert.alert('Error', 'Failed to open URL');
    });
  };

  const renderItem = ({ item }: { item: InboxItem }) => {
    const icon = CONTENT_TYPE_ICONS[item.content_type] || '📋';
    const statusColor = STATUS_COLORS[item.status] || colors.textMuted;
    const isExtracting = item.extraction_status === 'pending' || item.extraction_status === 'extracting';

    return (
      <TouchableOpacity
        style={[styles.itemCard, item.status === 'unread' && styles.itemCardUnread]}
        onPress={() => handleItemPress(item)}
        onLongPress={() => handleDelete(item.id)}
      >
        <View style={styles.itemHeader}>
          <Text style={styles.itemIcon}>{icon}</Text>
          <View style={styles.itemMeta}>
            <Text style={styles.itemTitle} numberOfLines={2}>
              {item.title || 'Untitled'}
            </Text>
            <View style={styles.itemSubRow}>
              {item.original_url && (
                <Text style={styles.itemDomain}>{getDomain(item.original_url)}</Text>
              )}
              <Text style={styles.itemTime}>{timeAgo(item.shared_at)}</Text>
            </View>
          </View>
          <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
        </View>
        {item.description && (
          <Text style={styles.itemDescription} numberOfLines={2}>
            {item.description}
          </Text>
        )}
        {isExtracting && (
          <View style={styles.extractingRow}>
            <ActivityIndicator size="small" color={colors.primary} />
            <Text style={styles.extractingText}>Extracting content...</Text>
          </View>
        )}
        {item.word_count && (
          <Text style={styles.wordCount}>{item.word_count.toLocaleString()} words</Text>
        )}
      </TouchableOpacity>
    );
  };

  const filterTabs = [
    { key: 'all', label: 'All', count: stats?.total },
    { key: 'unread', label: 'Unread', count: stats?.unread },
    { key: 'read', label: 'Read', count: stats?.read },
    { key: 'kept', label: 'Kept', count: stats?.kept },
  ];

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Share Input */}
      <View style={styles.shareContainer}>
        <TextInput
          style={styles.shareInput}
          placeholder="Paste a URL or type something to save..."
          placeholderTextColor={colors.textMuted}
          value={shareInput}
          onChangeText={setShareInput}
          onSubmitEditing={handleShare}
          returnKeyType="send"
          autoCapitalize="none"
          autoCorrect={false}
        />
        {shareInput ? (
          <TouchableOpacity
            style={[styles.shareButton, sharing && styles.shareButtonDisabled]}
            onPress={handleShare}
            disabled={sharing}
          >
            {sharing ? (
              <ActivityIndicator size="small" color={colors.text} />
            ) : (
              <Text style={styles.shareButtonText}>Share</Text>
            )}
          </TouchableOpacity>
        ) : (
          <TouchableOpacity style={styles.pasteButton} onPress={handlePasteAndShare}>
            <Text style={styles.pasteButtonText}>Paste</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Filter Tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.filterContainer}
        contentContainerStyle={styles.filterContent}
      >
        {filterTabs.map(tab => (
          <TouchableOpacity
            key={tab.key}
            style={[styles.filterTab, filter === tab.key && styles.filterTabActive]}
            onPress={() => { setFilter(tab.key); setLoading(true); }}
          >
            <Text style={[styles.filterTabText, filter === tab.key && styles.filterTabTextActive]}>
              {tab.label}
              {tab.count !== undefined ? ` (${tab.count})` : ''}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Item List */}
      <FlatList
        data={items}
        renderItem={renderItem}
        keyExtractor={item => item.id}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={colors.primary}
          />
        }
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyIcon}>📥</Text>
            <Text style={styles.emptyText}>
              {filter === 'all'
                ? 'No items yet. Share a URL or text above!'
                : `No ${filter} items`}
            </Text>
          </View>
        }
      />

      {/* Detail Modal */}
      <Modal
        visible={selectedItem !== null}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setSelectedItem(null)}
      >
        <SafeAreaView style={styles.modalContainer}>
          {selectedItem && (
            <>
              {/* Modal Header */}
              <View style={styles.modalHeader}>
                <TouchableOpacity onPress={() => setSelectedItem(null)}>
                  <Text style={styles.modalClose}>Close</Text>
                </TouchableOpacity>
                <View style={styles.modalActions}>
                  {selectedItem.status !== 'kept' && (
                    <TouchableOpacity
                      style={[styles.actionButton, styles.keepButton]}
                      onPress={() => handleStatusUpdate(selectedItem.id, 'kept')}
                    >
                      <Text style={styles.actionButtonText}>Keep</Text>
                    </TouchableOpacity>
                  )}
                  {selectedItem.status !== 'discarded' && (
                    <TouchableOpacity
                      style={[styles.actionButton, styles.discardButton]}
                      onPress={() => handleStatusUpdate(selectedItem.id, 'discarded')}
                    >
                      <Text style={styles.actionButtonText}>Discard</Text>
                    </TouchableOpacity>
                  )}
                  <TouchableOpacity
                    style={[styles.actionButton, styles.discussButton]}
                    onPress={() => handleDiscuss(selectedItem)}
                  >
                    <Text style={styles.actionButtonText}>Discuss</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* Item Detail */}
              <ScrollView style={styles.modalBody} contentContainerStyle={styles.modalBodyContent}>
                <Text style={styles.detailTitle}>
                  {CONTENT_TYPE_ICONS[selectedItem.content_type] || '📋'}{' '}
                  {selectedItem.title || 'Untitled'}
                </Text>

                {selectedItem.original_url && (
                  <TouchableOpacity onPress={() => handleOpenUrl(selectedItem.original_url!)}>
                    <Text style={styles.detailUrl}>{selectedItem.original_url}</Text>
                  </TouchableOpacity>
                )}

                <View style={styles.detailMetaRow}>
                  <Text style={styles.detailMetaText}>
                    {selectedItem.content_type} {selectedItem.word_count ? `· ${selectedItem.word_count.toLocaleString()} words` : ''}
                  </Text>
                  <View style={[styles.statusBadge, { backgroundColor: STATUS_COLORS[selectedItem.status] }]}>
                    <Text style={styles.statusBadgeText}>{selectedItem.status}</Text>
                  </View>
                </View>

                {/* Reddit metadata */}
                {selectedItem.content_type === 'reddit' && selectedItem.meta && (
                  <View style={styles.redditMeta}>
                    {selectedItem.meta.subreddit && (
                      <Text style={styles.redditSubreddit}>r/{selectedItem.meta.subreddit}</Text>
                    )}
                    {selectedItem.meta.author && (
                      <Text style={styles.redditAuthor}>u/{selectedItem.meta.author}</Text>
                    )}
                    {selectedItem.meta.score !== undefined && (
                      <Text style={styles.redditScore}>{selectedItem.meta.score} points</Text>
                    )}
                  </View>
                )}

                {detailLoading ? (
                  <View style={styles.detailLoading}>
                    <ActivityIndicator size="large" color={colors.primary} />
                    <Text style={styles.detailLoadingText}>Loading content...</Text>
                  </View>
                ) : selectedItem.extraction_status === 'extracted' && selectedItem.extracted_text ? (
                  <Text style={styles.detailText}>{selectedItem.extracted_text}</Text>
                ) : selectedItem.extraction_status === 'failed' ? (
                  <Text style={styles.detailError}>Content extraction failed</Text>
                ) : (
                  <View style={styles.detailLoading}>
                    <ActivityIndicator size="small" color={colors.primary} />
                    <Text style={styles.detailLoadingText}>Content is being extracted...</Text>
                  </View>
                )}
              </ScrollView>
            </>
          )}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },

  // Share input
  shareContainer: {
    flexDirection: 'row',
    padding: spacing.md,
    gap: spacing.sm,
  },
  shareInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  shareButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
  },
  shareButtonDisabled: {
    opacity: 0.6,
  },
  shareButtonText: {
    color: colors.text,
    fontWeight: '600',
    fontSize: fontSizes.sm,
  },
  pasteButton: {
    backgroundColor: colors.surfaceLight,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
  },
  pasteButtonText: {
    color: colors.textSecondary,
    fontWeight: '600',
    fontSize: fontSizes.sm,
  },

  // Filter tabs
  filterContainer: {
    maxHeight: 44,
  },
  filterContent: {
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  filterTab: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surface,
  },
  filterTabActive: {
    backgroundColor: colors.primary,
  },
  filterTabText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  filterTabTextActive: {
    color: colors.text,
  },

  // List
  listContent: {
    padding: spacing.md,
    paddingTop: spacing.sm,
    gap: spacing.sm,
  },

  // Item card
  itemCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  itemCardUnread: {
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
  },
  itemHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  itemIcon: {
    fontSize: 24,
    marginTop: 2,
  },
  itemMeta: {
    flex: 1,
  },
  itemTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    lineHeight: 22,
  },
  itemSubRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: 4,
  },
  itemDomain: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  itemTime: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 6,
  },
  itemDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: spacing.sm,
    lineHeight: 20,
  },
  extractingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  extractingText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  wordCount: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },

  // Empty state
  emptyContainer: {
    padding: spacing.xxl,
    alignItems: 'center',
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: spacing.md,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    textAlign: 'center',
  },

  // Detail modal
  modalContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalClose: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  modalActions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  actionButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.md,
  },
  keepButton: {
    backgroundColor: colors.success,
  },
  discardButton: {
    backgroundColor: colors.surfaceLight,
  },
  discussButton: {
    backgroundColor: colors.primary,
  },
  actionButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },

  // Detail body
  modalBody: {
    flex: 1,
  },
  modalBodyContent: {
    padding: spacing.md,
  },
  detailTitle: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
    lineHeight: 28,
    marginBottom: spacing.sm,
  },
  detailUrl: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.sm,
  },
  detailMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  detailMetaText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
  },
  statusBadgeText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
  },

  // Reddit meta
  redditMeta: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.md,
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  redditSubreddit: {
    color: colors.warning,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  redditAuthor: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  redditScore: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },

  // Detail content
  detailLoading: {
    padding: spacing.xl,
    alignItems: 'center',
    gap: spacing.sm,
  },
  detailLoadingText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
  detailText: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
  },
  detailError: {
    color: colors.error,
    fontSize: fontSizes.md,
    textAlign: 'center',
    padding: spacing.xl,
  },
});
