import apiClient from './api';
import { Message } from '../types/api';

export interface SendMessageParams {
  messages: Message[];  // Changed from single message to full conversation history
  conversationId?: string;
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
    onComplete: (conversationId: string) => void,
    onError: (error: Error) => void
  ): Promise<void> {
    // Format messages for API - send full conversation history
    const formattedMessages = params.messages.map(msg => ({
      role: msg.role,
      content: msg.content,
    }));

    const requestBody: any = { messages: formattedMessages };
    if (params.conversationId) {
      requestBody.conversation_id = params.conversationId;
    }

    try {
      await apiClient.streamChat(
        formattedMessages,
        onChunk,
        (conversationId) => {
          // Use the conversation_id from backend if provided, otherwise use the one we sent
          onComplete(conversationId || params.conversationId || '');
        },
        onError,
        params.conversationId  // Pass session_id to maintain conversation history
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
