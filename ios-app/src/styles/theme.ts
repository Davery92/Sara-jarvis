// Theme configuration
//
// Single source of truth for Sara's brand on iOS. Matches the webapp tokens
// (frontend/src/index.css + DESIGN_LANGUAGE.md): deep navy backgrounds, teal
// as the single action color, slate text ramp. If you change a value here,
// check it against the web palette first — the two platforms must stay one brand.
export const colors = {
  // Primary colors (matching web app: teal accent on deep navy)
  primary: '#14b8a6',      // web --assistant-accent-strong
  primaryDark: '#0d9488',
  secondary: '#8b5cf6',
  accent: '#5eead4',       // web --assistant-accent

  // Background colors
  background: '#050b16',   // web body background
  surface: '#0c1626',      // web flat card surface
  surfaceLight: '#16233a',

  // Text colors (slate ramp, matching web text-slate-100/400/500)
  text: '#f1f5f9',
  textSecondary: '#94a3b8',
  textMuted: '#64748b',

  // Status colors
  success: '#34d399',
  warning: '#fbbf24',
  error: '#fb7185',
  info: '#7dd3fc',

  // UI colors
  border: 'rgba(130, 151, 182, 0.16)',  // web --assistant-border
  divider: 'rgba(130, 151, 182, 0.10)',
  shadow: '#000000',
  overlay: 'rgba(2, 8, 23, 0.6)',

  // Assistant product palette
  assistant: {
    panel: '#0c1626',
    panelRaised: '#13203a',
    panelMuted: '#0a1322',
    border: 'rgba(130, 151, 182, 0.16)',
    borderStrong: 'rgba(94, 234, 212, 0.24)',  // web --assistant-border-strong
    action: '#14b8a6',
    actionSoft: 'rgba(45, 212, 191, 0.16)',
    passive: '#5eead4',
    passiveSoft: 'rgba(94, 234, 212, 0.14)',
    alert: '#fbbf24',
    alertSoft: 'rgba(251, 191, 36, 0.16)',
    successSoft: 'rgba(52, 211, 153, 0.16)',
    errorSoft: 'rgba(251, 113, 133, 0.16)',
  },

  // Extended hues — semantic accents shared across screens (ACS console event
  // kinds, tags, charts). Use these instead of hardcoding Tailwind hex values
  // in components; they mirror the Tailwind-400 hues the webapp uses.
  hues: {
    indigo: '#818cf8',
    violet: '#a78bfa',
    sky: '#38bdf8',
    cyan: '#22d3ee',
    orange: '#fb923c',
    fuchsia: '#e879f9',
    rose: '#fb7185',
    emerald: '#34d399',
    amber: '#fbbf24',
    slate: '#cbd5e1',
  },

  // Fitness colors
  fitness: {
    calories: '#f59e0b',
    protein: '#3b82f6',
    carbs: '#10b981',
    fats: '#ef4444',

    // Day-type accents — used anywhere we surface training vs rest
    // day macros/calories (dashboard hero, nutrition header, plan view).
    // Paired with Ionicons: 'flash' (training) / 'moon' (rest).
    trainingDay: '#8b5cf6',       // purple — matches webapp training badge
    trainingDayBg: 'rgba(139, 92, 246, 0.12)',
    restDay: '#3b82f6',           // blue — matches webapp rest badge
    restDayBg: 'rgba(59, 130, 246, 0.12)',

    // Plan section accents (parity with webapp PlanView)
    phaseAccent: 'rgba(59, 130, 246, 0.5)',      // blue for Phase sections
    nutritionAccent: 'rgba(16, 185, 129, 0.5)',  // green for Nutrition sections
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
