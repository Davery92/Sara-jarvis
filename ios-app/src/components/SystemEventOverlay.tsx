import React from 'react';
import {
  Modal,
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TouchableOpacity,
  Platform,
  Dimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, borderRadius, fontSizes } from '../styles/theme';

// Global overlay for narrator (System AI) broadcasts.
//
// Tapping a system_event push fills this with the event payload and shows it
// over whatever screen the user is on. iOS truncates long push bodies even in
// long-press preview; this surface always shows the full thing.

export interface SystemEventOverlayPayload {
  event_id: string;
  title: string;
  body: string;
  subtitle?: string | null;
  severity: string;
  trigger_name?: string;
  trigger_context?: Record<string, any>;
}

interface Props {
  payload: SystemEventOverlayPayload | null;
  onClose: () => void;
  onDiscussInChat: (payload: SystemEventOverlayPayload) => void;
}

const SEVERITY_ACCENTS: Record<string, { color: string; tint: string; label: string }> = {
  roast:       { color: '#f87171', tint: 'rgba(248, 113, 113, 0.16)', label: 'ROAST' },
  observation: { color: '#94a3b8', tint: 'rgba(148, 163, 184, 0.12)', label: 'OBSERVATION' },
  achievement: { color: '#fbbf24', tint: 'rgba(251, 191, 36, 0.18)', label: 'ACHIEVEMENT' },
  patch_note:  { color: '#60a5fa', tint: 'rgba(96, 165, 250, 0.16)', label: 'PATCH NOTES' },
  sponsored:   { color: '#d946ef', tint: 'rgba(217, 70, 239, 0.16)', label: 'SPONSORED' },
  grudging:    { color: '#cbd5e1', tint: 'rgba(203, 213, 225, 0.12)', label: 'GRUDGING' },
  deflected:   { color: '#86efac', tint: 'rgba(134, 239, 172, 0.12)', label: 'NOTED' },
};

export default function SystemEventOverlay({ payload, onClose, onDiscussInChat }: Props) {
  const visible = payload !== null;
  const accent = payload
    ? (SEVERITY_ACCENTS[payload.severity] || SEVERITY_ACCENTS.observation)
    : SEVERITY_ACCENTS.observation;

  return (
    <Modal
      animationType="fade"
      transparent
      visible={visible}
      onRequestClose={onClose}
      statusBarTranslucent
    >
      {/* Backdrop: absolute-positioned Pressable BEHIND the card. Tap-outside
          dismisses without ever wrapping the card itself — so the card's
          ScrollView keeps the touch responder for scroll gestures. */}
      <View style={styles.modalRoot}>
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={onClose}
          accessibilityLabel="Dismiss broadcast"
        />
        <SafeAreaView
          style={styles.cardWrap}
          edges={['top', 'bottom']}
          pointerEvents="box-none"
        >
          {payload && (
            <View
              style={[styles.card, { borderColor: accent.color + '55' }]}
              // box-none on a normal View isn't needed — children naturally
              // receive touches and the Pressable underneath gets the rest.
            >
              <View style={[styles.headerBar, { backgroundColor: accent.tint }]}>
                <View style={[styles.severityStripe, { backgroundColor: accent.color }]} />
                <View style={styles.metaRow}>
                  <Text style={[styles.severityLabel, { color: accent.color }]}>
                    {accent.label}
                  </Text>
                  {!!payload.trigger_name && (
                    <>
                      <Text style={styles.metaDot}>·</Text>
                      <Text style={styles.metaText}>{payload.trigger_name}</Text>
                    </>
                  )}
                </View>
                <Text style={styles.title}>{stripTitleEmoji(payload.title)}</Text>
                {!!payload.subtitle && (
                  <Text style={styles.subtitle}>{payload.subtitle}</Text>
                )}
              </View>

              <ScrollView
                style={styles.bodyScroll}
                contentContainerStyle={styles.bodyContent}
                showsVerticalScrollIndicator
                bounces
                // nestedScrollEnabled is a no-op on iOS but harmless;
                // Android needs it when the parent is also scrollable.
                nestedScrollEnabled
                indicatorStyle={Platform.OS === 'ios' ? 'white' : 'default'}
              >
                <Text style={styles.body} selectable>{payload.body}</Text>
              </ScrollView>

              <View style={styles.actions}>
                <TouchableOpacity
                  style={[styles.actionBtn, styles.actionBtnSecondary]}
                  onPress={onClose}
                >
                  <Text style={styles.actionTextSecondary}>Dismiss</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.actionBtn, styles.actionBtnPrimary, { backgroundColor: accent.color }]}
                  onPress={() => onDiscussInChat(payload)}
                >
                  <Text style={styles.actionTextPrimary}>Discuss with Sara</Text>
                </TouchableOpacity>
              </View>
            </View>
          )}
        </SafeAreaView>
      </View>
    </Modal>
  );
}

