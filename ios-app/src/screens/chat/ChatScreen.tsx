import React, { useState, useRef, useEffect } from 'react';
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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { MainTabScreenProps } from '../../types/navigation';
import { Message } from '../../types/api';
import { chatService } from '../../services/chat';
import { voiceService } from '../../services/voice';
import MessageBubble from '../../components/chat/MessageBubble';
import StreamingIndicator from '../../components/chat/StreamingIndicator';
import ChatInput from '../../components/chat/ChatInput';
import { colors, spacing } from '../../styles/theme';
import { apiClient } from '../../services/api';

type Props = MainTabScreenProps<'Chat'>;

export default function ChatScreen({ navigation }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [voiceInitialized, setVoiceInitialized] = useState(false);
  const [continuousVoiceMode, setContinuousVoiceMode] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const flatListRef = useRef<FlatList>(null);
  const streamingMessageRef = useRef('');
  const isRecordingRef = useRef(false);
  const shouldResumeListening = useRef(false);
  const hasLoadedHistory = useRef(false);

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

  const handleSendMessage = async (messageText: string) => {
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

    console.log('[Chat] 📤 Sending message with conversationId:', conversationId);

    await chatService.sendMessage(
      {
        messages: conversationMessages,  // Send full history, not just new message
        conversationId,
      },
      // onChunk - called for each piece of streaming text
      (chunk: string) => {
        streamingMessageRef.current += chunk;
        setStreamingMessage(streamingMessageRef.current);
      },
      // onComplete - called when streaming finishes
      (newConversationId: string) => {
        // Add the complete assistant message
        const assistantMessage: Message = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: streamingMessageRef.current,
          created_at: new Date().toISOString(),
        };

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
        },
        // onChunk
        (chunk: string) => {
          streamingMessageRef.current += chunk;
          setStreamingMessage(streamingMessageRef.current);
        },
        // onComplete
        async (newConversationId: string) => {
          const responseText = streamingMessageRef.current;

          // Add assistant message
          const assistantMessage: Message = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: responseText,
            created_at: new Date().toISOString(),
          };

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

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 0}
      >
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
