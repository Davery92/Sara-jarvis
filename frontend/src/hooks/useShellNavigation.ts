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
  const [captureModalOpen, setCaptureModalOpen] = useState(false)
  const view = viewForPath(locationPathname)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        e.stopPropagation()
        setCommandPaletteOpen((prev) => !prev)
      } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'c') {
        // item 5.2: universal capture's web hotkey — same idea as the iOS
        // share sheet, for whatever's already open in the browser.
        e.preventDefault()
        e.stopPropagation()
        setCaptureModalOpen((prev) => !prev)
      }
    }

    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [])

  const openWorkspaceCanvas = useCallback(() => {
    window.open(APP_CONFIG.workbenchUrl, '_blank', 'noopener,noreferrer')
  }, [])

  const navigateToView = useCallback((
    nextView: string,
    closeMobileMenu = false,
    params?: Record<string, string>,
  ) => {
    const resolved = resolveViewAlias(nextView)
    if (!resolved) return

    if (closeMobileMenu) {
      setIsMobileMenuOpen(false)
    }

    if (resolved === 'workspace') {
      openWorkspaceCanvas()
      return
    }

    const basePath = pathForView(resolved)
    const query = params ? new URLSearchParams(params).toString() : ''
    const targetPath = query ? `${basePath}?${query}` : basePath
    // Always navigate when a query is present (deep-link may target the same
    // view with a different id); otherwise skip redundant same-path pushes.
    if (query || locationPathname !== basePath) {
      navigate(targetPath, { replace: resolved === 'login' })
    }
  }, [locationPathname, navigate, openWorkspaceCanvas])

  useEffect(() => {
    const handleNavigate = (
      e: CustomEvent<{ view: string; params?: Record<string, string> }>,
    ) => {
      if (e.detail?.view) {
        navigateToView(e.detail.view, false, e.detail.params)
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
    captureModalOpen,
    setCaptureModalOpen,
    openWorkspaceCanvas,
    navigateToView,
  }
}
