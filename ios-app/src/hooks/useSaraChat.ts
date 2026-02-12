/**
 * useSaraChat - Shared chat hook
 *
 * Extracted from ChatScreen so both the main Sara tab and the
 * FloatingAssistant mini-chat can share conversation state.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { Alert } from 'react-native';
import * as Haptics from 'expo-haptics';
import { Message } from '../types/api';
import { ContentCard as ContentCardType, SuggestedAction, ToolStatus } from '../types/cards';
import { chatService } from '../services/chat';
import { voiceService } from '../services/voice';
import { ImageAttachment } from '../services/imagePicker';
import { apiClient } from '../services/api';

interface UseSaraChatOptions {
  source?: string;
  currentScreen?: string;
}

export function useSaraChat(options?: UseSaraChatOptions) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingCards, setPendingCards] = useState<ContentCardType[]>([]);
  const [suggestedActions, setSuggestedActions] = useState<SuggestedAction[]>([]);
  const [activeToolStatus, setActiveToolStatus] = useState<ToolStatus | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [voiceInitialized, setVoiceInitialized] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:120b');

  const messagesRef = useRef<Message[]>([]);
  const streamingMessageRef = useRef('');
  const hasLoadedHistory = useRef(false);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const loadHistory = useCallback(async () => {
    if (hasLoadedHistory.current) return;
    hasLoadedHistory.current = true;

    try {
      setIsLoadingHistory(true);
      let savedConversationId: string | null = null;

      try {
        const sessionData = await chatService.getActiveSession();
        if (sessionData.active && sessionData.session?.conversation_id) {
          savedConversationId = sessionData.session.conversation_id;
        }
      } catch {}

      if (!savedConversationId) {
        const activeResponse = await apiClient.get('/api/conversations/active');
        savedConversationId = (activeResponse as any)?.conversation_id || null;
      }

      if (!savedConversationId) return;

      const messagesResponse = await apiClient.get(
        `/api/conversations/${savedConversationId}/messages?limit=100`
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
        setConversationId(savedConversationId);
      }
    } catch (error) {
      console.error('[useSaraChat] Error loading history:', error);
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  const initVoice = useCallback(async () => {
    const initialized = await voiceService.initialize();
    setVoiceInitialized(initialized);
    return initialized;
  }, []);

  const sendMessage = useCallback(
    async (messageText: string, images?: ImageAttachment[], inboxItemId?: string) => {
      setSuggestedActions([]);
      setPendingCards([]);
      setActiveToolStatus(null);

      try { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light); } catch {}

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

      const conversationMessages = updatedMessages.filter((m) => m.id !== 'welcome');

      await chatService.sendMessage(
        {
          messages: conversationMessages,
          conversationId,
          images,
          model: selectedModel,
          inboxItemId,
          source: options?.source || 'ios_overlay',
          currentScreen: options?.currentScreen,
          onContentCard: (card: any) => {
            setPendingCards((prev) => [...prev, card]);
          },
          onToolStatus: (status: ToolStatus) => {
            setActiveToolStatus(status.status === 'executing' ? status : null);
          },
          onSuggestedActions: (actions: SuggestedAction[]) => {
            setSuggestedActions(actions);
          },
        },
        (chunk: string) => {
          streamingMessageRef.current += chunk;
          setStreamingMessage(streamingMessageRef.current);
        },
        (newConversationId: string, episodeId?: string) => {
          try { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); } catch {}

          const assistantMessage: Message = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: streamingMessageRef.current,
            created_at: new Date().toISOString(),
            episode_id: episodeId,
            cards: [...pendingCards],
          };

          setMessages((prev) => [...prev, assistantMessage]);
          setStreamingMessage('');
          streamingMessageRef.current = '';
          setIsStreaming(false);
          setPendingCards([]);
          setActiveToolStatus(null);

          if (newConversationId && newConversationId !== conversationId) {
            setConversationId(newConversationId);
          }
        },
        (error: Error) => {
          console.error('[useSaraChat] Chat error:', error);
          setIsStreaming(false);
          setStreamingMessage('');
        }
      );
    },
    [conversationId, selectedModel, pendingCards, options?.source, options?.currentScreen]
  );

  const handleVoiceMessage = useCallback(
    async (audioUri: string) => {
      if (!voiceInitialized) return;
      try {
        setIsStreaming(true);
        setStreamingMessage('Transcribing...');
        const transcribedText = await voiceService.transcribeAudio(audioUri);
        if (!transcribedText || transcribedText.trim().length === 0) {
          setIsStreaming(false);
          setStreamingMessage('');
          return;
        }
        await sendMessage(transcribedText);
      } catch (error) {
        console.error('[useSaraChat] Voice error:', error);
        setIsStreaming(false);
        setStreamingMessage('');
      }
    },
    [voiceInitialized, sendMessage]
  );

  const clearChat = useCallback(async () => {
    setMessages([]);
    setConversationId(null);
    setStreamingMessage('');
    try {
      await apiClient.post('/api/conversations/active', { conversation_id: null });
    } catch {}
  }, []);

  return {
    messages,
    streamingMessage,
    isStreaming,
    pendingCards,
    suggestedActions,
    activeToolStatus,
    conversationId,
    isLoadingHistory,
    voiceInitialized,
    selectedModel,
    setSelectedModel,
    loadHistory,
    initVoice,
    sendMessage,
    handleVoiceMessage,
    clearChat,
    setMessages,
    setSuggestedActions,
  };
}
