import React, { useState, useEffect, useCallback, useRef } from 'react';
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
  Animated,
  PanResponder,
} from 'react-native';
import * as ExpoClipboard from 'expo-clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as ExpoLinking from 'expo-linking';
import { useToast } from '../../context/ToastContext';
import { SkeletonList } from '../../components/SkeletonLoader';
import apiClient from '../../services/api';
import notesService from '../../services/notes';
import { navigateToChat, navigateToNoteEditor, navigateToTab } from '../../services/navigation';
import type { AppStackParamList } from '../../navigation/AppNavigator';
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

type InboxMode = 'content' | 'attention';
type InboxNavigationProp = NativeStackNavigationProp<AppStackParamList, 'Inbox'>;
type InboxRouteProp = RouteProp<AppStackParamList, 'Inbox'>;

interface AttentionItem {
  id: string;
  title: string;
  body: string | null;
  category: string;
  priority: 'low' | 'normal' | 'high' | 'urgent' | 'critical';
  status: 'new' | 'sent' | 'read' | 'archived' | 'dropped';
  source: string;
  payload?: Record<string, any> | null;
  created_at: string;
}

interface AttentionCountResponse {
  counts: Record<string, number>;
  unread: number;
}

interface AttentionAction {
  id: string;
  label: string;
  kind: string;
  target?: string;
  prompt?: string;
  url?: string;
  default_minutes?: number;
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

const ATTENTION_PRIORITY_COLORS: Record<string, string> = {
  critical: '#ef4444',
  urgent: '#f97316',
  high: '#eab308',
  normal: colors.info,
  low: colors.textMuted,
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

function normalizeExtractedText(text?: string): string {
  return (text || '').replace(/\r\n/g, '\n').trim();
}

function splitTextBlocks(text?: string): string[] {
  const normalized = normalizeExtractedText(text);
  if (!normalized) return [];
  return normalized
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
}

function SwipeableArchiveRow({ children, onArchive }: { children: React.ReactNode; onArchive: () => void }) {
  const translateX = useRef(new Animated.Value(0)).current;
  const panResponder = useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_, gestureState) => Math.abs(gestureState.dx) > 15 && Math.abs(gestureState.dx) > Math.abs(gestureState.dy),
      onPanResponderMove: (_, gestureState) => {
        if (gestureState.dx < 0) {
          translateX.setValue(gestureState.dx);
        }
      },
      onPanResponderRelease: (_, gestureState) => {
        if (gestureState.dx < -80) {
          Animated.timing(translateX, { toValue: -400, duration: 200, useNativeDriver: true }).start(() => {
            onArchive();
            translateX.setValue(0);
          });
        } else {
          Animated.spring(translateX, { toValue: 0, useNativeDriver: true }).start();
        }
      },
    })
  ).current;

  return (
    <View style={{ overflow: 'hidden' }}>
      <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.error, justifyContent: 'center', alignItems: 'flex-end', paddingRight: spacing.lg }]}>
        <Text style={{ color: '#fff', fontWeight: '600', fontSize: fontSizes.sm }}>Archive</Text>
      </View>
      <Animated.View style={{ transform: [{ translateX }] }} {...panResponder.panHandlers}>
        {children}
      </Animated.View>
    </View>
  );
}

