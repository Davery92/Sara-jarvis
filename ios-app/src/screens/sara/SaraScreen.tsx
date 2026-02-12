import React, { useState, useRef, useCallback } from 'react';
import { View, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SuggestedAction } from '../../types/cards';
import { colors } from '../../styles/theme';
import IntelligentBrief from '../../components/sara/IntelligentBrief';
import ActionChips from '../../components/sara/ActionChips';
import ChatScreen from '../chat/ChatScreen';

interface SaraScreenProps {
  navigation?: any;
  route?: any;
}

export default function SaraScreen(props: SaraScreenProps) {
  const [briefCollapsed, setBriefCollapsed] = useState(false);
  const chatRef = useRef<any>(null);

  const handleAction = useCallback((action: SuggestedAction) => {
    if (action.action === 'navigate' && action.target && props.navigation) {
      props.navigation.navigate(action.target);
    } else if (action.message) {
      // Send message to embedded chat
      if (chatRef.current?.sendMessage) {
        chatRef.current.sendMessage(action.message);
      }
    }
  }, [props.navigation]);

  const handleBriefToggle = useCallback(() => {
    setBriefCollapsed(c => !c);
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Collapsible Brief Header */}
      <IntelligentBrief
        collapsed={briefCollapsed}
        onToggleCollapse={handleBriefToggle}
        onAction={handleAction}
      />

      {/* Embedded Chat - takes remaining space */}
      <View style={styles.chatContainer}>
        <ChatScreen
          isEmbedded
          onBriefCollapse={() => setBriefCollapsed(true)}
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
