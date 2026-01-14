import React, { useState, useRef, useEffect, useCallback } from 'react';
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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Ionicons } from '@expo/vector-icons';
import { MainTabScreenProps, HealthAlertContext, NudgeContext, QuickReplyContext } from '../../types/navigation';
import { Message } from '../../types/api';
import { chatService } from '../../services/chat';
import { voiceService } from '../../services/voice';
import { ImageAttachment } from '../../services/imagePicker';
import MessageBubble from '../../components/chat/MessageBubble';
import StreamingIndicator from '../../components/chat/StreamingIndicator';
import ChatInput from '../../components/chat/ChatInput';
import { colors, spacing } from '../../styles/theme';
import { apiClient, ChatModel, ChatModelsResponse } from '../../services/api';

type Props = MainTabScreenProps<'Chat'> | { isEmbedded?: boolean };

export default function ChatScreen(props: Props) {
  // Handle both standalone and embedded modes
  const isEmbedded = 'isEmbedded' in props && props.isEmbedded;
  const navigation = 'navigation' in props ? props.navigation : undefined;
  const route = 'route' in props ? props.route : undefined;
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
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
  const streamingMessageRef = useRef('');
  const isRecordingRef = useRef(false);
  const shouldResumeListening = useRef(false);
  const hasLoadedHistory = useRef(false);
  const handledHealthAlertRef = useRef<string | null>(null);
  const handledNudgeRef = useRef<string | null>(null);
  const handledQuickReplyRef = useRef<string | null>(null);

  // Track pending contexts to send after component is ready
  const pendingHealthAlertRef = useRef<HealthAlertContext | null>(null);
  const pendingNudgeRef = useRef<NudgeContext | null>(null);
  const pendingQuickReplyRef = useRef<QuickReplyContext | null>(null);

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

    // Clear the params
    navigation.setParams({ quickReply: undefined });
  }, [route?.params?.quickReply, navigation]);

  // Load conversation history on mount
  useEffect(() => {
    const loadConversationHistory = async () => {
      if (hasLoadedHistory.current) return;
      hasLoadedHistory.current = true;

      try {
        setIsLoadingHistory(true);

        // Get active conversation from backend
        const activeResponse = await apiClient.get('/api/conversations/active');
        const savedConversationId = activeResponse.data?.conversation_id;

        if (!savedConversationId) {
          console.log('[Chat] No active conversation found');
          return;
        }

        console.log('[Chat] Loading conversation history for:', savedConversationId);

        // Load conversation messages
        const messagesResponse = await apiClient.get(
          `/api/conversations/${savedConversationId}/messages?limit=100`
        );

        const messagesData = messagesResponse.data;

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

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  }, [messages, streamingMessage]);

  const handleSendMessage = async (messageText: string, images?: ImageAttachment[]) => {
    // Add user message immediately
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: messageText,
      created_at: new Date().toISOString(),
    };

    const updatedMessages = [...messages, userMessage];
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
      },
      // onChunk - called for each piece of streaming text
      (chunk: string) => {
        streamingMessageRef.current += chunk;
        setStreamingMessage(streamingMessageRef.current);
      },
      // onComplete - called when streaming finishes
      (newConversationId: string, episodeId?: string) => {
        // Add the complete assistant message with episode_id for rating
        const assistantMessage: Message = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: streamingMessageRef.current,
          created_at: new Date().toISOString(),
          episode_id: episodeId,  // Include episode_id for star rating
        };

        console.log('[Chat] 📝 Creating assistant message with episode_id:', episodeId);
        setMessages((prev) => [...prev, assistantMessage]);
        setStreamingMessage('');
        streamingMessageRef.current = '';
        setIsStreaming(false);

        // Always update conversation_id if backend provides one
        console.log('[Chat] 📨 Received conversation_id from backend:', newConversationId);
        console.log('[Chat] 📊 Current conversation_id:', conversationId);
        if (newConversationId) {
          if (newConversationId !== conversationId) {
            console.log('[Chat] 🔄 Updating conversation_id from', conversationId, 'to', newConversationId);
            setConversationId(newConversationId);
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
        // Add Sara's nudge as her message first, then user responds
        const saraMessage: Message = {
          id: `sara-nudge-${Date.now()}`,
          role: 'assistant',
          content: nudge.message,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, saraMessage]);

        // Build contextual response based on nudge type
        let userResponse: string;
        switch (nudge.nudgeType) {
          case 'morning_checkin':
            userResponse = "Hey Sara! I saw your check-in. What's on my schedule today?";
            break;
          case 'missed_meal':
          case 'late_breakfast':
          case 'late_lunch':
          case 'late_dinner':
            userResponse = "Thanks for the reminder about eating. What should I have?";
            break;
          case 'bedtime':
            userResponse = "I know, I know... I should go to bed. What do I have tomorrow morning?";
            break;
          default:
            userResponse = `I got your message: "${nudge.title}". What do you think I should do?`;
        }

        console.log('[Chat] Sending nudge response:', userResponse);
        handleSendMessage(userResponse);
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
  }, [isStreaming, isLoadingHistory]);

  const handleVoiceMessage = async (audioUri: string) => {
    if (!voiceInitialized) {
      Alert.alert('Voice Not Available', 'Microphone permission is required for voice chat.');
      return;
    }

    try {
      setIsStreaming(true);
      setStreamingMessage('Transcribing...');

      // Transcribe audio using native iOS speech recognition
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

      // Send transcribed text through regular chat (same as text messages)
      const updatedMessages = [...messages, userMessage];
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
          const responseText = streamingMessageRef.current;

          // Add assistant message with episode_id for rating
          const assistantMessage: Message = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: responseText,
            created_at: new Date().toISOString(),
            episode_id: episodeId,  // Include episode_id for star rating
          };

          console.log('[Chat] 🎤 Voice response with episode_id:', episodeId);
          setMessages((prev) => [...prev, assistantMessage]);
          setStreamingMessage('');
          streamingMessageRef.current = '';
          setIsStreaming(false);

          if (newConversationId && !conversationId) {
            setConversationId(newConversationId);
          }

          // Speak the response using native iOS TTS (emojis will be stripped)
          setIsPlayingAudio(true);
          await voiceService.speak(responseText);
          setIsPlayingAudio(false);

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
        ) : (
          <StreamingIndicator />
        )}
      </View>
    );
  };

  // Get display name for selected model
  const selectedModelName = availableModels?.models?.find(m => m.id === selectedModel)?.name || selectedModel;

  // Group models by provider
  const groupedModels = availableModels?.models?.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = [];
    acc[model.provider].push(model);
    return acc;
  }, {} as Record<string, ChatModel[]>) || {};

  return (
    <SafeAreaView style={[styles.container, isEphemeral && styles.ephemeralContainer]} edges={['bottom']}>
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
                    {provider === 'anthropic' ? 'Claude' : provider === 'google' ? 'Gemini' : 'Local'}
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
