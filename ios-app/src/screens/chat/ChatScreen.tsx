import React, { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Alert,
  TouchableOpacity,
  Text,
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  Switch,
  AppState,
  AppStateStatus,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { HealthAlertContext, NudgeContext, QuickReplyContext, HeartbeatContext, NotificationContext, NoteContext } from '../../types/navigation';
import { Message } from '../../types/api';
import { ContentCard as ContentCardType, SuggestedAction, ToolStatus } from '../../types/cards';
import { assistantAnalytics } from '../../services/assistantAnalytics';
import { chatService } from '../../services/chat';
import { surfacesService } from '../../services/surfaces';
import { voiceService } from '../../services/voice';
import { ImageAttachment } from '../../services/imagePicker';
import { DocumentAttachment } from '../../services/documentPicker';
import notesService from '../../services/notes';
import MessageBubble from '../../components/chat/MessageBubble';
import StreamingIndicator from '../../components/chat/StreamingIndicator';
import ChatInput from '../../components/chat/ChatInput';
import ContentCard from '../../components/cards/ContentCard';
import SuggestedActions from '../../components/chat/SuggestedActions';
import ToolStatusIndicator from '../../components/chat/ToolStatusIndicator';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../../styles/theme';
import { apiClient, ChatModel, ChatModelsResponse } from '../../services/api';
import { navigateToNoteEditor, handleSaraUiCommand } from '../../services/navigation';

type Props = {
  isEmbedded?: boolean;
  onBriefCollapse?: () => void;
  navigation?: any;
  route?: any;
};

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Claude',
  google: 'Gemini',
  openai: 'OpenAI',
  codex: 'ChatGPT Codex',
  local: 'Local',
};

type ConversationContextState = {
  kind: 'inbox' | 'notification' | 'note';
  title: string;
  summary: string;
  sourceLabel: string;
  primaryActionLabel: string;
  primaryPrompt: string;
  inboxItemId?: string;
  noteId?: string;
  previewText?: string;
};

type PendingMessageSourceState = {
  entryPoint: string;
  label?: string;
  target?: string;
  contextKind?: ConversationContextState['kind'];
};

function normalizeNoteReaderText(text?: string | null): string {
  return (text || '').replace(/\r\n/g, '\n').trim();
}

function splitNoteReaderBlocks(text?: string | null): string[] {
  return normalizeNoteReaderText(text)
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
}

