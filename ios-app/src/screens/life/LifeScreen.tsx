import React from 'react';
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../../styles/theme';

/**
 * SINGULAR_SARA_MASTER_PLAN §U0/§U6 — "Life: calendar, communications,
 * people, routines, fitness/recovery, food, location, and home." Primary
 * tab per §U8's recommended iOS structure (Sara, Today, Chat, Life, More).
 *
 * A hub, not a rewrite: every destination here is the existing, unmodified
 * screen, reached the same way `MoreScreen` already reaches its
 * destinations (push via the app stack) — Fitness moves from a primary tab
 * to being reachable from here (and still works from any existing
 * `navigation.navigate('Fitness')` call site via the same stack).
 */

interface LifeItem {
  name: string;
  icon: React.ComponentProps<typeof Ionicons>['name'];
  label: string;
  screen: string;
  description: string;
}

const LIFE_ITEMS: LifeItem[] = [
  {
    name: 'Calendar',
    icon: 'calendar-outline',
    label: 'Calendar',
    screen: 'Calendar',
    description: 'Events, schedule, and upcoming commitments.',
  },
  {
    name: 'Email',
    icon: 'mail-outline',
    label: 'Email',
    screen: 'Email',
    description: 'Inbox, drafts, and messages needing a reply.',
  },
  {
    name: 'Fitness',
    icon: 'barbell-outline',
    label: 'Fitness',
    screen: 'Fitness',
    description: 'Workouts, recovery, nutrition, and progress.',
  },
  {
    name: 'Recipes',
    icon: 'restaurant-outline',
    label: 'Recipes',
    screen: 'Recipes',
    description: 'Saved recipes and meal ideas.',
  },
];

export default function LifeScreen() {
  const navigation = useNavigation();

  const handlePress = (screen: string) => {
    (navigation as any).navigate(screen);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Your Life</Text>
          <Text style={styles.title}>Life</Text>
          <Text style={styles.subtitle}>
            Calendar, email, fitness, and recipes — the routines outside work.
          </Text>
        </View>

        <View style={styles.sectionCard}>
          {LIFE_ITEMS.map((item, index) => (
            <TouchableOpacity
              key={item.name}
              style={[
                styles.menuRow,
                index < LIFE_ITEMS.length - 1 && styles.menuRowBorder,
              ]}
              onPress={() => handlePress(item.screen)}
              activeOpacity={0.75}
            >
              <View style={styles.menuIconWrap}>
                <Ionicons name={item.icon} size={22} color={colors.primary} />
              </View>
              <View style={styles.menuCopy}>
                <Text style={styles.menuLabel}>{item.label}</Text>
                <Text style={styles.menuDescription}>{item.description}</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.lg },
  heroCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    padding: spacing.lg,
    marginBottom: spacing.xl,
    ...shadows.sm,
  },
  heroEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  title: { fontSize: fontSizes.xxl, fontWeight: 'bold', color: colors.text },
  subtitle: { marginTop: spacing.sm, color: colors.textSecondary, fontSize: fontSizes.sm, lineHeight: 20 },
  sectionCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    overflow: 'hidden',
  },
  menuRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  menuRowBorder: { borderBottomWidth: 1, borderBottomColor: colors.assistant.border },
  menuIconWrap: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panelRaised,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuCopy: { flex: 1, gap: 2 },
  menuLabel: { fontSize: fontSizes.md, color: colors.text, fontWeight: '600' },
  menuDescription: { fontSize: fontSizes.xs, color: colors.textMuted, marginTop: 2 },
});
