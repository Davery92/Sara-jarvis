/**
 * Chat Store - Zustand
 *
 * Manages chat state:
 * - Messages
 * - Streaming state
 * - Active conversation
 * - Tool calls
 */

import { create } from 'zustand';

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tool_calls?: any[];
  sources?: any[];
  timestamp?: string;
}

interface ChatState {
  messages: Message[];
  isStreaming: boolean;
  currentConversationId: string | null;
  streamingMessage: string;

  // Actions
  addMessage: (message: Message) => void;
  updateLastMessage: (content: string) => void;
  setMessages: (messages: Message[]) => void;
  clearMessages: () => void;
  setStreaming: (isStreaming: boolean) => void;
  setStreamingMessage: (content: string) => void;
  appendToStreamingMessage: (chunk: string) => void;
  finalizeStreamingMessage: () => void;
  setConversationId: (id: string | null) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  currentConversationId: null,
  streamingMessage: '',

  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message]
  })),

  updateLastMessage: (content) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0) {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        content
      };
    }
    return { messages };
  }),

  setMessages: (messages) => set({ messages }),

  clearMessages: () => set({
    messages: [],
    streamingMessage: '',
    isStreaming: false
  }),

  setStreaming: (isStreaming) => set({ isStreaming }),

  setStreamingMessage: (content) => set({ streamingMessage: content }),

  appendToStreamingMessage: (chunk) => set((state) => ({
    streamingMessage: state.streamingMessage + chunk
  })),

  finalizeStreamingMessage: () => {
    const { streamingMessage, messages } = get();

    if (streamingMessage) {
      set({
        messages: [...messages, {
          role: 'assistant',
          content: streamingMessage,
          timestamp: new Date().toISOString()
        }],
        streamingMessage: '',
        isStreaming: false
      });
    }
  },

  setConversationId: (id) => set({ currentConversationId: id }),
}));