function ChatScreenInner(props: Props, ref: React.Ref<any>) {
  // Handle both standalone and embedded modes
  const isEmbedded = 'isEmbedded' in props && props.isEmbedded;
  const onBriefCollapse = 'onBriefCollapse' in props ? props.onBriefCollapse : undefined;
  const navigation = 'navigation' in props ? props.navigation : undefined;
  const route = 'route' in props ? props.route : undefined;
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  // Content cards and suggested actions state
  const [pendingCards, setPendingCards] = useState<ContentCardType[]>([]);
  const [suggestedActions, setSuggestedActions] = useState<SuggestedAction[]>([]);
  const [activeToolStatus, setActiveToolStatus] = useState<ToolStatus | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [voiceInitialized, setVoiceInitialized] = useState(false);
  const [continuousVoiceMode, setContinuousVoiceMode] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // Start true: the mount history loader (which fully replaces `messages`) is
  // async, so it doesn't flip this flag until after its first `await`. If we
  // started at false, the "process pending contexts" effect would inject a seed
  // (heartbeat / "Reply to Sara" prompt / tapped-notification message) before
  // history finished, and the history load would then clobber it. Starting true
  // holds the seed behind the gate; the loader's `finally` flips it false, which
  // re-runs the seed effect and appends the seed AFTER history is in place.
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  // Empty = no override; adopted from the server's default once models load.
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [isEphemeral, setIsEphemeral] = useState(false);
  // Phase 12K item 4 — inbox chip: pending notifications + Needs-You items count.
  const [inboxCount, setInboxCount] = useState(0);
  const [availableModels, setAvailableModels] = useState<ChatModelsResponse | null>(null);
  const [showConversationControls, setShowConversationControls] = useState(false);
  const [conversationContext, setConversationContext] = useState<ConversationContextState | null>(null);
  const [contextExpanded, setContextExpanded] = useState(false);
  // Collapse the context summary whenever a new context loads.
  useEffect(() => { setContextExpanded(false); }, [conversationContext?.title]);
  const [noteReaderVisible, setNoteReaderVisible] = useState(false);
  const [noteReaderTitle, setNoteReaderTitle] = useState('');
  const [noteReaderContent, setNoteReaderContent] = useState('');
  const [noteReaderLoading, setNoteReaderLoading] = useState(false);
  const flatListRef = useRef<FlatList>(null);
  const messagesRef = useRef<Message[]>([]);
  const streamingMessageRef = useRef('');
  // Mirror of pendingCards. The streaming onComplete closure captures state from
  // when the request started (pendingCards just cleared to []), so reading
  // pendingCards there loses every card that streamed in. Read the ref instead.
  const pendingCardsRef = useRef<ContentCardType[]>([]);

  // Surfaces (interactive checklists / cook-mode) are persistent DB rows, but
  // reloaded chat history comes back without cards. Re-inject any active
  // surfaces for the conversation onto the last assistant message so they
  // survive screen switches and cross-device.
  const attachActiveSurfaces = useCallback(
    async (msgs: Message[], convId: string | null): Promise<Message[]> => {
      if (!convId) return msgs;
      try {
        const surfaces = await surfacesService.list({ status: 'active', conversation_id: convId });
        if (!surfaces.length) return msgs;
        const cards = surfaces.map((s) => ({ card_type: 'surface_card', title: s.title, surface: s })) as any[];
        const copy = [...msgs];
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].role === 'assistant') {
            copy[i] = { ...copy[i], cards };
            return copy;
          }
        }
        return copy;
      } catch {
        return msgs;
      }
    },
    []
  );
  const isRecordingRef = useRef(false);
  const shouldResumeListening = useRef(false);
  const hasLoadedHistory = useRef(false);
  const handledHealthAlertRef = useRef<string | null>(null);
  const handledNudgeRef = useRef<string | null>(null);
  const handledQuickReplyRef = useRef<string | null>(null);
  const handledHeartbeatRef = useRef<string | null>(null);

  // Track background state for resuming chat
  const wasStreamingWhenBackgroundedRef = useRef(false);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);

  // Track pending contexts to send after component is ready
  const pendingHealthAlertRef = useRef<HealthAlertContext | null>(null);
  const pendingNudgeRef = useRef<NudgeContext | null>(null);
  const pendingQuickReplyRef = useRef<QuickReplyContext | null>(null);
  const pendingHeartbeatRef = useRef<HeartbeatContext | null>(null);
  // Counter to trigger the processing effect when a pending ref is set
  const [pendingContextTrigger, setPendingContextTrigger] = useState(0);
  const pendingInboxItemRef = useRef<{ id: string; title: string } | null>(null);
  const handledInboxItemRef = useRef<string | null>(null);
  const pendingNoteContextRef = useRef<NoteContext | null>(null);
  const handledNoteContextRef = useRef<string | null>(null);
  const pendingNotificationRef = useRef<NotificationContext | null>(null);
  const handledNotificationRef = useRef<string | null>(null);
  const pendingMessageSourceRef = useRef<PendingMessageSourceState | null>(null);
  const lastChatOpenedAtRef = useRef(0);

  const resolveNoteId = useCallback(async (noteId?: string, noteTitle?: string) => {
    const normalizedId = (noteId || '').trim();
    if (normalizedId) {
      return normalizedId;
    }

    const normalizedTitle = (noteTitle || '').trim();
    if (!normalizedTitle) {
      return null;
    }

    try {
      const note = normalizedTitle.startsWith("Sara's Daily Report")
        ? await notesService.findDailyReportNote({ title: normalizedTitle })
        : await notesService.findBestMatchingNoteByTitle(normalizedTitle);
      return note?.id ?? null;
    } catch (error) {
      console.error('[Chat] Failed to resolve note by title:', error);
      return null;
    }
  }, []);

  const fetchFullNoteText = useCallback(async (noteId?: string, fallbackText?: string, noteTitle?: string) => {
    const fallback = normalizeNoteReaderText(fallbackText);

    const resolvedId = await resolveNoteId(noteId, noteTitle);
    if (!resolvedId) {
      return fallback;
    }

    try {
      const note = await notesService.getNote(resolvedId);
      return normalizeNoteReaderText(note.content) || fallback;
    } catch (error) {
      console.error('[Chat] Failed to load full note content:', error);
      return fallback;
    }
  }, [resolveNoteId]);

  const hydrateNoteConversationContext = useCallback(async (noteContext: NoteContext) => {
    const fullText = await fetchFullNoteText(noteContext.id, noteContext.preview, noteContext.title);
    if (!fullText) return;

    setConversationContext((current) => {
      if (!current || current.kind !== 'note' || current.noteId !== noteContext.id) {
        return current;
      }
      if (current.previewText === fullText) {
        return current;
      }
      return {
        ...current,
        previewText: fullText,
      };
    });
  }, [fetchFullNoteText]);

  const openNoteReader = useCallback(async () => {
    if (!conversationContext || conversationContext.kind !== 'note') return;

    const fallbackText = conversationContext.previewText || '';
    setNoteReaderTitle(conversationContext.title);
    setNoteReaderContent(fallbackText);
    setNoteReaderVisible(true);
    setNoteReaderLoading(true);

    const fullText = await fetchFullNoteText(
      conversationContext.noteId,
      fallbackText,
      conversationContext.title,
    );
    setNoteReaderContent(fullText || 'No report content is available yet.');
    setNoteReaderLoading(false);
  }, [conversationContext, fetchFullNoteText]);

  const openFullNote = useCallback(async () => {
    if (!conversationContext || conversationContext.kind !== 'note') return;

    const resolvedId = await resolveNoteId(conversationContext.noteId, conversationContext.title);
    if (resolvedId) {
      setNoteReaderVisible(false);
      navigateToNoteEditor(resolvedId);
      return;
    }

    await openNoteReader();
  }, [conversationContext, openNoteReader, resolveNoteId]);

  // Keep latest messages in a ref so async voice/text handlers don't use stale closures.
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useFocusEffect(
    useCallback(() => {
      const now = Date.now();
      if (now - lastChatOpenedAtRef.current > 15000) {
        lastChatOpenedAtRef.current = now;
        assistantAnalytics.track('assistant.chat_opened', {
          screen: isEmbedded ? 'sara_embedded' : 'chat',
          resumed_conversation: Boolean(conversationId),
          has_messages: messagesRef.current.length > 0,
        });
      }
    }, [conversationId, isEmbedded]),
  );

  // Handle inbox item discussion from navigation params
  useEffect(() => {
    if (!route || !navigation) return;
    const inboxItem = route.params?.inboxItem as { id: string; title: string } | undefined;
    if (!inboxItem) return;

    if (handledInboxItemRef.current === inboxItem.id) return;
    handledInboxItemRef.current = inboxItem.id;

    console.log('[Chat] Inbox item received, queuing for discussion:', inboxItem);
    pendingInboxItemRef.current = inboxItem;
    setPendingContextTrigger(t => t + 1);

    navigation.setParams({ inboxItem: undefined });
  }, [route?.params?.inboxItem, navigation]);

  useEffect(() => {
    if (!route || !navigation) return;
    const noteContext = route.params?.noteContext as NoteContext | undefined;
    if (!noteContext) return;

    if (handledNoteContextRef.current === noteContext.id) return;
    handledNoteContextRef.current = noteContext.id;

    console.log('[Chat] Note context received, queuing for discussion:', noteContext);
    pendingNoteContextRef.current = noteContext;
    setPendingContextTrigger(t => t + 1);

    navigation.setParams({ noteContext: undefined });
  }, [route?.params?.noteContext, navigation]);

  // Handle health alert from push notification
  useEffect(() => {
    if (!route || !navigation) return;
    const healthAlert = route.params?.healthAlert;
    if (!healthAlert) return;

    // Don't re-handle the same alert
    const alertKey = `${healthAlert.insightId || healthAlert.title}`;
    if (handledHealthAlertRef.current === alertKey) return;
    handledHealthAlertRef.current = alertKey;

    console.log('[Chat] Health alert received, queuing for conversation:', healthAlert);
    pendingHealthAlertRef.current = healthAlert;
    setPendingContextTrigger(t => t + 1);

    // Clear the params
    navigation.setParams({ healthAlert: undefined });
  }, [route?.params?.healthAlert, navigation]);

  // Handle nudge from push notification (meal reminders, morning check-ins, etc.)
  useEffect(() => {
    if (!route || !navigation) return;
    const nudge = route.params?.nudge;
    if (!nudge) return;

    // Don't re-handle the same nudge
    const nudgeKey = `${nudge.nudgeType}-${nudge.title}`;
    if (handledNudgeRef.current === nudgeKey) return;
    handledNudgeRef.current = nudgeKey;

    console.log('[Chat] Nudge received, queuing for conversation:', nudge);
    pendingNudgeRef.current = nudge;
    setPendingContextTrigger(t => t + 1);

    // Clear the params
    navigation.setParams({ nudge: undefined });
  }, [route?.params?.nudge, navigation]);

  // Handle quick reply from notification action button
  useEffect(() => {
    if (!route || !navigation) return;
    const quickReply = route.params?.quickReply;
    if (!quickReply) return;

    // Don't re-handle the same reply
    const replyKey = `${quickReply.message}-${Date.now()}`;
    if (handledQuickReplyRef.current === replyKey) return;
    handledQuickReplyRef.current = replyKey;

    console.log('[Chat] Quick reply received:', quickReply);
    pendingQuickReplyRef.current = quickReply;
    setPendingContextTrigger(t => t + 1);

    // Clear the params
    navigation.setParams({ quickReply: undefined });
  }, [route?.params?.quickReply, navigation]);

  // Handle heartbeat notification (proactive check-ins from Sara)
  useEffect(() => {
    if (!route || !navigation) return;
    const heartbeat = route.params?.heartbeat;
    if (!heartbeat) return;

    // Don't re-handle the same heartbeat
    const heartbeatKey = `${heartbeat.title}-${heartbeat.message.slice(0, 20)}`;
    if (handledHeartbeatRef.current === heartbeatKey) return;
    handledHeartbeatRef.current = heartbeatKey;

    console.log('[Chat] Heartbeat notification received, queuing for conversation:', heartbeat);
    pendingHeartbeatRef.current = heartbeat;
    setPendingContextTrigger(t => t + 1);

    // Clear the params
    navigation.setParams({ heartbeat: undefined });
  }, [route?.params?.heartbeat, navigation]);

  // Handle notification context (from NotificationsScreen "Chat with Sara about this")
  useEffect(() => {
    if (!route || !navigation) return;
    const notification = route.params?.notification as NotificationContext | undefined;
    if (!notification) return;

    // Don't re-handle the same notification
    if (handledNotificationRef.current === notification.id) return;
    handledNotificationRef.current = notification.id;

    console.log('[Chat] Notification context received, queuing for conversation:', notification);
    pendingNotificationRef.current = notification;
    setPendingContextTrigger(t => t + 1);

    // Clear the params
    navigation.setParams({ notification: undefined });
  }, [route?.params?.notification, navigation]);

  // Handle task chat inject — backend persisted result to conversation, reload it
  useEffect(() => {
    if (!route || !navigation) return;
    const taskInject = route.params?.taskInject as { taskId: string; conversationId?: string; noteId?: string } | undefined;
    if (!taskInject) return;

    console.log('[Chat] Task inject received, reloading conversation:', taskInject);
    navigation.setParams({ taskInject: undefined });

    // Reload conversation history to pick up the new episode
    const reloadConversation = async () => {
      try {
        const cid = taskInject.conversationId || conversationId;
        if (!cid) return;
        const messagesResponse = await apiClient.get(
          `/api/conversations/${cid}/messages?limit=100`
        );
        const messagesData = messagesResponse as any;
        if (messagesData && messagesData.length > 0) {
          const loadedMessages: Message[] = messagesData.map((ep: any) => ({
            id: ep.id,
            role: ep.role,
            content: ep.content,
            created_at: ep.created_at,
            episode_id: ep.id,
          }));
          setMessages(await attachActiveSurfaces(loadedMessages, cid));
        }
      } catch (error) {
        console.error('[Chat] Error reloading after task inject:', error);
      }
    };
    reloadConversation();
  }, [route?.params?.taskInject, navigation]);

  // Load conversation history on mount
  useEffect(() => {
    const loadConversationHistory = async () => {
      if (hasLoadedHistory.current) return;
      hasLoadedHistory.current = true;

      try {
        setIsLoadingHistory(true);

        const candidateIds: string[] = [];

        // First, check for a cross-device active session (e.g. started on desktop)
        try {
          const sessionData = await chatService.getActiveSession();
          const sessionConvId = sessionData.session?.conversation_id;
          if (sessionData.active && sessionConvId && sessionConvId !== 'unknown') {
            candidateIds.push(sessionConvId);
            console.log('[Chat] Resuming cross-device session:', sessionConvId, 'from', sessionData.session?.last_device);
          }
        } catch {
          // Non-critical — fall through to conversations/active
        }

        // Also try the per-device active conversation, in case the session id is stale
        try {
          const activeResponse = await apiClient.get('/api/conversations/active');
          const activeConvId = (activeResponse as any)?.conversation_id || null;
          if (activeConvId && !candidateIds.includes(activeConvId)) {
            candidateIds.push(activeConvId);
          }
        } catch {
          // Non-critical
        }

        if (candidateIds.length === 0) {
          console.log('[Chat] No active conversation found');
          return;
        }

        for (const savedConversationId of candidateIds) {
          console.log('[Chat] Loading conversation history for:', savedConversationId);

          const messagesResponse = await apiClient.get(
            `/api/conversations/${savedConversationId}/messages?limit=100`
          );

          const messagesData = messagesResponse as any;

          if (messagesData && messagesData.length > 0) {
            // Convert Episode format to Message format
            const loadedMessages: Message[] = messagesData.map((ep: any) => ({
              id: ep.id,
              role: ep.role,
              content: ep.content,
              created_at: ep.created_at,
              episode_id: ep.id,  // Map episode ID for rating
            }));

            setMessages(await attachActiveSurfaces(loadedMessages, savedConversationId));
            setConversationId(savedConversationId);
            console.log(`[Chat] Loaded ${loadedMessages.length} messages from conversation ${savedConversationId}`);
            return;
          }
          console.log('[Chat] Conversation had no messages, trying next candidate:', savedConversationId);
        }
      } catch (error) {
        console.error('[Chat] Error loading conversation history:', error);
      } finally {
        setIsLoadingHistory(false);
      }
    };

    loadConversationHistory();
  }, []);

  // Fetch available chat models on mount
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const models = await apiClient.getChatModels();
        setAvailableModels(models);
        if (models.default && !selectedModel) {
          setSelectedModel(models.default);
        }
      } catch (error) {
        console.error('[Chat] Failed to fetch chat models:', error);
      }
    };
    fetchModels();
  }, []);

  // Handle app state changes (background/foreground)
  // When app goes to background while streaming, we need to reload conversation
  // when returning to get the completed response
  useEffect(() => {
    const reloadConversationHistory = async () => {
      try {
        let reloadId = conversationId;

        // If we don't have a conversationId yet (new conversation where the
        // final_response SSE event never arrived), discover it from the backend.
        if (!reloadId) {
          console.log('[Chat] No conversationId — discovering from backend...');
          // Try the stored active conversation first
          try {
            const activeResponse = await apiClient.get('/api/conversations/active');
            reloadId = (activeResponse as any)?.conversation_id || null;
          } catch {
            // ignore — best-effort
          }
          // Fall back to the most recent conversation
          if (!reloadId) {
            try {
              const convList = await apiClient.get('/api/conversations/list?limit=1') as any[];
              if (convList?.length > 0) {
                reloadId = convList[0].conversation_id;
              }
            } catch {
              // ignore — best-effort
            }
          }
          if (!reloadId) {
            console.log('[Chat] No conversation found, cannot reload');
            return;
          }
          // Persist the discovered id so future reloads and saves work
          setConversationId(reloadId);
        }

        console.log('[Chat] Reloading conversation after returning from background...', reloadId);
        const messagesResponse = await apiClient.get(
          `/api/conversations/${reloadId}/messages?limit=100`
        );

        const messagesData = messagesResponse as any;

        if (messagesData && messagesData.length > 0) {
          const loadedMessages: Message[] = messagesData.map((ep: any) => ({
            id: ep.id,
            role: ep.role,
            content: ep.content,
            created_at: ep.created_at,
            episode_id: ep.id,
          }));

          setMessages(await attachActiveSurfaces(loadedMessages, reloadId));
          console.log(`[Chat] Reloaded ${loadedMessages.length} messages`);
        }
      } catch (error) {
        console.error('[Chat] Error reloading conversation history:', error);
      }
    };

    const handleAppStateChange = (nextAppState: AppStateStatus) => {
      console.log('[Chat] AppState changed:', appStateRef.current, '->', nextAppState);

      // App is going to background
      if (appStateRef.current === 'active' && nextAppState.match(/inactive|background/)) {
        if (isStreaming) {
          console.log('[Chat] App backgrounded while streaming - will reload on return');
          wasStreamingWhenBackgroundedRef.current = true;
        }
      }

      // App is returning to foreground
      if (appStateRef.current.match(/inactive|background/) && nextAppState === 'active') {
        if (wasStreamingWhenBackgroundedRef.current) {
          console.log('[Chat] App returned from background - reloading conversation');
          // Don't reset flag yet — the XHR error callback may fire after this handler.
          // Delay the reset so the error handler can still see the flag and suppress the alert.
          setTimeout(() => {
            wasStreamingWhenBackgroundedRef.current = false;
          }, 2000);
          setIsStreaming(false);
          setStreamingMessage('');
          streamingMessageRef.current = '';
          // Reload conversation to get completed response
          reloadConversationHistory();
        }
      }

      appStateRef.current = nextAppState;
    };

    const subscription = AppState.addEventListener('change', handleAppStateChange);

    return () => {
      subscription.remove();
    };
  }, [conversationId, isStreaming]);

  // Save active conversation when conversation_id changes
  useEffect(() => {
    const saveActiveConversation = async () => {
      if (!conversationId) return;

      try {
        await apiClient.post('/api/conversations/active', { conversation_id: conversationId });
        console.log('[Chat] Saved active conversation:', conversationId);
      } catch (error) {
        console.error('[Chat] Error saving active conversation:', error);
      }
    };

    saveActiveConversation();
  }, [conversationId]);

  // Initialize voice on mount
  useEffect(() => {
    const initVoice = async () => {
      const initialized = await voiceService.initialize();
      setVoiceInitialized(initialized);
      if (!initialized) {
        console.log('[Chat] Voice not available');
      }
    };
    initVoice();

    return () => {
      voiceService.cleanup();
    };
  }, []);

  // Expose sendMessage to parent via ref
  useImperativeHandle(ref, () => ({
    sendMessage: (text: string) => handleSendMessage(text),
  }));

  const messageContentToText = (content: any): string => {
    if (typeof content === 'string') return content;
    if (!Array.isArray(content)) return '';
    return content
      .filter((part: any) => part?.type === 'text' && typeof part?.text === 'string')
      .map((part: any) => part.text)
      .join('\n')
      .trim();
  };

  const resolveAssistantResponseText = async (rawText: string, convId?: string | null): Promise<string> => {
    const direct = (rawText || '').trim();
    if (direct) return direct;
    if (!convId) return '';
    try {
      const history = await chatService.getConversationHistory(convId);
      for (let i = history.length - 1; i >= 0; i -= 1) {
        const msg = history[i];
        if (msg.role !== 'assistant') continue;
        const text = messageContentToText(msg.content);
        if (text) return text;
      }
    } catch (e) {
      console.warn('[Chat] Failed to recover assistant response from history:', e);
    }
    return '';
  };

  // Inbox chip (12K.4): keep the pending count fresh; refetch after each stream
  // completes (an ack in that turn drops it).
  const loadInboxCount = useCallback(async () => {
    try {
      const r = await apiClient.get<{ badge: number }>('/api/assistant-inbox/badge');
      setInboxCount(r?.badge || 0);
    } catch { /* noop */ }
  }, []);
  useEffect(() => {
    loadInboxCount();
    const id = setInterval(loadInboxCount, 30000);
    return () => clearInterval(id);
  }, [loadInboxCount]);
  useEffect(() => { if (!isStreaming) loadInboxCount(); }, [isStreaming, loadInboxCount]);

  const handleSendMessage = async (
    messageText: string,
    images?: ImageAttachment[],
    documents?: DocumentAttachment[],
    inboxItemId?: string,
    noteId?: string,
  ) => {
    const activeConversationContext = conversationContext;
    const pendingMessageSource = pendingMessageSourceRef.current;
    pendingMessageSourceRef.current = null;
    const resolvedInboxItemId = inboxItemId || activeConversationContext?.inboxItemId;
    const resolvedNoteId = noteId || activeConversationContext?.noteId;

    // Clear previous suggestions when sending new message
    setSuggestedActions([]);
    setPendingCards([]);
    pendingCardsRef.current = [];
    setActiveToolStatus(null);
    if (activeConversationContext) {
      setConversationContext(null);
    }

    // Collapse brief when typing (embedded mode)
    if (isEmbedded && onBriefCollapse) {
      onBriefCollapse();
    }

    // Haptic feedback
    try { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); } catch {}

    // Add user message immediately
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: messageText,
      created_at: new Date().toISOString(),
    };

    assistantAnalytics.track('assistant.message_sent', {
      input_mode: 'text',
      has_images: Boolean(images?.length),
      has_documents: Boolean(documents?.length),
      has_context: Boolean(activeConversationContext),
      context_kind: activeConversationContext?.kind || pendingMessageSource?.contextKind || null,
      entry_point: pendingMessageSource?.entryPoint || 'composer',
      label: pendingMessageSource?.label || null,
      target: pendingMessageSource?.target || null,
      inbox_item_id: resolvedInboxItemId || null,
      note_id: resolvedNoteId || null,
    });

    const updatedMessages = [...messagesRef.current, userMessage];
    setMessages(updatedMessages);
    setIsStreaming(true);
    setStreamingMessage('');
    streamingMessageRef.current = '';

    // Send FULL conversation history to backend with streaming
    // Filter out the welcome message - it's not part of the real conversation
    const conversationMessages = updatedMessages.filter(m => m.id !== 'welcome');

    console.log('[Chat] 📤 Sending message with conversationId:', conversationId, 'model:', selectedModel, 'ephemeral:', isEphemeral, 'images:', images?.length || 0);

    await chatService.sendMessage(
      {
        messages: conversationMessages,  // Send full history, not just new message
        conversationId,
        images,  // Pass images to the service
        documents,  // Pass document attachments (PDF/Word/text) to the service
        model: selectedModel,  // Pass selected model
        ephemeral: isEphemeral,  // Pass ephemeral mode
        inboxItemId: resolvedInboxItemId,  // Pass inbox item for discussion context
        noteId: resolvedNoteId,  // Pass note for report/note discussion context
        source: isEmbedded ? 'ios' : 'ios',
        onContentCard: (card: any) => {
          pendingCardsRef.current = [...pendingCardsRef.current, card];
          setPendingCards(prev => [...prev, card]);
        },
        onToolStatus: (status: ToolStatus) => {
          setActiveToolStatus(status.status === 'executing' ? status : null);
        },
        onSuggestedActions: (actions: SuggestedAction[]) => {
          setSuggestedActions(actions);
        },
        onUiCommand: handleSaraUiCommand,
      },
      // onChunk - called for each piece of streaming text
      (chunk: string) => {
        streamingMessageRef.current += chunk;
        setStreamingMessage(streamingMessageRef.current);
      },
      // onComplete - called when streaming finishes
      async (newConversationId: string, episodeId?: string) => {
        // Haptic feedback on complete
        try { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); } catch {}

        const resolvedConversationId = newConversationId || conversationId;
        const responseText = await resolveAssistantResponseText(
          streamingMessageRef.current,
          resolvedConversationId
        );

        // Add the complete assistant message with episode_id and cards
        const assistantMessage: Message = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: responseText || 'I finished thinking, but no visible response text was returned.',
          created_at: new Date().toISOString(),
          episode_id: episodeId,  // Include episode_id for star rating
          cards: [...pendingCardsRef.current],  // Attach accumulated cards (ref avoids stale closure)
        };

        console.log('[Chat] 📝 Creating assistant message with episode_id:', episodeId, 'cards:', pendingCardsRef.current.length);
        setMessages((prev) => [...prev, assistantMessage]);
        setStreamingMessage('');
        streamingMessageRef.current = '';
        setIsStreaming(false);
        setPendingCards([]);
        pendingCardsRef.current = [];
        setActiveToolStatus(null);

        // Always update conversation_id if backend provides one
        console.log('[Chat] 📨 Received conversation_id from backend:', newConversationId);
        console.log('[Chat] 📊 Current conversation_id:', conversationId);
        if (resolvedConversationId) {
          if (resolvedConversationId !== conversationId) {
            console.log('[Chat] 🔄 Updating conversation_id from', conversationId, 'to', resolvedConversationId);
            setConversationId(resolvedConversationId);
          } else {
            console.log('[Chat] ✅ conversation_id already matches');
          }
        } else {
          console.warn('[Chat] ⚠️ No conversation_id received from backend!');
        }
      },
      // onError
      (error: Error) => {
        console.error('Chat error:', error);
        setIsStreaming(false);
        setStreamingMessage('');
        streamingMessageRef.current = '';

        // If the app was backgrounded during streaming, don't show error -
        // the AppState handler will reload the completed response
        if (wasStreamingWhenBackgroundedRef.current) {
          console.log('[Chat] Suppressing error - app was backgrounded during stream, will reload on foreground');
          return;
        }

        Alert.alert(
          'Error',
          'Failed to send message. Please check your connection and try again.'
        );
      }
    );
  };

  // Process pending contexts after handleSendMessage is available
  useEffect(() => {
    if (isStreaming || isLoadingHistory) return;

    // Process health alert - show as Sara's message (she detected the issue)
    if (pendingHealthAlertRef.current) {
      const healthAlert = pendingHealthAlertRef.current;
      pendingHealthAlertRef.current = null;

      setTimeout(() => {
        // Build Sara's alert message
        const alertContent = healthAlert.body
          ? `🏥 **Health Alert: ${healthAlert.title}**\n\n${healthAlert.body}\n\nLet me know if you'd like me to explain more or suggest what to do.`
          : `🏥 **Health Alert: ${healthAlert.title || 'I noticed something'}**\n\nI detected some changes in your health metrics that I wanted to bring to your attention. Would you like me to explain what I noticed?`;

        // Add as Sara's message (assistant role)
        const saraMessage: Message = {
          id: `sara-alert-${Date.now()}`,
          role: 'assistant',
          content: alertContent,
          created_at: new Date().toISOString(),
        };

        console.log('[Chat] Adding health alert as Sara message');
        setMessages((prev) => [...prev, saraMessage]);
      }, 300);
      return;
    }

    // Process nudge (meal reminders, morning check-ins, etc.)
    if (pendingNudgeRef.current) {
      const nudge = pendingNudgeRef.current;
      pendingNudgeRef.current = null;

      setTimeout(() => {
        // Add Sara's nudge as her message — user can reply naturally
        const saraMessage: Message = {
          id: `sara-nudge-${Date.now()}`,
          role: 'assistant',
          content: nudge.message,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, saraMessage]);
        console.log('[Chat] Added nudge message from Sara');
      }, 300);
      return;
    }

    // Process quick reply from notification action
    if (pendingQuickReplyRef.current) {
      const quickReply = pendingQuickReplyRef.current;
      pendingQuickReplyRef.current = null;

      setTimeout(() => {
        console.log('[Chat] Sending quick reply:', quickReply.message);
        pendingMessageSourceRef.current = {
          entryPoint: 'quick_reply',
        };
        handleSendMessage(quickReply.message);
      }, 300);
      return;
    }

    // Process heartbeat notification (proactive check-ins from Sara)
    if (pendingHeartbeatRef.current) {
      const heartbeat = pendingHeartbeatRef.current;
      pendingHeartbeatRef.current = null;

      setTimeout(() => {
        // Add Sara's heartbeat message to the chat - user can respond naturally
        const saraMessage: Message = {
          id: `sara-heartbeat-${Date.now()}`,
          role: 'assistant',
          content: heartbeat.message,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, saraMessage]);
        console.log('[Chat] Added heartbeat message from Sara');
      }, 300);
      return;
    }

    // Process notification context (ACS discoveries, notifications)
    if (pendingNotificationRef.current) {
      const notification = pendingNotificationRef.current;
      pendingNotificationRef.current = null;

      setTimeout(() => {
        const isACS = notification.item_type === 'acs_discovery';
        setConversationContext({
          kind: 'notification',
          title: notification.title,
          summary: notification.message || (isACS ? 'Sara surfaced a discovery worth reviewing.' : 'Sara brought a notification into the conversation.'),
          sourceLabel: isACS ? 'Reviewing a discovery' : 'Reviewing a notification',
          primaryActionLabel: isACS ? 'Why it matters' : 'Discuss this',
          primaryPrompt: isACS
            ? `Give me the short version of "${notification.title}" and explain why it matters.`
            : `Help me think through "${notification.title}" and decide what to do next.`,
        });
        assistantAnalytics.track('assistant.proactive_context_opened', {
          source: 'notification',
          item_type: notification.item_type || null,
          category: notification.category || null,
          title: notification.title,
        });
        console.log('[Chat] Loaded notification context into chat:', notification.id);
      }, 300);
      return;
    }

    // Process note/report discussion
    if (pendingNoteContextRef.current) {
      const noteContext = pendingNoteContextRef.current;
      pendingNoteContextRef.current = null;

      setTimeout(() => {
        setConversationContext({
          kind: 'note',
          title: noteContext.title,
          summary: 'Sara attached this full report as context for your next reply.',
          sourceLabel: 'Reviewing a report',
          primaryActionLabel: 'Discuss this report',
          primaryPrompt: noteContext.prompt || `Help me review "${noteContext.title}" and tell me what matters.`,
          noteId: noteContext.id,
          previewText: noteContext.preview,
        });
        assistantAnalytics.track('assistant.proactive_context_opened', {
          source: 'note',
          item_id: noteContext.id,
          title: noteContext.title,
        });
        void hydrateNoteConversationContext(noteContext);
        console.log('[Chat] Loaded note context into chat:', noteContext.id);
      }, 300);
      return;
    }

    // Process inbox item discussion
    if (pendingInboxItemRef.current) {
      const inboxItem = pendingInboxItemRef.current;
      pendingInboxItemRef.current = null;

      setTimeout(() => {
        setConversationContext({
          kind: 'inbox',
          title: inboxItem.title,
          summary: 'Sara has this captured item ready as context for your next reply.',
          sourceLabel: 'Reviewing a captured item',
          primaryActionLabel: 'Review with Sara',
          primaryPrompt: `Help me review "${inboxItem.title}" and tell me what matters.`,
          inboxItemId: inboxItem.id,
        });
        assistantAnalytics.track('assistant.proactive_context_opened', {
          source: 'inbox',
          item_id: inboxItem.id,
          title: inboxItem.title,
        });
        console.log('[Chat] Loaded inbox item context into chat:', inboxItem.id);
      }, 300);
      return;
    }
  }, [isStreaming, isLoadingHistory, pendingContextTrigger]);

  const handleVoiceMessage = async (audioUri: string) => {
    if (!voiceInitialized) {
      Alert.alert('Voice Not Available', 'Microphone permission is required for voice chat.');
      return;
    }

    try {
      setIsStreaming(true);
      setStreamingMessage('Transcribing...');

      // Transcribe audio with backend Whisper endpoint.
      const transcribedText = await voiceService.transcribeAudio(audioUri);

      if (!transcribedText || transcribedText.trim().length === 0) {
        setIsStreaming(false);
        setStreamingMessage('');

        // Resume listening if in continuous mode
        if (shouldResumeListening.current) {
          console.log('[Chat] Empty transcription, resuming continuous listening');
          startContinuousListening();
        }
        return;
      }

      // Add user's transcribed message
      const userMessage: Message = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: transcribedText,
        created_at: new Date().toISOString(),
      };

      const inputMode = shouldResumeListening.current ? 'voice_hands_free' : 'voice_hold_to_talk';
      assistantAnalytics.track('assistant.message_sent', {
        input_mode: inputMode,
        entry_point: inputMode === 'voice_hands_free' ? 'hands_free' : 'hold_to_talk',
        transcript_length: transcribedText.length,
      });

      setMessages((prev) => [...prev, userMessage]);
      setStreamingMessage('Thinking...');
      streamingMessageRef.current = '';

      // Send transcribed text through regular chat (same as text messages)
      const updatedMessages = [...messagesRef.current, userMessage];
      const conversationMessages = updatedMessages.filter(m => m.id !== 'welcome');

      await chatService.sendMessage(
        {
          messages: conversationMessages,
          conversationId,
          model: selectedModel,  // Pass selected model
          ephemeral: isEphemeral,  // Pass ephemeral mode
          source: 'ios',
          onUiCommand: handleSaraUiCommand,
        },
        // onChunk
        (chunk: string) => {
          streamingMessageRef.current += chunk;
          setStreamingMessage(streamingMessageRef.current);
        },
        // onComplete
        async (newConversationId: string, episodeId?: string) => {
          const responseText = await resolveAssistantResponseText(
            streamingMessageRef.current,
            newConversationId || conversationId
          );

          // Add assistant message with episode_id for rating
          const assistantMessage: Message = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: responseText || 'I finished thinking, but no visible response text was returned.',
            created_at: new Date().toISOString(),
            episode_id: episodeId,  // Include episode_id for star rating
          };

          console.log('[Chat] 🎤 Voice response with episode_id:', episodeId);
          setMessages((prev) => [...prev, assistantMessage]);
          setStreamingMessage('');
          streamingMessageRef.current = '';
          setIsStreaming(false);

          if (newConversationId && newConversationId !== conversationId) {
            setConversationId(newConversationId);
          }

          // Speak the response using native iOS TTS (emojis will be stripped)
          setIsPlayingAudio(true);
          try {
            await voiceService.speak(responseText);
          } catch (ttsError) {
            console.error('[Chat] TTS playback failed:', ttsError);
          } finally {
            setIsPlayingAudio(false);
          }

          // Resume listening if in continuous mode
          console.log('[Chat] TTS finished. Checking resume:', {
            continuousVoiceMode,
            shouldResume: shouldResumeListening.current
          });
          if (shouldResumeListening.current) {
            console.log('[Chat] Resuming continuous listening after TTS');
            await startContinuousListening();
          }
        },
        // onError
        (error: Error) => {
          console.error('Chat error:', error);
          setIsStreaming(false);
          setStreamingMessage('');
          Alert.alert('Error', 'Failed to send message. Please try again.');

          // Resume listening if in continuous mode
          if (shouldResumeListening.current) {
            console.log('[Chat] Resuming continuous listening after error');
            startContinuousListening();
          }
        }
      );
    } catch (error) {
      console.error('Voice message error:', error);
      setIsStreaming(false);
      setStreamingMessage('');

      // Resume listening if in continuous mode
      if (shouldResumeListening.current) {
        console.log('[Chat] Resuming continuous listening after voice error');
        startContinuousListening();
      }
    }
  };

  // Start continuous listening with VAD
  const startContinuousListening = async () => {
    try {
      // Ensure voice is initialized (re-initialize in case audio mode was changed by TTS)
      const initialized = await voiceService.initialize();
      if (!initialized) {
        console.error('[Chat] Voice initialization failed - microphone permission denied');
        Alert.alert('Microphone Access', 'Please enable microphone access in Settings to use voice features.');
        return;
      }

      setIsListening(true);
      await voiceService.startContinuousRecording(async () => {
        // VAD detected silence, process the recording
        setIsListening(false);
        const audioUri = await voiceService.stopRecording();
        if (audioUri) {
          await handleVoiceMessage(audioUri);
        }
      });
    } catch (error) {
      console.error('[Chat] Failed to start continuous listening:', error);
      setIsListening(false);
    }
  };

  // Toggle continuous voice mode
  const handleToggleContinuousVoice = async () => {
    console.log('[Chat] Toggle continuous voice. Current mode:', continuousVoiceMode);
    assistantAnalytics.track('assistant.voice_hands_free_toggled', {
      enabled: !continuousVoiceMode,
      screen: isEmbedded ? 'sara_embedded' : 'chat',
    });

    if (continuousVoiceMode) {
      // Turn off continuous mode
      console.log('[Chat] Turning OFF continuous voice mode');
      shouldResumeListening.current = false;
      setContinuousVoiceMode(false);
      setIsListening(false);
      try {
        await voiceService.stopRecording();
        console.log('[Chat] Continuous voice mode stopped');
      } catch (error) {
        console.error('[Chat] Error stopping recording:', error);
      }
    } else {
      // Turn on continuous mode and start listening
      console.log('[Chat] Turning ON continuous voice mode');
      setContinuousVoiceMode(true);
      shouldResumeListening.current = true;
      await startContinuousListening();
    }
  };

  // Cleanup continuous mode on unmount
  useEffect(() => {
    return () => {
      if (continuousVoiceMode) {
        shouldResumeListening.current = false;
        voiceService.stopRecording();
      }
    };
  }, [continuousVoiceMode]);

  const handleClearChat = () => {
    Alert.alert(
      'Start New Chat',
      'Are you sure you want to start a new conversation?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'New Chat',
          style: 'destructive',
          onPress: async () => {
            setMessages([]);
            setConversationId(null);
            setStreamingMessage('');
            setConversationContext(null);
            setSuggestedActions([]);
            setPendingCards([]);
            pendingCardsRef.current = [];
            setActiveToolStatus(null);

            // Clear active conversation on backend
            try {
              await apiClient.post('/api/conversations/active', { conversation_id: null });
              console.log('[Chat] Cleared active conversation - starting new chat');
            } catch (error) {
              console.error('[Chat] Error clearing active conversation:', error);
            }
          },
        },
      ]
    );
  };

  const renderMessage = ({ item }: { item: Message }) => (
    <MessageBubble message={item} />
  );

  const renderStreamingMessage = () => {
    if (!isStreaming && !streamingMessage) return null;

    const tempMessage: Message = {
      id: 'streaming',
      role: 'assistant',
      content: streamingMessage || '',
      created_at: new Date().toISOString(),
    };

    return (
      <View>
        {streamingMessage ? (
          <MessageBubble message={tempMessage} />
        ) : activeToolStatus ? (
          <ToolStatusIndicator toolName={activeToolStatus.tool} status={activeToolStatus.status} />
        ) : (
          <StreamingIndicator />
        )}
      </View>
    );
  };

  // Handle card actions (navigate or send message)
  const handleCardAction = useCallback((action: any) => {
    if (action.action === 'navigate' && action.target && navigation) {
      navigation.navigate(action.target, action.params || {});
    } else if (action.message) {
      pendingMessageSourceRef.current = {
        entryPoint: 'content_card',
        label: action.label || undefined,
        target: action.target || undefined,
      };
      handleSendMessage(action.message);
    }
  }, [navigation]);

  // Handle suggested action tap
  const handleSuggestedAction = useCallback((action: SuggestedAction) => {
    assistantAnalytics.track('assistant.suggested_action_tapped', {
      label: action.label,
      action: action.action || (action.message ? 'message' : 'unknown'),
      target: action.target || null,
      has_message: Boolean(action.message),
    });
    if (action.action === 'navigate' && action.target && navigation) {
      navigation.navigate(action.target);
    } else if (action.message) {
      pendingMessageSourceRef.current = {
        entryPoint: 'suggested_action',
        label: action.label,
        target: action.target || undefined,
      };
      handleSendMessage(action.message);
    }
    setSuggestedActions([]);
  }, [navigation]);

  const handleConversationContextAction = useCallback(() => {
    if (!conversationContext) return;
    assistantAnalytics.track('assistant.proactive_context_prompt_used', {
      source: conversationContext.kind,
      title: conversationContext.title,
      label: conversationContext.primaryActionLabel,
    });
    pendingMessageSourceRef.current = {
      entryPoint: 'proactive_context',
      label: conversationContext.primaryActionLabel,
      contextKind: conversationContext.kind,
    };
    handleSendMessage(
      conversationContext.primaryPrompt,
      undefined,
      undefined,
      conversationContext.inboxItemId,
      conversationContext.noteId,
    );
  }, [conversationContext, handleSendMessage]);

  // Get display name for selected model
  const selectedModelDetails = availableModels?.models?.find(m => m.id === selectedModel);
  const selectedModelName = selectedModelDetails?.name || selectedModel;
  const selectedProviderLabel = PROVIDER_LABELS[selectedModelDetails?.provider || 'local'] || 'Local';

  // Group models by provider
  const groupedModels = availableModels?.models?.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = [];
    acc[model.provider].push(model);
    return acc;
  }, {} as Record<string, ChatModel[]>) || {};

  const handleExitChat = useCallback(() => {
    if (!navigation) return;

    if (typeof navigation.canGoBack === 'function' && navigation.canGoBack()) {
      navigation.goBack();
      return;
    }

    navigation.navigate?.('MainTabs', { screen: 'Sara' });
  }, [navigation]);

  return (
    <SafeAreaView style={[styles.container, isEphemeral && styles.ephemeralContainer]} edges={isEmbedded ? [] : ['top', 'bottom']}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 0}
      >
        {/* Conversation header */}
        <View style={[styles.header, isEphemeral && styles.ephemeralHeader]}>
          {!isEmbedded ? (
            <TouchableOpacity
              style={styles.backButton}
              onPress={handleExitChat}
              activeOpacity={0.8}
            >
              <Ionicons name="chevron-back" size={18} color={colors.textSecondary} />
              <Text style={styles.backButtonText}>Back</Text>
            </TouchableOpacity>
          ) : null}
          <View style={styles.headerCopy}>
            <Text style={styles.headerEyebrow}>
              {isEmbedded ? 'Sara conversation' : 'Sara'}
            </Text>
            <Text style={styles.headerTitle}>
              {isEphemeral ? 'Private mode is on for this conversation.' : 'Ask, speak, or pick up where you left off.'}
            </Text>
          </View>
          <TouchableOpacity
            style={[styles.controlsButton, isEphemeral && styles.controlsButtonActive]}
            onPress={() => setShowConversationControls(true)}
          >
            <Ionicons
              name={isEphemeral ? 'shield-checkmark-outline' : 'options-outline'}
              size={18}
              color={isEphemeral ? colors.secondary : colors.textMuted}
            />
            <Text style={[styles.controlsButtonText, isEphemeral && styles.controlsButtonTextActive]}>
              {isEphemeral ? 'Private' : 'Controls'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Conversation Controls Modal */}
        <Modal
          visible={showConversationControls}
          transparent
          animationType="fade"
          onRequestClose={() => setShowConversationControls(false)}
        >
          <Pressable
            style={styles.modalOverlay}
            onPress={() => setShowConversationControls(false)}
          >
            <Pressable style={styles.modalContent} onPress={(event) => event.stopPropagation()}>
              <ScrollView showsVerticalScrollIndicator={false}>
                <Text style={styles.modalEyebrow}>Conversation</Text>
                <Text style={styles.modalTitle}>Conversation controls</Text>
                <Text style={styles.modalDescription}>
                  Keep this chat private when needed, or switch the model Sara uses for this conversation.
                </Text>

                <View style={styles.controlCard}>
                  <View style={styles.controlCopy}>
                    <Text style={styles.controlTitle}>Private mode</Text>
                    <Text style={styles.controlDescription}>
                      Useful for one-off chats you do not want Sara to retain.
                    </Text>
                  </View>
                  <Switch
                    value={isEphemeral}
                    onValueChange={setIsEphemeral}
                    trackColor={{ false: colors.surfaceLight, true: 'rgba(139, 92, 246, 0.45)' }}
                    thumbColor={isEphemeral ? colors.secondary : colors.text}
                  />
                </View>

                <View style={styles.selectedModelCard}>
                  <Text style={styles.selectedModelLabel}>Current model</Text>
                  <Text style={styles.selectedModelName}>{selectedModelName}</Text>
                  <Text style={styles.selectedModelProvider}>{selectedProviderLabel}</Text>
                </View>

                {Object.entries(groupedModels).map(([provider, models]) => (
                  <View key={provider} style={styles.providerGroup}>
                    <Text style={styles.providerLabel}>
                      {PROVIDER_LABELS[provider] || 'Local'}
                    </Text>
                    {models.map((model) => (
                      <TouchableOpacity
                        key={model.id}
                        style={[
                          styles.modelOption,
                          model.id === selectedModel && styles.modelOptionSelected,
                        ]}
                        onPress={() => {
                          setSelectedModel(model.id);
                          setShowConversationControls(false);
                        }}
                      >
                        <View style={styles.modelOptionCopy}>
                          <Text
                            style={[
                              styles.modelOptionText,
                              model.id === selectedModel && styles.modelOptionTextSelected,
                            ]}
                          >
                            {model.name}
                          </Text>
                          <Text style={styles.modelOptionMeta}>{PROVIDER_LABELS[model.provider] || 'Local'}</Text>
                        </View>
                        {model.id === selectedModel && (
                          <Ionicons name="checkmark-circle" size={18} color={colors.primary} />
                        )}
                      </TouchableOpacity>
                    ))}
                  </View>
                ))}
              </ScrollView>
            </Pressable>
          </Pressable>
        </Modal>

        {/* Sara Status Bar - hidden in embedded mode (shown in IntelligentBrief) */}
        {!isEmbedded && <SaraStatusBar />}

        {/* Messages List */}
        <FlatList
          ref={flatListRef}
          style={styles.messageListContainer}
          data={messages}
          renderItem={renderMessage}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.messageList}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
          ListFooterComponent={renderStreamingMessage}
          onContentSizeChange={() => {
            flatListRef.current?.scrollToEnd({ animated: false });
          }}
        />

        {/* New Chat button - show only if there are messages */}
        {messages.length > 0 && (
          <TouchableOpacity
            style={styles.clearButton}
            onPress={handleClearChat}
          >
            <Text style={styles.clearButtonText}>+ New Chat</Text>
          </TouchableOpacity>
        )}

        {conversationContext && (
          <View style={styles.contextBanner}>
            <View style={styles.contextBannerHeader}>
              <View style={styles.contextIconWrap}>
                <Ionicons
                  name={
                    conversationContext.kind === 'inbox' || conversationContext.kind === 'note'
                      ? 'document-text-outline'
                      : 'notifications-outline'
                  }
                  size={16}
                  color={colors.accent}
                />
              </View>
              <View style={styles.contextCopy}>
                <Text style={styles.contextEyebrow}>{conversationContext.sourceLabel}</Text>
                <Text style={styles.contextTitle} numberOfLines={contextExpanded ? undefined : 2}>{conversationContext.title}</Text>
                <TouchableOpacity activeOpacity={0.7} onPress={() => setContextExpanded((v) => !v)}>
                  <Text style={styles.contextSummary} numberOfLines={contextExpanded ? undefined : 2}>
                    {conversationContext.summary}
                  </Text>
                  {(conversationContext.summary?.length || 0) > 90 ? (
                    <Text style={styles.contextMore}>{contextExpanded ? 'Show less' : 'Show more'}</Text>
                  ) : null}
                </TouchableOpacity>
              </View>
              <TouchableOpacity
                style={styles.contextDismiss}
                onPress={() => setConversationContext(null)}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Ionicons name="close" size={16} color={colors.textMuted} />
              </TouchableOpacity>
            </View>
            {conversationContext.previewText || conversationContext.kind === 'note' ? (
              <View style={styles.contextPreviewCard}>
                <Text style={styles.contextPreviewLabel}>
                  {conversationContext.kind === 'note' ? 'Report Preview' : 'Preview'}
                </Text>
                {conversationContext.previewText ? (
                  <Text style={styles.contextPreviewText} numberOfLines={8}>
                    {conversationContext.previewText}
                  </Text>
                ) : (
                  <Text style={styles.contextPreviewText}>
                    Loading the report content...
                  </Text>
                )}
                {conversationContext.kind === 'note' ? (
                  <TouchableOpacity
                    style={styles.contextReaderButton}
                    onPress={openFullNote}
                    activeOpacity={0.85}
                  >
                    <Ionicons name="document-outline" size={14} color={colors.primary} />
                    <Text style={styles.contextReaderButtonText}>Open Full Report</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            ) : null}
            <View style={styles.contextActions}>
              <TouchableOpacity
                style={styles.contextPrimaryButton}
                onPress={handleConversationContextAction}
                activeOpacity={0.85}
              >
                <Text style={styles.contextPrimaryButtonText}>{conversationContext.primaryActionLabel}</Text>
              </TouchableOpacity>
              <Text style={styles.contextHint}>Or just type naturally below.</Text>
            </View>
          </View>
        )}

        {/* Suggested Actions */}
        {suggestedActions.length > 0 && !isStreaming && (
          <SuggestedActions actions={suggestedActions} onAction={handleSuggestedAction} />
        )}

        {/* Inbox chip (Phase 12K.4) — pull pending items into the chat */}
        {inboxCount > 0 && !isStreaming && (
          <TouchableOpacity
            onPress={() => handleSendMessage(
              "What's waiting for me? Show me the pending notifications and Needs-You items so I can address them.")}
            style={{
              alignSelf: 'flex-start', marginHorizontal: 12, marginBottom: 6,
              flexDirection: 'row', alignItems: 'center',
              paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
              backgroundColor: 'rgba(45,212,191,0.12)', borderWidth: 1, borderColor: 'rgba(45,212,191,0.3)',
            }}
            accessibilityLabel={`${inboxCount} items waiting — address in chat`}
          >
            <Text style={{ color: '#5eead4', fontSize: 12, fontWeight: '600' }}>
              📥 {inboxCount} waiting — address here
            </Text>
          </TouchableOpacity>
        )}

        {/* Input */}
        <ChatInput
          onSend={handleSendMessage}
          onVoiceMessage={handleVoiceMessage}
          onHoldToTalkStart={() => {
            assistantAnalytics.track('assistant.voice_hold_to_talk_started', {
              screen: isEmbedded ? 'sara_embedded' : 'chat',
            });
          }}
          disabled={isStreaming || isPlayingAudio}
          placeholder={conversationContext?.kind === 'note'
            ? 'Ask about this report or tell Sara what you want to understand...'
            : conversationContext
              ? 'Reply about this item or ask what to do next...'
              : 'Ask Sara anything...'}
          voiceEnabled={voiceInitialized}
          continuousVoiceMode={continuousVoiceMode}
          onToggleContinuousVoice={handleToggleContinuousVoice}
          isListeningContinuous={isListening}
        />
      </KeyboardAvoidingView>

      <Modal
        visible={noteReaderVisible}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setNoteReaderVisible(false)}
      >
        <SafeAreaView style={styles.noteReaderModal} edges={['top', 'bottom']}>
          <View style={styles.noteReaderHeader}>
            <TouchableOpacity onPress={() => setNoteReaderVisible(false)}>
              <Text style={styles.noteReaderControl}>Close</Text>
            </TouchableOpacity>
            <Text style={styles.noteReaderTitle} numberOfLines={2}>
              {noteReaderTitle || 'Report'}
            </Text>
            <View style={styles.noteReaderControlSpacer} />
          </View>

          {noteReaderLoading && !noteReaderContent ? (
            <View style={styles.noteReaderLoading}>
              <ActivityIndicator size="large" color={colors.primary} />
            </View>
          ) : (
            <ScrollView
              style={styles.noteReaderScroll}
              contentContainerStyle={styles.noteReaderScrollContent}
              showsVerticalScrollIndicator
            >
              {splitNoteReaderBlocks(noteReaderContent).map((block, index) => (
                <Text key={`note-reader-${index}`} selectable style={styles.noteReaderParagraph}>
                  {block}
                </Text>
              ))}
            </ScrollView>
          )}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const ChatScreen = forwardRef(ChatScreenInner);
export default ChatScreen;

// --- Sara Status Bar Component ---
const STATUS_LABELS: Record<string, string> = {
  curious: 'looking into something',
  calm: 'ready',
  alert: 'watching closely',
  concerned: 'flagging something important',
  happy: 'in a good groove',
  focused: 'working through something',
  neutral: 'available',
  reflective: 'connecting context',
  attentive: 'paying attention',
};

function SaraStatusBar() {
  const [status, setStatus] = useState<any>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const data = await apiClient.get('/api/sara/status');
        setStatus(data);
      } catch {
        // Graceful degradation - renders nothing
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  if (!status) return null;

  const statusLabel = STATUS_LABELS[status.emotional_state] || 'available';
  const thought = status.latest_thought
    ? (status.latest_thought.length > 60 ? status.latest_thought.slice(0, 60) + '...' : status.latest_thought)
    : null;

  return (
    <TouchableOpacity
      onPress={() => setExpanded(!expanded)}
      style={statusBarStyles.container}
      activeOpacity={0.7}
    >
      <View style={statusBarStyles.row}>
        <View style={statusBarStyles.statusBadge}>
          <Ionicons name="sparkles-outline" size={13} color={colors.accent} />
        </View>
        <Text style={statusBarStyles.state}>Sara is {statusLabel}</Text>
        {thought && <Text style={statusBarStyles.thought} numberOfLines={1}>{thought}</Text>}
        <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={14} color={colors.textMuted} />
      </View>
      {expanded && (
        <View style={statusBarStyles.details}>
          {status.watching_for && (
            <Text style={statusBarStyles.detail}>Watching for: {status.watching_for}</Text>
          )}
          {status.last_action && (
            <Text style={statusBarStyles.detail}>Recently: {status.last_action.slice(0, 80)}</Text>
          )}
          {status.david_energy != null && (
            <Text style={statusBarStyles.detail}>Energy estimate: {(status.david_energy * 100).toFixed(0)}%</Text>
          )}
          {status.pkg_facts_count > 0 && (
            <Text style={statusBarStyles.detail}>Loaded context: {status.pkg_facts_count} memory item{status.pkg_facts_count === 1 ? '' : 's'}</Text>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

const statusBarStyles = StyleSheet.create({
  container: {
    backgroundColor: colors.assistant.panel,
    borderBottomWidth: 1,
    borderBottomColor: colors.assistant.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  statusBadge: {
    width: 22,
    height: 22,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.passiveSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  state: { color: colors.textSecondary, fontSize: fontSizes.xs, fontWeight: '600' },
  thought: { flex: 1, color: colors.textMuted, fontSize: 11, fontStyle: 'italic' },
  details: { marginTop: spacing.xs, gap: 3 },
  detail: { color: colors.textMuted, fontSize: 11 },
});

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  ephemeralContainer: {
    backgroundColor: colors.assistant.panelMuted,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.assistant.border,
    backgroundColor: colors.assistant.panel,
  },
  backButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    paddingHorizontal: spacing.xs,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  backButtonText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  ephemeralHeader: {
    backgroundColor: 'rgba(139, 92, 246, 0.12)',
  },
  headerCopy: {
    flex: 1,
    paddingRight: spacing.md,
  },
  headerEyebrow: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  headerTitle: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  controlsButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs + 2,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    backgroundColor: colors.assistant.panelMuted,
  },
  controlsButtonActive: {
    borderColor: colors.secondary,
    backgroundColor: 'rgba(139, 92, 246, 0.16)',
  },
  controlsButtonText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  controlsButtonTextActive: {
    color: colors.secondary,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    padding: spacing.lg,
    width: '88%',
    maxWidth: 360,
    maxHeight: '70%',
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  modalEyebrow: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  modalTitle: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  modalDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginBottom: spacing.lg,
  },
  controlCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panelMuted,
    marginBottom: spacing.md,
  },
  controlCopy: {
    flex: 1,
  },
  controlTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  controlDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  selectedModelCard: {
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    marginBottom: spacing.lg,
  },
  selectedModelLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: spacing.xs,
  },
  selectedModelName: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  selectedModelProvider: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
  providerGroup: {
    marginBottom: spacing.md,
  },
  providerLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.xs,
  },
  modelOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.md,
    gap: spacing.sm,
  },
  modelOptionSelected: {
    backgroundColor: colors.assistant.passiveSoft,
  },
  modelOptionCopy: {
    flex: 1,
  },
  modelOptionText: {
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  modelOptionTextSelected: {
    color: colors.primary,
    fontWeight: '500',
  },
  modelOptionMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  messageListContainer: {
    flex: 1,
  },
  messageList: {
    paddingVertical: spacing.md,
    flexGrow: 1,
  },
  clearButton: {
    alignSelf: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  clearButtonText: {
    color: colors.textSecondary,
    fontSize: 14,
    fontWeight: '600',
  },
  contextBanner: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panel,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    ...shadows.sm,
  },
  contextBannerHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  contextIconWrap: {
    width: 28,
    height: 28,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.passiveSoft,
    justifyContent: 'center',
    alignItems: 'center',
  },
  contextCopy: {
    flex: 1,
  },
  contextEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: 2,
  },
  contextTitle: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '700',
    marginBottom: 2,
  },
  contextSummary: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 17,
  },
  contextMore: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    marginTop: 2,
  },
  contextPreviewCard: {
    marginTop: spacing.sm,
    marginLeft: 36,
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panelMuted,
    borderWidth: 1,
    borderColor: colors.assistant.border,
  },
  contextPreviewLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: spacing.xs,
  },
  contextPreviewText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    lineHeight: 21,
  },
  contextReaderButton: {
    marginTop: spacing.md,
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.actionSoft,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
  },
  contextReaderButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  contextDismiss: {
    paddingTop: 2,
  },
  contextActions: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  contextPrimaryButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.primary,
  },
  noteReaderModal: {
    flex: 1,
    backgroundColor: colors.background,
  },
  noteReaderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.assistant.border,
    backgroundColor: colors.assistant.panel,
  },
  noteReaderControl: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  noteReaderControlSpacer: {
    width: 44,
  },
  noteReaderTitle: {
    flex: 1,
    marginHorizontal: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
    textAlign: 'center',
  },
  noteReaderLoading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  noteReaderScroll: {
    flex: 1,
  },
  noteReaderScrollContent: {
    padding: spacing.lg,
    gap: spacing.md,
  },
  noteReaderParagraph: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
    marginBottom: spacing.md,
  },
  contextPrimaryButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  contextHint: {
    flex: 1,
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    textAlign: 'right',
  },
});
