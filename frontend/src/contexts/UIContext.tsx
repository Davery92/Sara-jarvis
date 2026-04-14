import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { AppView, viewForPath } from '../navigation/views';

interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
}

interface UIContextType {
  view: AppView;
  setView: (view: AppView) => void;
  navigateToView: (view: AppView) => void;
  isMobileMenuOpen: boolean;
  setIsMobileMenuOpen: (open: boolean) => void;
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  toasts: Toast[];
  addToast: (message: string, type?: Toast['type']) => void;
  removeToast: (id: string) => void;
}

const UIContext = createContext<UIContextType | null>(null);

export function UIProvider({ children, onNavigate }: { children: ReactNode; onNavigate?: (view: AppView) => void }) {
  const [view, setViewState] = useState<AppView>(() => viewForPath(window.location.pathname));
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const setView = useCallback((v: AppView) => {
    setViewState(v);
    setIsMobileMenuOpen(false);
  }, []);

  const navigateToView = useCallback((v: AppView) => {
    setView(v);
    onNavigate?.(v);
  }, [setView, onNavigate]);

  const addToast = useCallback((message: string, type: Toast['type'] = 'info') => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 5000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  return (
    <UIContext.Provider value={{
      view, setView, navigateToView,
      isMobileMenuOpen, setIsMobileMenuOpen,
      commandPaletteOpen, setCommandPaletteOpen,
      toasts, addToast, removeToast,
    }}>
      {children}
    </UIContext.Provider>
  );
}

export function useUI() {
  const ctx = useContext(UIContext);
  if (!ctx) throw new Error('useUI must be used within UIProvider');
  return ctx;
}
