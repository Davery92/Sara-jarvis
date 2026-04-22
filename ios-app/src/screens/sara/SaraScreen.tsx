import React, { useRef, useState, useEffect } from 'react';
import { View, StyleSheet, Keyboard, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect } from '@react-navigation/native';
import { colors } from '../../styles/theme';
import ACSStatusCard from '../../components/sara/ACSStatusCard';
import SaraOverviewPanel from '../../components/sara/SaraOverviewPanel';
import ChatScreen from '../chat/ChatScreen';

interface SaraScreenProps {
  navigation?: any;
  route?: any;
}

export default function SaraScreen(props: SaraScreenProps) {
  const chatRef = useRef<any>(null);
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const [forceChatFocus, setForceChatFocus] = useState(false);

  const hasIncomingChatContext = Boolean(
    props.route?.params?.inboxItem ||
    props.route?.params?.noteContext ||
    props.route?.params?.notification ||
    props.route?.params?.quickReply ||
    props.route?.params?.heartbeat ||
    props.route?.params?.healthAlert ||
    props.route?.params?.nudge ||
    props.route?.params?.taskInject,
  );

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const showSub = Keyboard.addListener(showEvent, () => setKeyboardVisible(true));
    const hideSub = Keyboard.addListener(hideEvent, () => setKeyboardVisible(false));
    return () => { showSub.remove(); hideSub.remove(); };
  }, []);

  useEffect(() => {
    if (hasIncomingChatContext) {
      setForceChatFocus(true);
    }
  }, [hasIncomingChatContext]);

  useFocusEffect(
    React.useCallback(() => {
      return () => {
        setForceChatFocus(false);
      };
    }, [])
  );

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {!keyboardVisible && !forceChatFocus && (
        <>
          <ACSStatusCard />
          <SaraOverviewPanel
            onPrompt={(prompt) => {
              setForceChatFocus(true);
              chatRef.current?.sendMessage(prompt);
            }}
            onOpenCalendar={() => props.navigation?.navigate('Calendar')}
            onOpenTasks={() => props.navigation?.navigate('DailyTasks')}
            onOpenInbox={() => props.navigation?.navigate('AssistantInboxTab')}
          />
        </>
      )}
      <View style={styles.chatContainer}>
        <ChatScreen
          isEmbedded
          ref={chatRef}
          navigation={props.navigation}
          route={props.route}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  chatContainer: {
    flex: 1,
  },
});
