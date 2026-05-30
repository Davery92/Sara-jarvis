/**
 * useSaraPresence
 *
 * iOS half of the "make Sara feel present" work (P0.3). Gives the floating orb a
 * live sense of what Sara is actually doing, not just a static emotional emoji.
 *
 * React Native has no native EventSource, so (unlike the web shell, which uses the
 * /api/acs/v2/stream SSE feed) this polls — consistent with the rest of the app:
 *   - /api/sara/status        emotional state (every 20s)
 *   - /api/acs/v2/daemon-status   liveness (every 20s)
 *   - /api/acs/v2/activity?limit=1   newest daemon activity (every 8s)
 *
 * When a *notable* new activity appears (Sara sets a focus, reaches out, thinks),
 * we surface a transient reaction for a few seconds so the orb visibly responds —
 * the "she just noticed something" moment.
 */

import { useEffect, useRef, useState } from 'react';
import { apiClient } from '../services/api';

const EMOTION_EMOJI: Record<string, string> = {
  curious: '🤔', calm: '😌', alert: '⚡', concerned: '😟',
  happy: '😊', focused: '🎯', neutral: '😐', reflective: '🪞', attentive: '👀',
};

interface ReactionStyle {
  emoji: string;
  color: string;
  emphatic?: boolean;
  label: string;
}

// Mirrors the web SaraPresence reaction map. Notable kinds only.
const REACTIONS: Record<string, ReactionStyle> = {
  focus_set:    { emoji: '🎯', color: '#38bdf8', emphatic: true, label: 'noticed something' },
  notify_david: { emoji: '📣', color: '#fbbf24', emphatic: true, label: 'reaching out' },
  thought:      { emoji: '🤔', color: '#818cf8', label: 'thinking' },
  reflection:   { emoji: '🪞', color: '#a78bfa', label: 'reflecting' },
  tool_call:    { emoji: '⚙️', color: '#e879f9', label: 'working' },
  tool_result:  { emoji: '⚙️', color: '#e879f9', label: 'working' },
  inbox_pickup: { emoji: '📥', color: '#22d3ee', label: 'picking it up' },
};

const NOTABLE = new Set(Object.keys(REACTIONS));
const REACTION_MS = 9000;
const IDLE_COLOR = '#0d7ff2'; // theme primary

export interface SaraPresence {
  emotionalState: string;
  emoji: string;
  color: string;
  emphatic: boolean;
  reacting: boolean;
  label: string;
  isAlive: boolean;
}

export function useSaraPresence(): SaraPresence {
  const [emotionalState, setEmotionalState] = useState('neutral');
  const [isAlive, setIsAlive] = useState(true);
  const [reactionKind, setReactionKind] = useState<string | null>(null);

  const lastActivityId = useRef<string | null>(null);
  const seeded = useRef(false);
  const reactionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Emotional state + liveness.
  useEffect(() => {
    let alive = true;
    const fetchStatus = async () => {
      try {
        const s = await apiClient.get<any>('/api/sara/status');
        if (alive && s?.emotional_state) setEmotionalState(s.emotional_state);
      } catch {}
      try {
        const d = await apiClient.get<any>('/api/acs/v2/daemon-status');
        if (alive && typeof d?.is_alive === 'boolean') setIsAlive(d.is_alive);
      } catch {}
    };
    fetchStatus();
    const t = setInterval(fetchStatus, 20000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // Newest activity → transient reaction.
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const rows = await apiClient.get<any[]>('/api/acs/v2/activity?limit=1');
        const latest = Array.isArray(rows) && rows.length ? rows[0] : null;
        if (!latest || !alive) return;
        // First poll just establishes a baseline — don't react to history.
        if (!seeded.current) {
          lastActivityId.current = latest.id;
          seeded.current = true;
          return;
        }
        if (latest.id !== lastActivityId.current) {
          lastActivityId.current = latest.id;
          if (NOTABLE.has(latest.kind)) {
            setReactionKind(latest.kind);
            if (reactionTimer.current) clearTimeout(reactionTimer.current);
            reactionTimer.current = setTimeout(() => setReactionKind(null), REACTION_MS);
          }
        }
      } catch {}
    };
    poll();
    const t = setInterval(poll, 8000);
    return () => {
      alive = false;
      clearInterval(t);
      if (reactionTimer.current) clearTimeout(reactionTimer.current);
    };
  }, []);

  const reaction = reactionKind ? REACTIONS[reactionKind] : null;
  return {
    emotionalState,
    emoji: reaction ? reaction.emoji : (EMOTION_EMOJI[emotionalState] || '🤖'),
    color: reaction ? reaction.color : IDLE_COLOR,
    emphatic: !!reaction?.emphatic,
    reacting: !!reaction,
    label: reaction ? reaction.label : emotionalState,
    isAlive,
  };
}
