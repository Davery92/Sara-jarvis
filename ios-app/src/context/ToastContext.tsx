import React, { createContext, useContext, useState, useCallback, useRef, ReactNode } from 'react';
import { Animated, Text, TouchableOpacity, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { colors, spacing, fontSizes } from '../styles/theme';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastData {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastContextType {
  showToast: (type: ToastType, message: string, duration?: number) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

const TOAST_COLORS: Record<ToastType, string> = {
  success: colors.success,
  error: colors.error,
  warning: colors.warning,
  info: colors.info,
};

const TOAST_ICONS: Record<ToastType, string> = {
  success: '\u2713',
  error: '!',
  warning: '\u26A0',
  info: 'i',
};

function Toast({ toast, onDismiss }: { toast: ToastData; onDismiss: () => void }) {
  const insets = useSafeAreaInsets();
  const translateY = useRef(new Animated.Value(-100)).current;

  React.useEffect(() => {
    Animated.spring(translateY, {
      toValue: 0,
      useNativeDriver: true,
      tension: 80,
      friction: 10,
    }).start();
  }, []);

  const handleDismiss = () => {
    Animated.timing(translateY, {
      toValue: -100,
      duration: 200,
      useNativeDriver: true,
    }).start(() => onDismiss());
  };

  return (
    <Animated.View
      style={[
        styles.toast,
        {
          top: insets.top + 8,
          transform: [{ translateY }],
          borderLeftColor: TOAST_COLORS[toast.type],
        },
      ]}
    >
      <View style={[styles.iconCircle, { backgroundColor: TOAST_COLORS[toast.type] }]}>
        <Text style={styles.iconText}>{TOAST_ICONS[toast.type]}</Text>
      </View>
      <Text style={styles.message} numberOfLines={2}>{toast.message}</Text>
      <TouchableOpacity onPress={handleDismiss} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
        <Text style={styles.dismiss}>X</Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastData | null>(null);
  const idRef = useRef(0);
  const timerRef = useRef<NodeJS.Timeout>();

  const showToast = useCallback((type: ToastType, message: string, duration = 3000) => {
    if (timerRef.current) clearTimeout(timerRef.current);

    const id = ++idRef.current;
    setToast({ id, type, message });

    timerRef.current = setTimeout(() => {
      setToast((current) => (current?.id === id ? null : current));
    }, duration);
  }, []);

  const dismiss = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setToast(null);
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toast && <Toast toast={toast} onDismiss={dismiss} />}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

const styles = StyleSheet.create({
  toast: {
    position: 'absolute',
    left: spacing.md,
    right: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: 12,
    borderLeftWidth: 4,
    padding: spacing.md,
    gap: spacing.sm,
    zIndex: 10000,
    elevation: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  iconCircle: {
    width: 24,
    height: 24,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  iconText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '700',
  },
  message: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  dismiss: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    paddingLeft: spacing.sm,
  },
});
