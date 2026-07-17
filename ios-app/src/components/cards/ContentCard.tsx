import React, { useEffect, useRef } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Animated } from 'react-native';
import { ContentCard as ContentCardType, CardAction } from '../../types/cards';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import CalendarCard from './CalendarCard';
import ReminderCard from './ReminderCard';
import TimerCard from './TimerCard';
import NotesCard from './NotesCard';
import NutritionCard from './NutritionCard';
import EmailCard from './EmailCard';
import HealthCard from './HealthCard';
import LearningCard from './LearningCard';
import HomeCard from './HomeCard';
import GenericCard from './GenericCard';

interface ContentCardProps {
  card: ContentCardType;
  onAction: (action: CardAction) => void;
  index?: number;
}

const CARD_COMPONENTS: Record<string, React.FC<any>> = {
  calendar_card: CalendarCard,
  reminder_card: ReminderCard,
  timer_card: TimerCard,
  notes_card: NotesCard,
  note_detail_card: NotesCard,
  nutrition_card: NutritionCard,
  email_card: EmailCard,
  health_card: HealthCard,
  learning_card: LearningCard,
  home_card: HomeCard,
};

export default function ContentCard({ card, onAction, index = 0 }: ContentCardProps) {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const slideAnim = useRef(new Animated.Value(20)).current;

  useEffect(() => {
    const delay = index * 100;
    Animated.parallel([
      Animated.timing(fadeAnim, {
        toValue: 1,
        duration: 200,
        delay,
        useNativeDriver: true,
      }),
      Animated.timing(slideAnim, {
        toValue: 0,
        duration: 200,
        delay,
        useNativeDriver: true,
      }),
    ]).start();
  }, []);

  const CardComponent = CARD_COMPONENTS[card.card_type] || GenericCard;

  return (
    <Animated.View
      style={[
        styles.container,
        { opacity: fadeAnim, transform: [{ translateY: slideAnim }] },
      ]}
    >
      <CardComponent card={card} onAction={onAction} />
      {card.actions && card.actions.length > 0 && (
        <View style={styles.actionsRow}>
          {card.actions.map((action, i) => (
            <TouchableOpacity
              key={i}
              style={styles.actionButton}
              onPress={() => onAction(action)}
            >
              <Text style={styles.actionText}>{action.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginHorizontal: spacing.md,
    marginVertical: spacing.xs,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  actionsRow: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    gap: spacing.sm,
  },
  actionButton: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
    backgroundColor: 'rgba(13, 127, 242, 0.1)',
  },
  actionText: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
});
