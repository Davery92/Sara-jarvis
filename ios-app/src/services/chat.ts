import apiClient, { ChatOptions } from './api';
import { Message, MessageContent } from '../types/api';
import { ImageAttachment } from './imagePicker';

export interface SendMessageParams {
  messages: Message[];  // Changed from single message to full conversation history
  conversationId?: string;
  images?: ImageAttachment[];  // Optional images to attach to the last message
  model?: string;  // Optional model override
  ephemeral?: boolean;  // If true, chat won't be saved to memory
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
      const chatOptions: ChatOptions = {};
      if (params.model) {
        chatOptions.model = params.model;
      }
      if (params.ephemeral) {
        chatOptions.ephemeral = params.ephemeral;
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
}

export const chatService = new ChatService();
export default chatService;
