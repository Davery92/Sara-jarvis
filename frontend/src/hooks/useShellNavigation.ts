import { useCallback, useEffect, useState } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { APP_CONFIG } from '../config'
import { pathForView, resolveViewAlias, viewForPath } from '../navigation/views'
import type { AppView } from '../navigation/views'

interface UseShellNavigationOptions {
  locationPathname: string
  navigate: NavigateFunction
}

export function useShellNavigation({
  locationPathname,
  navigate,
}: UseShellNavigationOptions) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const view = viewForPath(locationPathname)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        e.stopPropagation()
        setCommandPaletteOpen((prev) => !prev)
      }
    }

    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [])

  const openWorkspaceCanvas = useCallback(() => {
    window.open(APP_CONFIG.workbenchUrl, '_blank', 'noopener,noreferrer')
  }, [])

  const navigateToView = useCallback((nextView: string, closeMobileMenu = false) => {
    const resolved = resolveViewAlias(nextView)
    if (!resolved) return

    if (closeMobileMenu) {
      setIsMobileMenuOpen(false)
    }

    if (resolved === 'workspace') {
      openWorkspaceCanvas()
      return
    }

    const targetPath = pathForView(resolved)
    if (locationPathname !== targetPath) {
      navigate(targetPath, { replace: resolved === 'login' })
    }
  }, [locationPathname, navigate, openWorkspaceCanvas])

  useEffect(() => {
    const handleNavigate = (e: CustomEvent<{ view: string }>) => {
      if (e.detail?.view) {
        navigateToView(e.detail.view)
      }
    }

    window.addEventListener('navigate', handleNavigate as EventListener)
    return () => window.removeEventListener('navigate', handleNavigate as EventListener)
  }, [navigateToView])

  return {
    view,
    isMobileMenuOpen,
    setIsMobileMenuOpen,
    commandPaletteOpen,
    setCommandPaletteOpen,
    openWorkspaceCanvas,
    navigateToView,
  }
}
