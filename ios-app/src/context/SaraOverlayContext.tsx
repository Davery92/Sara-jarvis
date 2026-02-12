/**
 * SaraOverlayContext
 *
 * Tracks the current screen name and Sara floating overlay state.
 * Hidden on the Sara tab (full chat already there).
 * Uses navigationRef (not useNavigationState) so it can live outside NavigationContainer.
 */

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { navigationRef } from '../services/navigation';

type OverlayMode = 'orb' | 'mini' | 'hidden';

interface SaraOverlayState {
  mode: OverlayMode;
  currentScreen: string;
  setMode: (mode: OverlayMode) => void;
}

const SaraOverlayContext = createContext<SaraOverlayState>({
  mode: 'orb',
  currentScreen: 'Sara',
  setMode: () => {},
});

export function useSaraOverlay() {
  return useContext(SaraOverlayContext);
}

function getCurrentScreenName(): string {
  if (!navigationRef.isReady()) return 'Sara';
  try {
    const state = navigationRef.getRootState();
    if (!state) return 'Sara';
    // Root stack → Main → AppStack(MainTabs) → tab name
    const mainRoute = state.routes.find((r) => r.name === 'Main');
    if (mainRoute && mainRoute.state) {
      const appState = mainRoute.state;
      const tabsRoute = appState.routes?.find((r: any) => r.name === 'MainTabs');
      if (tabsRoute && tabsRoute.state) {
        const tabState = tabsRoute.state;
        const activeTab = tabState.routes?.[tabState.index ?? 0];
        return activeTab?.name ?? 'Sara';
      }
      // Stack screen (Notes, Documents, etc.)
      const activeRoute = appState.routes?.[appState.index ?? 0];
      return activeRoute?.name ?? 'Sara';
    }
    return 'Sara';
  } catch {
    return 'Sara';
  }
}

export function SaraOverlayProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeRaw] = useState<OverlayMode>('orb');
  const [currentScreen, setCurrentScreen] = useState('Sara');
  const prevScreenRef = useRef('Sara');

  // Poll navigation state to track current screen
  useEffect(() => {
    const interval = setInterval(() => {
      const screen = getCurrentScreenName();
      if (screen !== prevScreenRef.current) {
        prevScreenRef.current = screen;
        setCurrentScreen(screen);
        // Collapse mini-chat when switching tabs
        if (screen === 'Sara') {
          setModeRaw('orb');
        }
      }
    }, 500);
    return () => clearInterval(interval);
  }, []);

  const setMode = useCallback((newMode: OverlayMode) => {
    setModeRaw(newMode);
  }, []);

  // Auto-hide on Sara tab
  const effectiveMode = currentScreen === 'Sara' ? 'hidden' : mode;

  return (
    <SaraOverlayContext.Provider value={{ mode: effectiveMode, currentScreen, setMode }}>
      {children}
    </SaraOverlayContext.Provider>
  );
}
