import React, { useRef, useState, useEffect } from 'react';
import { View, StyleSheet, Keyboard, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors } from '../../styles/theme';
import ACSStatusCard from '../../components/sara/ACSStatusCard';
import ChatScreen from '../chat/ChatScreen';

interface SaraScreenProps {
  navigation?: any;
  route?: any;
}

export default function SaraScreen(props: SaraScreenProps) {
  const chatRef = useRef<any>(null);
  const [keyboardVisible, setKeyboardVisible] = useState(false);

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const showSub = Keyboard.addListener(showEvent, () => setKeyboardVisible(true));
    const hideSub = Keyboard.addListener(hideEvent, () => setKeyboardVisible(false));
    return () => { showSub.remove(); hideSub.remove(); };
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {!keyboardVisible && <ACSStatusCard />}
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