export default function InboxScreen() {
  const navigation = useNavigation<InboxNavigationProp>();
  const route = useRoute<InboxRouteProp>();
  const { showToast } = useToast();
  const initialMode: InboxMode = route?.params?.tab === 'attention' ? 'attention' : 'content';

  const [mode, setMode] = useState<InboxMode>(initialMode);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [stats, setStats] = useState<InboxStats | null>(null);
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [attentionCounts, setAttentionCounts] = useState<AttentionCountResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');
  const [attentionFilter, setAttentionFilter] = useState<'all' | 'unread' | 'read'>('all');
  const [shareInput, setShareInput] = useState('');
  const [sharing, setSharing] = useState(false);
  const [selectedItem, setSelectedItem] = useState<InboxItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expandedAttentionId, setExpandedAttentionId] = useState<string | null>(null);
  const [attentionActionBusy, setAttentionActionBusy] = useState<string | null>(null);
  const [hitlReplyText, setHitlReplyText] = useState('');
  const [hitlReplyItemId, setHitlReplyItemId] = useState<string | null>(null);
  const [hitlReplySending, setHitlReplySending] = useState(false);

  const loadContentItems = useCallback(async () => {
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

  const loadAttentionItems = useCallback(async () => {
    try {
      const [itemsData, countsData] = await Promise.all([
        apiClient.getAttentionItems(undefined, 100),
        apiClient.getAttentionCount(),
      ]);
      setAttentionItems(itemsData || []);
      setAttentionCounts(countsData || null);
    } catch (error) {
      console.error('Failed to load attention inbox:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (route?.params?.tab === 'attention') {
      setMode('attention');
    } else if (route?.params?.tab === 'content') {
      setMode('content');
    }
  }, [route?.params?.tab]);

  useEffect(() => {
    setLoading(true);
    if (mode === 'content') {
      loadContentItems();
    } else {
      loadAttentionItems();
    }
  }, [mode, loadContentItems, loadAttentionItems]);

  // Reload when screen comes into focus
  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      if (mode === 'content') {
        loadContentItems();
      } else {
        loadAttentionItems();
      }
    }, [mode, loadContentItems, loadAttentionItems])
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
          setMode('content');
          loadContentItems();
        } else if (sharedText) {
          setSharing(true);
          await apiClient.shareTextToInbox(sharedText);
          setSharing(false);
          setMode('content');
          loadContentItems();
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
    if (mode === 'content') {
      loadContentItems();
    } else {
      loadAttentionItems();
    }
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
      await loadContentItems();
    } catch (error) {
      console.error('Share failed:', error);
      showToast('error', 'Failed to share content');
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
      showToast('error', 'Failed to update status');
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
            showToast('error', 'Failed to delete item');
          }
        },
      },
    ]);
  };

  const handleDiscuss = (item: InboxItem) => {
    setSelectedItem(null);
    const chatParams = {
      inboxItem: {
        id: item.id,
        title: item.title || 'Shared content',
      },
    };

    // Route back through the tab stack first so the Sara chat surface is visible.
    setTimeout(() => {
      try {
        (navigation as any).navigate('MainTabs', {
          screen: 'Sara',
          params: chatParams,
        });
      } catch {
        navigateToChat(chatParams);
      }
    }, 0);
  };

  const handleOpenUrl = (url: string) => {
    ExpoLinking.openURL(url).catch(() => {
      showToast('error', 'Failed to open URL');
    });
  };

  const handleCopyExtractedText = async (text?: string) => {
    const normalized = normalizeExtractedText(text);
    if (!normalized) return;

    try {
      await ExpoClipboard.setStringAsync(normalized);
      showToast('success', 'Copied full text');
    } catch {
      showToast('error', 'Failed to copy text');
    }
  };

  const getAttentionActions = (item: AttentionItem): AttentionAction[] => {
    const actions = item.payload?.actions;
    if (!Array.isArray(actions)) return [];
    return actions.filter((action): action is AttentionAction =>
      !!action &&
      typeof action.id === 'string' &&
      typeof action.label === 'string' &&
      typeof action.kind === 'string'
    );
  };

  const markAttentionRead = async (id: string) => {
    try {
      await apiClient.markAttentionRead(id);
      await loadAttentionItems();
    } catch {
      showToast('error', 'Failed to mark as read');
    }
  };

  const markAttentionEngaged = async (id: string) => {
    try {
      await apiClient.engageAttentionItem(id);
      const countsData = await apiClient.getAttentionCount();
      setAttentionCounts(countsData || null);
    } catch {
      // best effort
    }
  };

  const archiveAttentionItem = async (id: string) => {
    try {
      await apiClient.archiveAttentionItem(id);
      await loadAttentionItems();
    } catch {
      showToast('error', 'Failed to archive item');
    }
  };

  const openAttentionNote = async (item: AttentionItem) => {
    try {
      const rawNoteId = String(item.payload?.note_id || '').trim();
      if (rawNoteId) {
        navigateToNoteEditor(rawNoteId);
        return;
      }

      const note = item.title.startsWith("Sara's Daily Report")
        ? await notesService.findDailyReportNote({ title: item.title })
        : await notesService.findBestMatchingNoteByTitle(item.title);
      if (note?.id) {
        navigateToNoteEditor(note.id);
        return;
      }

      showToast('error', 'Full report is not ready yet');
    } catch {
      showToast('error', 'Failed to open full report');
    }
  };

  const handleAttentionDirective = (directive?: {
    type?: string;
    target?: string;
    prompt?: string;
    url?: string;
    note_id?: string;
    note_title?: string;
    note_preview?: string;
    title?: string;
  }) => {
    if (!directive?.type) return;
    if (directive.type === 'navigate') {
      const target = (directive.target || '').toLowerCase();
      if (target === 'calendar') {
        navigation.navigate('Calendar');
      } else if (target === 'inbox') {
        setMode('content');
      } else {
        navigateToTab('More');
      }
      return;
    }

    if (directive.type === 'open_url' && directive.url) {
      ExpoLinking.openURL(directive.url).catch(() => {
        showToast('error', 'Failed to open URL');
      });
      return;
    }

    if (directive.type === 'chat') {
      if (directive.note_id) {
        navigateToChat({
          noteContext: {
            id: directive.note_id,
            title: directive.note_title || directive.title || 'Shared note',
            prompt: directive.prompt,
            preview: directive.note_preview,
          },
        });
        return;
      }

      navigateToChat({
        heartbeat: {
          title: 'Attention item',
          message: directive.prompt || 'Help me handle this.',
          priority: 'normal',
        },
      });
    }
  };

  const runAttentionAction = async (itemId: string, action: AttentionAction, params?: Record<string, any>) => {
    const busyKey = `${itemId}:${action.id}`;
    setAttentionActionBusy(busyKey);
    try {
      const result = await apiClient.runAttentionAction(itemId, action.id, params);
      handleAttentionDirective(result?.directive);
      if (result?.reminder?.title && result?.reminder?.reminder_time) {
        const when = new Date(result.reminder.reminder_time).toLocaleTimeString('en-US', {
          hour: 'numeric',
          minute: '2-digit',
        });
        showToast('success', `Reminder set: ${result.reminder.title} at ${when}`);
      }
      if (result?.calendar_event) {
        const when = new Date(result.calendar_event.start_time).toLocaleString('en-US', {
          dateStyle: 'short',
          timeStyle: 'short',
        });
        showToast('success', `Event created: ${result.calendar_event.title} at ${when}`);
      }
      if (result?.status === 'completed') {
        showToast('success', 'Item marked as completed.');
      }
      await loadAttentionItems();
    } catch {
      showToast('error', 'Could not run that action.');
    } finally {
      setAttentionActionBusy(null);
    }
  };

  const showTimePicker = (itemId: string, action: AttentionAction) => {
    const hoursFromNow = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();
    const tomorrow9am = () => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      d.setHours(9, 0, 0, 0);
      return d.toISOString();
    };

    if (action.kind === 'add_reminder') {
      Alert.alert('Remind me', 'When should I remind you?', [
        { text: '1 hour', onPress: () => runAttentionAction(itemId, action, { reminder_time: hoursFromNow(1) }) },
        { text: '3 hours', onPress: () => runAttentionAction(itemId, action, { reminder_time: hoursFromNow(3) }) },
        { text: 'Tomorrow 9am', onPress: () => runAttentionAction(itemId, action, { reminder_time: tomorrow9am() }) },
        { text: 'Cancel', style: 'cancel' },
      ]);
    } else if (action.kind === 'add_calendar') {
      Alert.alert('Add to calendar', 'When should this event be?', [
        { text: 'In 1 hour', onPress: () => runAttentionAction(itemId, action, { start_time: hoursFromNow(1) }) },
        { text: 'In 3 hours', onPress: () => runAttentionAction(itemId, action, { start_time: hoursFromNow(3) }) },
        { text: 'Tomorrow 9am', onPress: () => runAttentionAction(itemId, action, { start_time: tomorrow9am() }) },
        { text: 'Cancel', style: 'cancel' },
      ]);
    }
  };

  const handleAttentionActionPress = (itemId: string, action: AttentionAction) => {
    if (action.kind === 'hitl_reply') {
      setHitlReplyItemId(itemId);
      setHitlReplyText('');
      setExpandedAttentionId(itemId);
      return;
    }
    if (action.kind === 'add_reminder' || action.kind === 'add_calendar') {
      showTimePicker(itemId, action);
    } else {
      runAttentionAction(itemId, action);
    }
  };

  const submitHitlReply = async (itemId: string, message: string) => {
    if (!message.trim()) return;
    setHitlReplySending(true);
    try {
      await apiClient.replyToAttentionItem(itemId, message);
      showToast('success', 'Reply sent to Sara');
      setHitlReplyItemId(null);
      setHitlReplyText('');
      await loadAttentionItems();
    } catch {
      showToast('error', 'Failed to send reply');
    } finally {
      setHitlReplySending(false);
    }
  };

  const filteredAttentionItems = attentionItems.filter((item) => {
    if (attentionFilter === 'unread') {
      return item.status === 'new' || item.status === 'sent';
    }
    if (attentionFilter === 'read') {
      return item.status === 'read';
    }
    return true;
  });

  const renderAttentionItem = ({ item }: { item: AttentionItem }) => {
    const isCompleted = item.status === 'completed' as string;
    const priorityColor = ATTENTION_PRIORITY_COLORS[item.priority] || colors.textMuted;
    const actions = getAttentionActions(item);
    const isExpanded = expandedAttentionId === item.id;
    const isUnread = item.status === 'new' || item.status === 'sent';
    const isHitl = item.payload?.type === 'human_input_request';
    const hasDirectReport = Boolean(item.payload?.note_id) || item.title.startsWith("Sara's Daily Report");

    return (
      <SwipeableArchiveRow onArchive={() => handleArchiveItem(item.id)}>
      <TouchableOpacity
        style={[
          styles.itemCard,
          isUnread && styles.itemCardUnread,
          isCompleted && styles.itemCardCompleted,
          isHitl && !isCompleted && { borderLeftWidth: 3, borderLeftColor: '#f97316' },
        ]}
        onPress={() => {
          const nextExpanded = isExpanded ? null : item.id;
          setExpandedAttentionId(nextExpanded);
          if (nextExpanded && isUnread) {
            markAttentionEngaged(item.id);
          }
        }}
      >
        <View style={styles.itemHeader}>
          <View style={[styles.attentionPriorityBadge, { backgroundColor: `${priorityColor}22`, borderColor: `${priorityColor}66` }]}>
            <Text style={[styles.attentionPriorityText, { color: priorityColor }]}>{item.priority}</Text>
          </View>
          <View style={styles.itemMeta}>
            <Text style={[styles.itemTitle, isCompleted && styles.completedText]} numberOfLines={2}>
              {isCompleted ? '\u2705 ' : ''}{item.title}
            </Text>
            <View style={styles.itemSubRow}>
              <Text style={styles.itemDomain}>{item.category}</Text>
              <Text style={styles.itemTime}>{timeAgo(item.created_at)}</Text>
            </View>
          </View>
          <View style={{ flexDirection: 'row', gap: spacing.sm }}>
            {isUnread && (
              <TouchableOpacity onPress={() => markAttentionRead(item.id)}>
                <Text style={styles.attentionReadText}>Read</Text>
              </TouchableOpacity>
            )}
            {!isCompleted && (
              <TouchableOpacity onPress={() => archiveAttentionItem(item.id)}>
                <Text style={styles.attentionArchiveText}>Archive</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        {item.body && (
          <Text style={styles.itemDescription} numberOfLines={isExpanded ? undefined : 2}>
            {item.body}
          </Text>
        )}

        {!isCompleted && actions.length > 0 && (
          <View style={styles.attentionActionsRow}>
            {hasDirectReport ? (
              <TouchableOpacity
                style={[styles.attentionActionChip, styles.completeActionChip]}
                onPress={() => openAttentionNote(item)}
              >
                <Text style={[styles.attentionActionText, styles.completeActionText]}>
                  Open Full Report
                </Text>
              </TouchableOpacity>
            ) : null}
            {actions.map((action) => {
              const busy = attentionActionBusy === `${item.id}:${action.id}`;
              const isComplete = action.kind === 'complete';
              return (
                <TouchableOpacity
                  key={action.id}
                  style={[styles.attentionActionChip, isComplete && styles.completeActionChip]}
                  disabled={busy}
                  onPress={() => handleAttentionActionPress(item.id, action)}
                >
                  <Text style={[styles.attentionActionText, isComplete && styles.completeActionText]}>
                    {busy ? 'Working...' : action.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        )}

        {/* HITL inline reply */}
        {isExpanded && !isCompleted && item.payload?.type === 'human_input_request' && (
          <View style={styles.hitlReplyContainer}>
            {item.payload?.question && (
              <View style={styles.hitlQuestionBox}>
                <Text style={styles.hitlQuestionLabel}>Sara is asking:</Text>
                <Text style={styles.hitlQuestionText}>{item.payload.question}</Text>
              </View>
            )}
            <View style={styles.hitlReplyRow}>
              <TextInput
                style={styles.hitlReplyInput}
                placeholder="Type your reply..."
                placeholderTextColor={colors.textMuted}
                value={hitlReplyItemId === item.id ? hitlReplyText : ''}
                onChangeText={(text) => {
                  setHitlReplyItemId(item.id);
                  setHitlReplyText(text);
                }}
                onSubmitEditing={() => {
                  if (hitlReplyText.trim()) submitHitlReply(item.id, hitlReplyText);
                }}
                returnKeyType="send"
                editable={!hitlReplySending}
              />
              <TouchableOpacity
                style={[styles.hitlReplySend, (!hitlReplyText.trim() || hitlReplySending) && { opacity: 0.3 }]}
                disabled={!hitlReplyText.trim() || hitlReplySending}
                onPress={() => submitHitlReply(item.id, hitlReplyText)}
              >
                <Text style={styles.hitlReplySendText}>
                  {hitlReplySending ? '...' : 'Reply'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        )}
      </TouchableOpacity>
      </SwipeableArchiveRow>
    );
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
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <SkeletonList count={8} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.modeTabsRow}>
        <TouchableOpacity
          style={[styles.modeTab, mode === 'content' && styles.modeTabActive]}
          onPress={() => { setMode('content'); setLoading(true); }}
        >
          <Text style={[styles.modeTabText, mode === 'content' && styles.modeTabTextActive]}>
            Content ({stats?.unread ?? 0})
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.modeTab, mode === 'attention' && styles.modeTabActive]}
          onPress={() => { setMode('attention'); setLoading(true); }}
        >
          <Text style={[styles.modeTabText, mode === 'attention' && styles.modeTabTextActive]}>
            Attention ({attentionCounts?.unread ?? 0})
          </Text>
        </TouchableOpacity>
      </View>

      {mode === 'content' && (
        <>
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

          {/* Content List */}
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
        </>
      )}

      {mode === 'attention' && (
        <>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.filterContainer}
            contentContainerStyle={styles.filterContent}
          >
            {[
              { key: 'all', label: 'All', count: attentionItems.length },
              { key: 'unread', label: 'Unread', count: attentionCounts?.unread ?? 0 },
              { key: 'read', label: 'Read', count: attentionCounts?.counts?.read ?? 0 },
            ].map(tab => (
              <TouchableOpacity
                key={tab.key}
                style={[styles.filterTab, attentionFilter === tab.key && styles.filterTabActive]}
                onPress={() => setAttentionFilter(tab.key as 'all' | 'unread' | 'read')}
              >
                <Text style={[styles.filterTabText, attentionFilter === tab.key && styles.filterTabTextActive]}>
                  {tab.label} ({tab.count})
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          <FlatList
            data={filteredAttentionItems}
            renderItem={renderAttentionItem}
            keyExtractor={(item) => item.id}
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
                <Text style={styles.emptyIcon}>🧠</Text>
                <Text style={styles.emptyText}>
                  {attentionFilter === 'all'
                    ? 'No attention items right now.'
                    : `No ${attentionFilter} attention items`}
                </Text>
              </View>
            }
          />
        </>
      )}

      {/* Detail Modal */}
      <Modal
        visible={selectedItem !== null}
        animationType="slide"
        presentationStyle="fullScreen"
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
                  {selectedItem.extracted_text ? (
                    <TouchableOpacity
                      style={[styles.actionButton, styles.copyButton]}
                      onPress={() => handleCopyExtractedText(selectedItem.extracted_text)}
                    >
                      <Text style={styles.actionButtonText}>Copy</Text>
                    </TouchableOpacity>
                  ) : null}
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

                {selectedItem.description ? (
                  <View style={styles.detailSection}>
                    <Text style={styles.detailSectionLabel}>Summary</Text>
                    <View style={styles.detailTextCard}>
                      <Text style={styles.detailSummaryText}>{selectedItem.description}</Text>
                    </View>
                  </View>
                ) : null}

                {detailLoading ? (
                  <View style={styles.detailLoading}>
                    <ActivityIndicator size="large" color={colors.primary} />
                    <Text style={styles.detailLoadingText}>Loading content...</Text>
                  </View>
                ) : selectedItem.extraction_status === 'extracted' && selectedItem.extracted_text ? (
                  <View style={styles.detailSection}>
                    <Text style={styles.detailSectionLabel}>Captured content</Text>
                    <View style={styles.detailTextCard}>
                      {splitTextBlocks(selectedItem.extracted_text).map((block, index) => (
                        <Text
                          key={`${selectedItem.id}-block-${index}`}
                          selectable
                          style={[styles.detailText, index > 0 && styles.detailTextBlock]}
                        >
                          {block}
                        </Text>
                      ))}
                    </View>
                  </View>
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
  modeTabsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },
  modeTab: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surface,
    alignItems: 'center',
  },
  modeTabActive: {
    backgroundColor: colors.primary,
  },
  modeTabText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  modeTabTextActive: {
    color: colors.text,
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
  attentionPriorityBadge: {
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginTop: 2,
  },
  attentionPriorityText: {
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  attentionActionsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  attentionActionChip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.primary + '66',
    backgroundColor: colors.primary + '12',
  },
  attentionActionText: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  attentionReadText: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  attentionArchiveText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  itemCardCompleted: {
    opacity: 0.6,
    borderLeftWidth: 3,
    borderLeftColor: colors.success,
  },
  completedText: {
    textDecorationLine: 'line-through',
    color: colors.textMuted,
  },
  completeActionChip: {
    borderColor: colors.success + '66',
    backgroundColor: colors.success + '14',
  },
  completeActionText: {
    color: colors.success,
  },

  // HITL reply styles
  hitlReplyContainer: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: '#f9731633',
  },
  hitlQuestionBox: {
    backgroundColor: '#f9731618',
    borderWidth: 1,
    borderColor: '#f9731633',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  hitlQuestionLabel: {
    color: '#f97316',
    fontSize: fontSizes.xs,
    fontWeight: '600',
    marginBottom: 4,
  },
  hitlQuestionText: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  hitlReplyRow: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  hitlReplyInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: '#f9731644',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  hitlReplySend: {
    backgroundColor: '#f9731622',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    justifyContent: 'center',
  },
  hitlReplySendText: {
    color: '#f97316',
    fontSize: fontSizes.sm,
    fontWeight: '600',
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
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
  },
  actionButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.md,
  },
  keepButton: {
    backgroundColor: colors.success,
  },
  copyButton: {
    backgroundColor: colors.surfaceLight,
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
    paddingBottom: spacing.xxl,
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
  detailSection: {
    marginTop: spacing.md,
  },
  detailSectionLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: spacing.sm,
  },
  detailTextCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  detailSummaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 22,
  },
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
    fontSize: fontSizes.sm,
    lineHeight: 24,
  },
  detailTextBlock: {
    marginTop: spacing.md,
  },
  detailError: {
    color: colors.error,
    fontSize: fontSizes.md,
    textAlign: 'center',
    padding: spacing.xl,
  },
});
