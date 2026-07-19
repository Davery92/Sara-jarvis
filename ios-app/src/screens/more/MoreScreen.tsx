import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ScrollView } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { borderRadius, colors, fontSizes, shadows, spacing } from '../../styles/theme';

interface MenuItem {
  name: string;
  icon: React.ComponentProps<typeof Ionicons>['name'];
  label: string;
  screen: string;
  description: string;
}

interface MenuSection {
  title: string;
  description: string;
  items: MenuItem[];
}

const menuSections: MenuSection[] = [
  {
    title: 'Assistant',
    description: 'Review what Sara has surfaced, delegated, or queued for your attention.',
    items: [
      {
        name: 'AssistantAnalytics',
        icon: 'analytics-outline',
        label: 'Assistant Usage',
        screen: 'AssistantAnalytics',
        description: 'See whether the redesign is changing actual behavior.',
      },
      {
        name: 'Notifications',
        icon: 'notifications-outline',
        label: 'Notifications',
        screen: 'Notifications',
        description: 'Recent nudges, discoveries, and alerts from Sara.',
      },
      {
        name: 'Briefings',
        icon: 'sunny-outline',
        label: 'Morning Brief',
        screen: 'Briefings',
        description: 'Your daily summary with weather, calendar, and recovery.',
      },
      {
        name: 'AgentTasks',
        icon: 'git-network-outline',
        label: 'Agent Tasks',
        screen: 'AgentTasks',
        description: 'Background jobs, clarifications, and task outcomes.',
      },
      {
        name: 'ACS',
        icon: 'layers-outline',
        label: 'ACS',
        screen: 'ACS',
        description: 'Autonomous cognition sessions, interests, and deliverables.',
      },
      {
        name: 'Automations',
        icon: 'flash-outline',
        label: 'Automations',
        screen: 'Automations',
        description: 'Recurring flows and assistant-triggered actions.',
      },
    ],
  },
  {
    title: 'Planning',
    description: 'The places where you organize today, upcoming work, and commitments.',
    items: [
      {
        name: 'DailyTasks',
        icon: 'checkbox-outline',
        label: 'Daily Tasks',
        screen: 'DailyTasks',
        description: 'Today’s checklist, focus items, and execution view.',
      },
      {
        name: 'Calendar',
        icon: 'calendar-outline',
        label: 'Calendar',
        screen: 'Calendar',
        description: 'Events, reminders, and iOS calendar sync.',
      },
      {
        name: 'Recipes',
        icon: 'restaurant-outline',
        label: 'Recipes',
        screen: 'Recipes',
        description: 'Saved meals and planning around nutrition.',
      },
    ],
  },
  {
    title: 'Knowledge',
    description: 'Your captured material, reference memory, and working context.',
    items: [
      {
        name: 'Learning',
        icon: 'school-outline',
        label: 'Learning',
        screen: 'Learning',
        description: 'Courses, prompts, and guided knowledge-building flows.',
      },
      {
        name: 'Notes',
        icon: 'document-text-outline',
        label: 'Notes',
        screen: 'Notes',
        description: 'Quick notes, folders, and markdown content.',
      },
      {
        name: 'Documents',
        icon: 'documents-outline',
        label: 'Documents',
        screen: 'Documents',
        description: 'Uploaded files, previews, and search.',
      },
      {
        name: 'Studio',
        icon: 'sparkles-outline',
        label: 'Studio',
        screen: 'Studio',
        description: 'Everything Sara has built — docs, code, diagrams — with downloads.',
      },
      {
        name: 'Knowledge',
        icon: 'library-outline',
        label: 'Knowledge',
        screen: 'Knowledge',
        description: 'Structured memory, extracted facts, and PKG views.',
      },
    ],
  },
  {
    title: 'System',
    description: 'Personal data sources, health context, and app controls.',
    items: [
      {
        name: 'System',
        icon: 'pulse-outline',
        label: 'The System',
        screen: 'System',
        description: 'What Sara sees, thinks, and surfaces — world state, attention balance, thoughts.',
      },
      {
        name: 'Machines',
        icon: 'server-outline',
        label: 'Machines',
        screen: 'Machines',
        description: 'Fleet health for every box David owns — CPU, memory, disk, alerts, and the enroll command.',
      },
      {
        name: 'Health',
        icon: 'heart-outline',
        label: 'Apple Health',
        screen: 'Health',
        description: 'HealthKit sync, recovery signals, and metrics.',
      },
      {
        name: 'Settings',
        icon: 'settings-outline',
        label: 'Settings',
        screen: 'Settings',
        description: 'Profile, preferences, memory, and integrations.',
      },
    ],
  },
];

export default function MoreScreen() {
  const navigation = useNavigation();
  const totalDestinations = menuSections.reduce((sum, section) => sum + section.items.length, 0);

  const handleItemPress = (screen: string) => {
    (navigation as any).navigate(screen);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Secondary Spaces</Text>
          <Text style={styles.title}>More</Text>
          <Text style={styles.subtitle}>
            Use this area for specialist tools, deeper review, and system controls beyond the core Sara, Inbox, and Fitness flow.
          </Text>

          <View style={styles.heroStatsRow}>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Sections</Text>
              <Text style={styles.heroStatValue}>{menuSections.length}</Text>
              <Text style={styles.heroStatMeta}>grouped around intent</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Spaces</Text>
              <Text style={styles.heroStatValue}>{totalDestinations}</Text>
              <Text style={styles.heroStatMeta}>secondary destinations</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Primary</Text>
              <Text style={styles.heroStatValue}>3</Text>
              <Text style={styles.heroStatMeta}>surfaces stay out of here</Text>
            </View>
          </View>
        </View>

        {menuSections.map((section) => (
          <View key={section.title} style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionTitleRow}>
                <Text style={styles.sectionTitle}>{section.title}</Text>
                <View style={styles.sectionCountPill}>
                  <Text style={styles.sectionCountText}>{section.items.length}</Text>
                </View>
              </View>
              <Text style={styles.sectionDescription}>{section.description}</Text>
            </View>

            <View style={styles.sectionCard}>
              {section.items.map((item, index) => (
                <TouchableOpacity
                  key={item.name}
                  style={[
                    styles.menuRow,
                    index < section.items.length - 1 && styles.menuRowBorder,
                  ]}
                  onPress={() => handleItemPress(item.screen)}
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
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    padding: spacing.lg,
  },
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
  title: {
    fontSize: fontSizes.xxl,
    fontWeight: 'bold',
    color: colors.text,
  },
  subtitle: {
    marginTop: spacing.sm,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  heroStatsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  heroStatCard: {
    flex: 1,
    minWidth: 96,
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
  },
  heroStatLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },
  heroStatValue: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginTop: 2,
  },
  heroStatMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 16,
    marginTop: 2,
  },
  section: {
    marginBottom: spacing.xl,
  },
  sectionHeader: {
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
  sectionCountPill: {
    minWidth: 28,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.full,
    backgroundColor: colors.assistant.panelRaised,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    alignItems: 'center',
  },
  sectionCountText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },
  sectionDescription: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
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
  menuRowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: colors.assistant.border,
  },
  menuIconWrap: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.assistant.panelRaised,
    alignItems: 'center',
    justifyContent: 'center',
  },
  menuCopy: {
    flex: 1,
    gap: 2,
  },
  menuLabel: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
  },
  menuDescription: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    lineHeight: 18,
  },
});
