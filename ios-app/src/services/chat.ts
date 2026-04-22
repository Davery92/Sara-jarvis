import apiClient, { ChatOptions } from './api';
import { Message, MessageContent } from '../types/api';
import { ImageAttachment } from './imagePicker';

export interface SendMessageParams {
  messages: Message[];  // Changed from single message to full conversation history
  conversationId?: string;
  images?: ImageAttachment[];  // Optional images to attach to the last message
  model?: string;  // Optional model override
  ephemeral?: boolean;  // If true, chat won't be saved to memory
  inboxItemId?: string;  // Pre-load inbox item content for discussion
  noteId?: string;  // Pre-load note content for discussion
  source?: string;  // 'ios' | 'ios_overlay'
  currentScreen?: string;  // Current screen for context-aware tool loading
  onContentCard?: (card: any) => void;
  onToolStatus?: (status: { tool: string; status: string }) => void;
  onSuggestedActions?: (actions: any[]) => void;
}

export interface ChatResponse {
  message: Message;
  conversation_id: string;
}

class ChatService {
  /**
   * Send a message with full conversation history and get streaming response
   */
  async sendMessage(
    params: SendMessageParams,
    onChunk: (chunk: string) => void,
    onComplete: (conversationId: string, episodeId?: string) => void,
    onError: (error: Error) => void
  ): Promise<void> {
    // Format messages for API - send full conversation history
    const formattedMessages = params.messages.map((msg, index) => {
      let content: MessageContent = msg.content;

      // If this is the last message and we have images, format as multimodal
      if (index === params.messages.length - 1 && params.images && params.images.length > 0) {
        const textContent = typeof msg.content === 'string'
          ? msg.content
          : (msg.content as any[]).find(c => c.type === 'text')?.text || '';

        content = [
          // Add images first
          ...params.images.map(img => ({
            type: 'image' as const,
            data: img.base64,
            media_type: img.type,
          })),
          // Then add text
          { type: 'text' as const, text: textContent },
        ];
      }

      return {
        role: msg.role,
        content,
      };
    });

    const requestBody: any = { messages: formattedMessages };
    if (params.conversationId) {
      requestBody.conversation_id = params.conversationId;
    }

    try {
      // Build chat options
      const chatOptions: ChatOptions = {
        // Always request notification on complete so background responses notify the user
        notifyOnComplete: true,
      };
      if (params.model) {
        chatOptions.model = params.model;
      }
      if (params.ephemeral) {
        chatOptions.ephemeral = params.ephemeral;
      }
      if (params.inboxItemId) {
        chatOptions.inboxItemId = params.inboxItemId;
      }
      if (params.noteId) {
        chatOptions.noteId = params.noteId;
      }
      if (params.source) {
        chatOptions.source = params.source;
      }
      if (params.currentScreen) {
        chatOptions.currentScreen = params.currentScreen;
      }
      if (params.onContentCard) {
        chatOptions.onContentCard = params.onContentCard;
      }
      if (params.onToolStatus) {
        chatOptions.onToolStatus = params.onToolStatus;
      }
      if (params.onSuggestedActions) {
        chatOptions.onSuggestedActions = params.onSuggestedActions;
      }

      await apiClient.streamChat(
        formattedMessages,
        onChunk,
        (conversationId, episodeId) => {
          // Use the conversation_id from backend if provided, otherwise use the one we sent
          onComplete(conversationId || params.conversationId || '', episodeId);
        },
        onError,
        params.conversationId,  // Pass session_id to maintain conversation history
        chatOptions  // Pass model and ephemeral options
      );
    } catch (error) {
      onError(error as Error);
    }
  }

  /**
   * Get message history for a conversation
   */
  async getConversationHistory(conversationId: string): Promise<Message[]> {
    const response = await apiClient.get<{ messages: Message[] }>(
      `/conversations/${conversationId}/messages`
    );
    return response.messages;
  }

  /**
   * Clear conversation (start fresh)
   */
  async clearConversation(): Promise<void> {
    // Just start a new conversation by not passing conversation_id
    // The backend will create a new one
  }

  /**
   * Check for an active session across devices.
   * Returns the active conversation_id if one exists and is < 1hr old.
   */
  async getActiveSession(): Promise<{ active: boolean; session?: { conversation_id?: string; last_device?: string; turn_count?: number; topic_summary?: string } }> {
    try {
      const response = await apiClient.get<{ active: boolean; session?: any }>('/api/session/active');
      return response;
    } catch {
      return { active: false };
    }
  }

  /**
   * Acknowledge a notification (track outcome for adaptive check-in frequency).
   */
  async ackNotification(notificationId: number, outcome: 'opened_chat' | 'dismissed'): Promise<void> {
    try {
      await apiClient.post(`/api/session/notifications/${notificationId}/ack`, { outcome });
    } catch {
      // Non-critical
    }
  }
}

export const chatService = new ChatService();
export default chatService;
