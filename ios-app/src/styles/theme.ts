// Theme configuration
export const colors = {
  // Primary colors (matching web app)
  primary: '#0d7ff2',
  primaryDark: '#0c6fd1',
  secondary: '#8b5cf6',
  accent: '#06b6d4',

  // Background colors
  background: '#18181b',
  surface: '#27272a',
  surfaceLight: '#3f3f46',

  // Text colors
  text: '#f8fafc',
  textSecondary: '#a1a1aa',
  textMuted: '#71717a',

  // Status colors
  success: '#10b981',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#3b82f6',

  // UI colors
  border: '#3f3f46',
  divider: '#27272a',
  shadow: '#000000',
  overlay: 'rgba(0, 0, 0, 0.5)',

  // Fitness colors
  fitness: {
    calories: '#f59e0b',
    protein: '#3b82f6',
    carbs: '#10b981',
    fats: '#ef4444',
  },
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

export const borderRadius = {
  sm: 4,
  md: 8,
  lg: 12,
  xl: 16,
  full: 9999,
};

export const fontSizes = {
  xs: 12,
  sm: 14,
  md: 16,
  lg: 18,
  xl: 20,
  xxl: 24,
  xxxl: 32,
};

export const fontWeights = {
  regular: '400' as const,
  medium: '500' as const,
  semibold: '600' as const,
  bold: '700' as const,
};

export const shadows = {
  sm: {
    shadowColor: colors.shadow,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.18,
    shadowRadius: 1.0,
    elevation: 1,
  },
  md: {
    shadowColor: colors.shadow,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.23,
    shadowRadius: 2.62,
    elevation: 4,
  },
  lg: {
    shadowColor: colors.shadow,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.30,
    shadowRadius: 4.65,
    elevation: 8,
  },
};

export const theme = {
  colors,
  spacing,
  borderRadius,
  fontSizes,
  fontWeights,
  shadows,
};

export type Theme = typeof theme;
