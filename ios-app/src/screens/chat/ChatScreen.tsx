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
  AppState,
  AppStateStatus,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { MainTabScreenProps, HealthAlertContext, NudgeContext, QuickReplyContext, HeartbeatContext, NotificationContext } from '../../types/navigation';
import { Message } from '../../types/api';
import { ContentCard as ContentCardType, SuggestedAction, ToolStatus } from '../../types/cards';
import { chatService } from '../../services/chat';
import { voiceService } from '../../services/voice';
import { ImageAttachment } from '../../services/imagePicker';
import MessageBubble from '../../components/chat/MessageBubble';
import StreamingIndicator from '../../components/chat/StreamingIndicator';
import ChatInput from '../../components/chat/ChatInput';
import ContentCard from '../../components/cards/ContentCard';
import SuggestedActions from '../../components/chat/SuggestedActions';
import ToolStatusIndicator from '../../components/chat/ToolStatusIndicator';
import { colors, spacing } from '../../styles/theme';
import { apiClient, ChatModel, ChatModelsResponse } from '../../services/api';

type Props = MainTabScreenProps<'Sara'> | MainTabScreenProps<'Chat'> | {
  isEmbedded?: boolean;
  onBriefCollapse?: () => void;
  navigation?: any;
  route?: any;
};

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
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:120b');
  const [isEphemeral, setIsEphemeral] = useState(false);
  const [availableModels, setAvailableModels] = useState<ChatModelsResponse | null>(null);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const flatListRef = useRef<FlatList>(null);
  const messagesRef = useRef<Message[]>([]);
  const streamingMessageRef = useRef('');
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
  const pendingNotificationRef = useRef<NotificationContext | null>(null);
  const handledNotificationRef = useRef<string | null>(null);

  // Keep latest messages in a ref so async voice/text handlers don't use stale closures.
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

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
          setMessages(loadedMessages);
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

        let savedConversationId: string | null = null;

        // First, check for a cross-device active session (e.g. started on desktop)
        try {
          const sessionData = await chatService.getActiveSession();
          if (sessionData.active && sessionData.session?.conversation_id) {
            savedConversationId = sessionData.session.conversation_id;
            console.log('[Chat] Resuming cross-device session:', savedConversationId, 'from', sessionData.session.last_device);
          }
        } catch {
          // Non-critical — fall through to conversations/active
        }

        // Fall back to the per-device active conversation
        if (!savedConversationId) {
          const activeResponse = await apiClient.get('/api/conversations/active');
          savedConversationId = (activeResponse as any)?.conversation_id || null;
        }

        if (!savedConversationId) {
          console.log('[Chat] No active conversation found');
          return;
        }

        console.log('[Chat] Loading conversation history for:', savedConversationId);

        // Load conversation messages
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

          setMessages(loadedMessages);
          setConversationId(savedConversationId);
          console.log(`[Chat] Loaded ${loadedMessages.length} messages from conversation ${savedConversationId}`);
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
        if (models.default && selectedModel === 'gpt-oss:120b') {
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

          setMessages(loadedMessages);
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

  const handleSendMessage = async (messageText: string, images?: ImageAttachment[], inboxItemId?: string) => {
    // Clear previous suggestions when sending new message
    setSuggestedActions([]);
    setPendingCards([]);
    setActiveToolStatus(null);

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
        model: selectedModel,  // Pass selected model
        ephemeral: isEphemeral,  // Pass ephemeral mode
        inboxItemId,  // Pass inbox item for discussion context
        source: isEmbedded ? 'ios' : 'ios',
        onContentCard: (card: any) => {
          setPendingCards(prev => [...prev, card]);
        },
        onToolStatus: (status: ToolStatus) => {
          setActiveToolStatus(status.status === 'executing' ? status : null);
        },
        onSuggestedActions: (actions: SuggestedAction[]) => {
          setSuggestedActions(actions);
        },
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
          cards: [...pendingCards],  // Attach accumulated cards
        };

        console.log('[Chat] 📝 Creating assistant message with episode_id:', episodeId, 'cards:', pendingCards.length);
        setMessages((prev) => [...prev, assistantMessage]);
        setStreamingMessage('');
        streamingMessageRef.current = '';
        setIsStreaming(false);
        setPendingCards([]);
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
        const emoji = isACS ? '🔬' : '💬';
        const label = isACS ? 'Discovery' : 'Notification';

        const saraMessage: Message = {
          id: `sara-notification-${Date.now()}`,
          role: 'assistant',
          content: `${emoji} **${label}: ${notification.title}**\n\n${notification.message}\n\nWould you like to discuss this further or take any action?`,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, saraMessage]);
        console.log('[Chat] Added notification message from Sara:', notification.id);
      }, 300);
      return;
    }

    // Process inbox item discussion
    if (pendingInboxItemRef.current) {
      const inboxItem = pendingInboxItemRef.current;
      pendingInboxItemRef.current = null;

      setTimeout(() => {
        const userMessage = `Let's talk about this: ${inboxItem.title}`;
        console.log('[Chat] Sending inbox item discussion:', inboxItem.id);
        handleSendMessage(userMessage, undefined, inboxItem.id);
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
      handleSendMessage(action.message);
    }
  }, [navigation]);

  // Handle suggested action tap
  const handleSuggestedAction = useCallback((action: SuggestedAction) => {
    if (action.action === 'navigate' && action.target && navigation) {
      navigation.navigate(action.target);
    } else if (action.message) {
      handleSendMessage(action.message);
    }
    setSuggestedActions([]);
  }, [navigation]);

  // Get display name for selected model
  const selectedModelName = availableModels?.models?.find(m => m.id === selectedModel)?.name || selectedModel;

  // Group models by provider
  const groupedModels = availableModels?.models?.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = [];
    acc[model.provider].push(model);
    return acc;
  }, {} as Record<string, ChatModel[]>) || {};

  return (
    <SafeAreaView style={[styles.container, isEphemeral && styles.ephemeralContainer]} edges={isEmbedded ? [] : ['bottom']}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 0}
      >
        {/* Header with Model Selector and Ghost Toggle */}
        <View style={[styles.header, isEphemeral && styles.ephemeralHeader]}>
          {/* Model Selector */}
          <TouchableOpacity
            style={styles.modelSelector}
            onPress={() => setShowModelPicker(true)}
          >
            <Text style={styles.modelSelectorText} numberOfLines={1}>
              {selectedModelName}
            </Text>
            <Ionicons name="chevron-down" size={16} color={colors.textMuted} />
          </TouchableOpacity>

          {/* Ghost/Ephemeral Toggle */}
          <TouchableOpacity
            style={[styles.ghostButton, isEphemeral && styles.ghostButtonActive]}
            onPress={() => setIsEphemeral(!isEphemeral)}
          >
            <Ionicons
              name="eye-off-outline"
              size={20}
              color={isEphemeral ? '#a855f7' : colors.textMuted}
            />
          </TouchableOpacity>
        </View>

        {/* Model Picker Modal */}
        <Modal
          visible={showModelPicker}
          transparent
          animationType="fade"
          onRequestClose={() => setShowModelPicker(false)}
        >
          <Pressable
            style={styles.modalOverlay}
            onPress={() => setShowModelPicker(false)}
          >
            <View style={styles.modalContent}>
              <Text style={styles.modalTitle}>Select Model</Text>
              {Object.entries(groupedModels).map(([provider, models]) => (
                <View key={provider}>
                  <Text style={styles.providerLabel}>
                    {provider === 'anthropic'
                      ? 'Claude'
                      : provider === 'google'
                      ? 'Gemini'
                      : provider === 'openai'
                      ? 'OpenAI'
                      : provider === 'codex'
                      ? 'ChatGPT Codex'
                      : 'Local'}
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
                        setShowModelPicker(false);
                      }}
                    >
                      <Text
                        style={[
                          styles.modelOptionText,
                          model.id === selectedModel && styles.modelOptionTextSelected,
                        ]}
                      >
                        {model.name}
                      </Text>
                      {model.id === selectedModel && (
                        <Ionicons name="checkmark" size={18} color={colors.primary} />
                      )}
                    </TouchableOpacity>
                  ))}
                </View>
              ))}
            </View>
          </Pressable>
        </Modal>

        {/* Sara Status Bar - hidden in embedded mode (shown in IntelligentBrief) */}
        {!isEmbedded && <SaraStatusBar />}

        {/* Messages List */}
        <FlatList
          ref={flatListRef}
          data={messages}
          renderItem={renderMessage}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.messageList}
          ListFooterComponent={renderStreamingMessage}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>
                Start a conversation with Sara
              </Text>
            </View>
          }
          onContentSizeChange={() => {
            flatListRef.current?.scrollToEnd({ animated: true });
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

        {/* Suggested Actions */}
        {suggestedActions.length > 0 && !isStreaming && (
          <SuggestedActions actions={suggestedActions} onAction={handleSuggestedAction} />
        )}

        {/* Input */}
        <ChatInput
          onSend={handleSendMessage}
          onVoiceMessage={handleVoiceMessage}
          disabled={isStreaming || isPlayingAudio}
          voiceEnabled={voiceInitialized}
          continuousVoiceMode={continuousVoiceMode}
          onToggleContinuousVoice={handleToggleContinuousVoice}
          isListeningContinuous={isListening}
        />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const ChatScreen = forwardRef(ChatScreenInner);
export default ChatScreen;

// --- Sara Status Bar Component ---
const EMOTION_EMOJI: Record<string, string> = {
  curious: '🤔', calm: '😌', alert: '⚡', concerned: '😟',
  happy: '😊', focused: '🎯', neutral: '😐', reflective: '🪞', attentive: '👀',
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

  const emoji = EMOTION_EMOJI[status.emotional_state] || '🤖';
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
        <Text style={statusBarStyles.emoji}>{emoji}</Text>
        <Text style={statusBarStyles.state}>Sara is {status.emotional_state}</Text>
        {thought && <Text style={statusBarStyles.thought} numberOfLines={1}>{thought}</Text>}
        <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={14} color="rgba(255,255,255,0.3)" />
      </View>
      {expanded && (
        <View style={statusBarStyles.details}>
          {status.watching_for && (
            <Text style={statusBarStyles.detail}>👀 {status.watching_for}</Text>
          )}
          {status.last_action && (
            <Text style={statusBarStyles.detail}>⚡ Last: {status.last_action.slice(0, 80)}</Text>
          )}
          {status.david_energy != null && (
            <Text style={statusBarStyles.detail}>🔋 Your energy: {(status.david_energy * 100).toFixed(0)}%</Text>
          )}
          {status.pkg_facts_count > 0 && (
            <Text style={statusBarStyles.detail}>🧠 {status.pkg_facts_count} facts about you</Text>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

const statusBarStyles = StyleSheet.create({
  container: {
    backgroundColor: 'rgba(255, 255, 255, 0.03)',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.06)',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  emoji: { fontSize: 14 },
  state: { color: 'rgba(255,255,255,0.5)', fontSize: 12 },
  thought: { flex: 1, color: 'rgba(255,255,255,0.3)', fontSize: 11, fontStyle: 'italic' },
  details: { marginTop: 6, gap: 3 },
  detail: { color: 'rgba(255,255,255,0.4)', fontSize: 11 },
});

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  ephemeralContainer: {
    backgroundColor: '#1a0a2e',  // Subtle purple tint
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  ephemeralHeader: {
    backgroundColor: 'rgba(168, 85, 247, 0.1)',
  },
  modelSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.card,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: 8,
    gap: 4,
    maxWidth: 150,
  },
  modelSelectorText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '500',
  },
  ghostButton: {
    padding: spacing.xs,
    borderRadius: 8,
  },
  ghostButtonActive: {
    backgroundColor: 'rgba(168, 85, 247, 0.2)',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: colors.card,
    borderRadius: 16,
    padding: spacing.lg,
    width: '80%',
    maxWidth: 300,
    maxHeight: '70%',
  },
  modalTitle: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '600',
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  providerLabel: {
    color: colors.textMuted,
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  modelOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: 8,
  },
  modelOptionSelected: {
    backgroundColor: 'rgba(20, 184, 166, 0.1)',
  },
  modelOptionText: {
    color: colors.text,
    fontSize: 15,
  },
  modelOptionTextSelected: {
    color: colors.primary,
    fontWeight: '500',
  },
  messageList: {
    paddingVertical: spacing.md,
    flexGrow: 1,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: 16,
    textAlign: 'center',
  },
  clearButton: {
    alignSelf: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.sm,
  },
  clearButtonText: {
    color: colors.error,
    fontSize: 14,
    fontWeight: '500',
  },
});
