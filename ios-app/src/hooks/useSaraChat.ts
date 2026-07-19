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
import { handleSaraUiCommand, SaraUiCommand } from '../services/navigation';

interface UseSaraChatOptions {
  source?: string;
  currentScreen?: string;
  // Called when the backend emits a ui_command ("open my inbox").
  // Defaults to handleSaraUiCommand (navigate to the screen).
  onUiCommand?: (command: SaraUiCommand) => void;
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
  // Empty = no override; the backend uses its configured default model.
  const [selectedModel, setSelectedModel] = useState<string>('');

  const messagesRef = useRef<Message[]>([]);
  const streamingMessageRef = useRef('');
  const hasLoadedHistory = useRef(false);
  // Mirror of pendingCards so the streaming onComplete closure (captured at
  // request start, when pendingCards was just cleared) reads cards that arrived
  // mid-stream. Without this, content cards never attach to the message.
  const pendingCardsRef = useRef<ContentCardType[]>([]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const loadHistory = useCallback(async () => {
    if (hasLoadedHistory.current) return;
    hasLoadedHistory.current = true;

    try {
      setIsLoadingHistory(true);
      const candidateIds: string[] = [];

      try {
        const sessionData = await chatService.getActiveSession();
        const sessionConvId = sessionData.session?.conversation_id;
        if (sessionData.active && sessionConvId && sessionConvId !== 'unknown') {
          candidateIds.push(sessionConvId);
        }
      } catch {}

      try {
        const activeResponse = await apiClient.get('/api/conversations/active');
        const activeConvId = (activeResponse as any)?.conversation_id || null;
        if (activeConvId && !candidateIds.includes(activeConvId)) {
          candidateIds.push(activeConvId);
        }
      } catch {}

      for (const savedConversationId of candidateIds) {
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
          return;
        }
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
      pendingCardsRef.current = [];
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
            pendingCardsRef.current = [...pendingCardsRef.current, card];
            setPendingCards((prev) => [...prev, card]);
          },
          onToolStatus: (status: ToolStatus) => {
            setActiveToolStatus(status.status === 'executing' ? status : null);
          },
          onSuggestedActions: (actions: SuggestedAction[]) => {
            setSuggestedActions(actions);
          },
          onUiCommand: (command: SaraUiCommand) => {
            if (options?.onUiCommand) {
              options.onUiCommand(command);
            } else {
              handleSaraUiCommand(command);
            }
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
            cards: [...pendingCardsRef.current],
          };

          setMessages((prev) => [...prev, assistantMessage]);
          setStreamingMessage('');
          streamingMessageRef.current = '';
          setIsStreaming(false);
          setPendingCards([]);
          pendingCardsRef.current = [];
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
    [conversationId, selectedModel, pendingCards, options?.source, options?.currentScreen, options?.onUiCommand]
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
