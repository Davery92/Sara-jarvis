import React from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { navigateToChat } from '../../services/navigation';
import { colors } from '../../styles/theme';
import ACSStatusCard from '../../components/sara/ACSStatusCard';
import SaraOverviewPanel from '../../components/sara/SaraOverviewPanel';

interface SaraScreenProps {
  navigation?: any;
  route?: any;
}

export default function SaraScreen(props: SaraScreenProps) {
  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <ACSStatusCard />
        <SaraOverviewPanel
          onOpenChat={() => navigateToChat()}
          onPrompt={(prompt) => {
            navigateToChat({
              quickReply: {
                message: prompt,
                title: 'Dashboard prompt',
              },
            });
          }}
          onOpenCalendar={() => props.navigation?.navigate('Calendar')}
          onOpenTasks={() => props.navigation?.navigate('DailyTasks')}
          onOpenInbox={() => props.navigation?.navigate('AssistantInboxTab')}
        />
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
    paddingBottom: 24,
  },
});