// Title prefix emoji from the backend (📢 / 🏆 / etc.) reads as noise inside
// the app where the severity already has its own accent. Strip the leading
// emoji + whitespace if present, but only if it's at position 0.
function stripTitleEmoji(title: string): string {
  // Crude but safe: drop any leading non-letter/non-digit chars + whitespace.
  return title.replace(/^[^\w]+\s*/, '').trim() || title;
}

const styles = StyleSheet.create({
  // Root container inside the Modal — fills the screen, hosts the
  // absolute-positioned dismiss layer + the centered card wrapper.
  modalRoot: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.55)',
  },
  // The SafeAreaView that centers the card. `pointerEvents="box-none"` is
  // critical so taps in the empty area around the card pass through to the
  // dismiss Pressable underneath.
  cardWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  // Card sizes to its content. The ScrollView (below) has its own pixel
  // maxHeight so the body area can grow up to that and then scroll —
  // without depending on flexbox to resolve `flex: 1` inside a content-sized
  // parent (which doesn't work reliably in React Native).
  card: {
    width: '100%',
    maxWidth: 480,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    overflow: 'hidden',
    flexDirection: 'column',
  },
  headerBar: {
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
    paddingHorizontal: spacing.md,
    paddingLeft: spacing.md + 8,
    position: 'relative',
    // header has no flex — auto-sizes to its content
  },
  severityStripe: {
    position: 'absolute',
    left: 0, top: spacing.sm, bottom: spacing.sm,
    width: 4,
    borderTopRightRadius: 2,
    borderBottomRightRadius: 2,
  },
  metaRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.xs },
  severityLabel: { fontSize: 11, fontWeight: '800', letterSpacing: 1.4 },
  metaDot: { color: colors.textMuted, marginHorizontal: spacing.xs },
  metaText: { color: colors.textMuted, fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase' },
  title: {
    color: colors.text,
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
    letterSpacing: 0.5,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
    marginTop: spacing.xs,
  },

  // ScrollView gets an explicit pixel maxHeight. When body fits within that,
  // the ScrollView shrinks to content height. When body exceeds it, the
  // ScrollView clamps and the content becomes scrollable. This sidesteps the
  // flex:1 + maxHeight-percentage interaction that didn't work in the last
  // attempt (the ScrollView collapsed to 0 height when the card sized to
  // content, hiding the body).
  bodyScroll: {
    maxHeight: Math.round(Dimensions.get('window').height * 0.55),
  },
  bodyContent: {
    padding: spacing.md,
    paddingBottom: spacing.lg,
  },
  body: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
  },

  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    // footer has no flex — auto-sizes to its content
  },
  actionBtn: {
    flex: 1,
    paddingVertical: spacing.sm + 2,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionBtnSecondary: {
    backgroundColor: colors.surfaceLight,
  },
  actionBtnPrimary: {},
  actionTextSecondary: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  actionTextPrimary: {
    color: '#0b0b0e',
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
});
