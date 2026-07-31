import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface MomentCard {
  id: string;
  kind: 'proof_of_memory' | 'artifact_unwrap';
  title: string;
  body: string;
}

const KIND_ICON: Record<string, string> = {
  proof_of_memory: '💭',
  artifact_unwrap: '🎁',
};

/**
 * items 5.8/5.9 (2026-07-31) — mirrors the web MomentCardStack. Rare, minted
 * cards: a right-moment memory callback, or "Sara made you something."
 * Renders nothing when there's nothing to show.
 */
export default function MomentCardStack() {
  const [cards, setCards] = useState<MomentCard[]>([]);
  const [unwrapped, setUnwrapped] = useState<Set<string>>(new Set());

  useEffect(() => {
    apiClient
      .get<MomentCard[]>('/api/moment-cards')
      .then((data) => setCards(Array.isArray(data) ? data : []))
      .catch(() => setCards([]));
  }, []);

  if (cards.length === 0) return null;

  const unwrap = async (card: MomentCard) => {
    if (unwrapped.has(card.id)) return;
    setUnwrapped((prev) => new Set(prev).add(card.id));
    try {
      await apiClient.post(`/api/moment-cards/${card.id}/seen`, {});
    } catch {
      // best-effort
    }
  };

  const dismiss = async (card: MomentCard) => {
    setCards((prev) => prev.filter((c) => c.id !== card.id));
    try {
      await apiClient.post(`/api/moment-cards/${card.id}/dismiss`, {});
    } catch {
      // no-op
    }
  };

  return (
    <View style={styles.stack}>
      {cards.map((card) => {
        const isUnwrapped = unwrapped.has(card.id);
        return (
          <View key={card.id} style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.icon}>{KIND_ICON[card.kind] || '✨'}</Text>
              <View style={styles.body}>
                <Text style={styles.eyebrow}>{card.title}</Text>
                {isUnwrapped ? (
                  <Text style={styles.bodyText}>{card.body}</Text>
                ) : (
                  <TouchableOpacity style={styles.unwrapBtn} onPress={() => unwrap(card)} activeOpacity={0.8}>
                    <Text style={styles.unwrapText}>
                      {card.kind === 'artifact_unwrap' ? 'Unwrap' : 'See what she means'}
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
              {isUnwrapped && (
                <TouchableOpacity onPress={() => dismiss(card)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                  <Text style={styles.dismiss}>✕</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: spacing.sm, marginBottom: spacing.lg },
  card: {
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: 'rgba(94, 234, 212, 0.25)',
    backgroundColor: 'rgba(45, 212, 191, 0.08)',
    padding: spacing.md,
  },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  icon: { fontSize: 22, lineHeight: 26 },
  body: { flex: 1 },
  eyebrow: {
    color: '#5eead4',
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },
  bodyText: { color: colors.text, fontSize: fontSizes.sm, lineHeight: 21, marginTop: 6 },
  unwrapBtn: {
    marginTop: spacing.sm,
    alignSelf: 'flex-start',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(94, 234, 212, 0.35)',
    backgroundColor: 'rgba(45, 212, 191, 0.12)',
    paddingVertical: 7,
    paddingHorizontal: spacing.md,
  },
  unwrapText: { color: '#5eead4', fontSize: fontSizes.sm, fontWeight: '600' },
  dismiss: { color: colors.textMuted, fontSize: fontSizes.md },
});
