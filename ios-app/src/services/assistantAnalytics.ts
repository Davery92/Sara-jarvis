import { Platform } from 'react-native';
import apiClient from './api';

export type AssistantAnalyticsEventType =
  | 'assistant.chat_opened'
  | 'assistant.inbox_opened'
  | 'assistant.inbox_item_opened'
  | 'assistant.message_sent'
  | 'assistant.proactive_context_opened'
  | 'assistant.proactive_context_prompt_used'
  | 'assistant.suggested_action_tapped'
  | 'assistant.voice_hands_free_toggled'
  | 'assistant.voice_hold_to_talk_started';

type AssistantAnalyticsPayload = Record<string, unknown>;

class AssistantAnalyticsService {
  private disabledUntil = 0;

  track(
    eventType: AssistantAnalyticsEventType,
    payload: AssistantAnalyticsPayload = {},
    metadata: AssistantAnalyticsPayload = {},
  ) {
    if (Date.now() < this.disabledUntil) {
      return;
    }

    void apiClient.post('/api/assistant-analytics/events', {
      event_type: eventType,
      payload,
      metadata: {
        platform: Platform.OS,
        ...metadata,
      },
      source: 'ios_app',
    }).catch((error) => {
      this.disabledUntil = Date.now() + 60_000;
      console.log('[AssistantAnalytics] Failed to track event:', eventType, error);
    });
  }
}

export const assistantAnalytics = new AssistantAnalyticsService();
