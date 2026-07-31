import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { APP_CONFIG } from './config'
import { AppView, pathForView } from './navigation/views'
import { useActivityMonitor } from './hooks/useActivityMonitor'
import { useDashboardWorkspace } from './hooks/useDashboardWorkspace'
import { useDocumentWorkspace } from './hooks/useDocumentWorkspace'
import { useShellNavigation } from './hooks/useShellNavigation'
import { useShellAuth } from './hooks/useShellAuth'
import { useTaskEventStream } from './hooks/useTaskEventStream'
import { CommandPalette } from './components/CommandPalette'
import { CaptureModal } from './components/CaptureModal'
import NotificationBanner from './components/NotificationBanner'
import MiniChatOverlay from './components/MiniChatOverlay'
import SaraOverlayHost from './components/overlay/SaraOverlayHost'
// import HealthAlertChat from './components/HealthAlertChat'  // Disabled: health notifications are hard-banned per HEARTBEAT.md
import ConfirmDialog from './components/ConfirmDialog'
import AuthScreen from './components/shell/AuthScreen'
import ShellHeader from './components/shell/ShellHeader'
import ShellNavigation, { type ShellNavItem } from './components/shell/ShellNavigation'
import { EMOTION_EMOJI, formatRelativeTime, getGreeting, WEATHER_EMOJI } from './components/shell/shellDisplay'
import ToastStack from './components/shell/ToastStack'
import ShellWorkspaceContent, { preloadPrimaryShellModules } from './components/shell/ShellWorkspaceContent'

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [message, setMessage] = useState('')
  const [chatMessages, setChatMessages] = useState([])
  const [toasts, setToasts] = useState([])
  const [chatAutoSendToken, setChatAutoSendToken] = useState<number | undefined>(undefined)
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    confirmLabel: string
    tone: 'danger' | 'neutral'
    busy: boolean
    action: null | (() => Promise<void> | void)
  }>({
    isOpen: false,
    title: '',
    message: '',
    confirmLabel: 'Confirm',
    tone: 'danger',
    busy: false,
    action: null,
  })

  // Health alert chat state — DISABLED: health notifications are hard-banned per HEARTBEAT.md
  // const [activeHealthAlert, setActiveHealthAlert] = useState(null)
  // const [dismissedHealthAlertIds, setDismissedHealthAlertIds] = useState(new Set())

  // Ref for scrolling main content to top on view change
  const mainContentRef = useRef<HTMLDivElement>(null)

  // Ref to track and cancel ongoing chat requests
  const abortControllerRef = useRef(null)

  const getInitialChatMessages = useCallback(() => ([{
    role: 'assistant',
    content: `Hello! I'm ${APP_CONFIG.assistantName}, your personal AI assistant. How can I help you today?`,
    timestamp: new Date(),
  }]), [])

  const {
    view,
    isMobileMenuOpen,
    setIsMobileMenuOpen,
    commandPaletteOpen,
    setCommandPaletteOpen,
    captureModalOpen,
    setCaptureModalOpen,
    openWorkspaceCanvas,
    navigateToView,
  } = useShellNavigation({
    locationPathname: location.pathname,
    navigate,
  })

  const {
    isAuthenticated,
    user,
    email,
    setEmail,
    password,
    setPassword,
    isLogin,
    setIsLogin,
    message: authMessage,
    loading: authLoading,
    handleAuth,
    logout,
  } = useShellAuth({
    locationPathname: location.pathname,
    onSessionStart: (nextView, options) => {
      navigateToView(nextView)
      if (options?.resetChat) {
        setChatMessages(getInitialChatMessages())
      }
    },
    onSessionEnd: () => {
      navigateToView('login')
      setChatMessages([])
    },
  })

  // Scroll main content to top on view change
  useEffect(() => {
    const scrollable = mainContentRef.current?.querySelector('[data-shell-active-scroll="true"] .overflow-y-auto')
      || mainContentRef.current?.querySelector('.overflow-y-auto')
    scrollable?.scrollTo(0, 0)
  }, [view])

  useEffect(() => {
    if (!isAuthenticated) return

    const preload = () => {
      preloadPrimaryShellModules()
    }

    if ('requestIdleCallback' in window) {
      const idleId = window.requestIdleCallback(preload, { timeout: 1200 })
      return () => window.cancelIdleCallback(idleId)
    }

    const timeoutId = setTimeout(preload, 300)
    return () => clearTimeout(timeoutId)
  }, [isAuthenticated])

  async function fetchAndDisplayLatestInsight(
    threshold: string,
    _delivery: 'companion' | 'toast' = 'companion',
  ) {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/insights?limit=1`, {
        credentials: 'include',
      })
      if (!response.ok) {
        throw new Error(`Failed to load latest insight: ${response.status}`)
      }

      const data = await response.json()
      const latestInsight = Array.isArray(data)
        ? data[0]
        : data?.insights?.[0] || data?.items?.[0] || data

      if (!latestInsight) {
        showToast(`Sara completed a ${threshold} sweep with new insight(s).`, 'success', true)
        return
      }

      const title = latestInsight.title || 'New insight'
      const message = latestInsight.message || latestInsight.content || latestInsight.summary || ''
      const preview = message ? `${title}: ${message}` : `${title} is ready for review.`
      showToast(preview.slice(0, 180) + (preview.length > 180 ? '...' : ''), 'success', true)
    } catch (error) {
      console.error('Failed to fetch latest insight:', error)
      showToast(`Sara completed a ${threshold} sweep with new insight(s).`, 'success', true)
    }
  }

  // Activity monitoring for autonomous behaviors
  useActivityMonitor({
    thresholds: {
      quickSweep: 25 * 60 * 1000,      // 25 minutes - short idle
      standardSweep: 2.5 * 60 * 60 * 1000, // 2.5 hours - medium idle
      digestSweep: 24 * 60 * 60 * 1000     // 24 hours - long idle
    },
    onThresholdReached: async (threshold, duration) => {
      console.log(`🤖 Sara: ${threshold} triggered after ${Math.round(duration / 60000)} minutes idle`)
      
      try {
        // Call backend autonomous sweep
        const response = await fetch(`${APP_CONFIG.apiUrl}/autonomous/sweep/${threshold}`, {
          method: 'POST',
          credentials: 'include'
        })

        if (response.ok) {
          const result = await response.json()
          console.log(`🤖 Autonomous sweep result:`, result)

          // Only notify if meaningful insights were generated
          if (result.insights_stored > 0 && result.new_insights > 0) {
            await fetchAndDisplayLatestInsight(threshold, 'companion')
          } else {
            console.log(`🤖 Sara: No new insights to share (${result.insights_stored} stored, ${result.new_insights || 0} new)`)
            // Don't show notifications or fallback behaviors when there's nothing new
          }
        } else {
          console.log(`🤖 Sara: Sweep completed but no actionable insights found`)
          // Don't notify on failed sweeps - just log quietly
        }
      } catch (error) {
        console.log(`🤖 Sara: Unable to generate insights at this time`)
        // Don't notify on errors - just log quietly
      }
    },
    onActivityResume: () => {
      console.log('🤖 Sara: Activity resumed, returning to idle')
    },
    enableLogging: true
  })


  // --- Presence heartbeat: reports current view every 30s ---
  useEffect(() => {
    if (!isAuthenticated) return

    const clientId = (() => {
      let id = sessionStorage.getItem('sara_client_id')
      if (!id) {
        id = `web_${Math.random().toString(36).slice(2, 10)}`
        sessionStorage.setItem('sara_client_id', id)
      }
      return id
    })()

    const sendHeartbeat = () => {
      fetch(`${APP_CONFIG.apiUrl}/api/presence/heartbeat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          platform: 'web',
          client_id: clientId,
          current_view: view,
          visible: !document.hidden,
        }),
      }).catch(() => {})
    }

    // Send immediately, then every 30s
    sendHeartbeat()
    const interval = setInterval(sendHeartbeat, 30_000)

    // Also send on tab visibility change
    const onVisibility = () => sendHeartbeat()
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [isAuthenticated, view])

  // --- Task event SSE: smart delivery of background worker results ---
  useTaskEventStream({
    enabled: isAuthenticated,
    onInjectChatMessage: (data) => {
      if (view === 'chat') {
        setChatMessages(prev => [...prev, {
          role: 'assistant',
          content: data.content,
          timestamp: new Date(),
        }])
      } else {
        // User navigated away since backend decided — downgrade to toast
        showToast(data.content.slice(0, 120) + (data.content.length > 120 ? '...' : ''), 'success', true)
      }
    },
    onShowNotification: (data) => {
      showToast(`${data.title}: ${data.message}`, 'success', true)
    },
  })

  // Health alert polling — DISABLED: health notifications are hard-banned per HEARTBEAT.md
  // The old useEffect polled /api/health/insights every 60s and showed popups.
  // Removed to enforce the ban system consistently.

  // Cleanup: cancel any ongoing chat requests when component unmounts
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [])

  const openConfirmDialog = useCallback((config: {
    title: string
    message: string
    confirmLabel?: string
    tone?: 'danger' | 'neutral'
    action: () => Promise<void> | void
  }) => {
    setConfirmDialog({
      isOpen: true,
      title: config.title,
      message: config.message,
      confirmLabel: config.confirmLabel || 'Confirm',
      tone: config.tone || 'danger',
      busy: false,
      action: config.action,
    })
  }, [])

  const closeConfirmDialog = useCallback(() => {
    setConfirmDialog(prev => {
      if (prev.busy) return prev
      return { ...prev, isOpen: false, action: null }
    })
  }, [])

  const confirmDialogAction = useCallback(async () => {
    const action = confirmDialog.action
    if (!action || confirmDialog.busy) return

    setConfirmDialog(prev => ({ ...prev, busy: true }))
    try {
      await action()
      setConfirmDialog(prev => ({ ...prev, isOpen: false, busy: false, action: null }))
    } catch (error) {
      console.error('Confirm action failed:', error)
      setConfirmDialog(prev => ({ ...prev, busy: false }))
    }
  }, [confirmDialog.action, confirmDialog.busy])

  const clearChat = () => {
    setChatMessages(getInitialChatMessages())
  }

  const showToast = useCallback((message, type = 'info', persistent = false, _highlight = false) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    setToasts(prev => {
      // Don't stack duplicates of the same message
      if (prev.some(t => t.message === message)) return prev
      return [...prev.slice(-9), { id, message, type, persistent }]
    })

    // Nothing camps on screen forever — history belongs in the notification
    // indicators, not in a stack covering the page.
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, persistent ? 30000 : 5000)
  }, [])
  
  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  const {
    timers,
    reminders,
    currentTime,
    morningBrief,
    morningBriefLoading,
    weather,
    calendarEvents,
    saraStatus,
    connectedDevices,
    standingOrders,
    journalEntries,
    expandedJournalEntries,
    attentionItems,
    missions,
    briefAudioPlaying,
    setBriefAudioPlaying,
    briefAudioRef,
    playBriefAudio,
    toggleJournalEntry,
    attentionUnreadCount,
    awaitingDecisionCount,
    inboxUnreadCount,
    missionAwaitingCount,
    runningMissionCount,
  } = useDashboardWorkspace({
    isAuthenticated,
    view,
    onShowToast: showToast,
  })

  const {
    documents,
    selectedFile,
    setSelectedFile,
    uploading,
    editingDocumentId,
    editingDocumentTitle,
    setEditingDocumentTitle,
    loadDocuments,
    uploadDocument,
    downloadDocument,
    deleteDocument,
    updateDocumentTitle,
    startEditDocumentTitle,
    cancelEditDocumentTitle,
  } = useDocumentWorkspace({
    onShowToast: showToast,
    onConfirm: openConfirmDialog,
  })

  // Load primary view data when switching views (including URL-driven navigation).
  useEffect(() => {
    if (!isAuthenticated) return

    if (view === 'documents') {
      loadDocuments()
    }
  }, [isAuthenticated, loadDocuments, view])

  const handleWorkspaceNavigation = async (noteId: string) => {
    if (noteId === 'workspace') {
      navigateToView('workspace')
      return
    }

    navigate({
      pathname: pathForView('notes'),
      search: `?id=${encodeURIComponent(noteId)}`,
    })
  }

  const getNavBadgeCount = (navView: AppView): number => {
    if (navView === 'inbox') return inboxUnreadCount
    if (navView === 'dashboard') return awaitingDecisionCount
    return 0
  }

  const handleChatQuickAction = (actionId: 'inbox_attention' | 'missions' | 'standing_orders') => {
    if (actionId === 'inbox_attention') {
      navigateToView('inbox')
      return
    }
    if (actionId === 'missions') {
      navigateToView('dashboard')
      return
    }
    if (actionId === 'standing_orders') {
      setMessage('Review my active standing orders and tell me what is scheduled next.')
    }
  }

  // Primary nav: 6 flagship surfaces (PHENOMENAL_ASSISTANT_PLAN.md Phase 8 —
  // 24 views collapsed to 6 + a More drawer; nothing deleted, only demoted,
  // and the command palette still reaches everything). 'notes' carries the
  // Knowledge label since NotesKnowledgeGarden already covers notes + graph
  // + connections; the raw PKG facts/people browser ('knowledge' view) moves
  // to More to avoid a two-items-named-"Knowledge" collision.
  // SINGULAR_SARA_MASTER_PLAN §U0: primary nav is now the human-purpose IA
  // (Home/Chat/Today/Memory/Life/Work/Studio/Interior/Settings) rather than
  // a subsystem list. Every previously-primary item (Knowledge/notes,
  // Fitness, System, Mind) still works exactly as before — it's reachable
  // both directly (still listed below in "More") and as a tab inside its
  // new grouped page (Memory, Life, Interior) — nothing was deleted or
  // rewritten, only re-organized, per the plan's Definition of Done #10
  // ("old paths are removed after measured parity, not merely hidden").
  const primaryNavItems: ShellNavItem[] = [
    { view: 'dashboard', label: 'Home', icon: 'home' },
    { view: 'chat', label: 'Chat', icon: 'chat' },
    { view: 'inbox', label: 'Today', icon: 'inbox' },
    { view: 'memory', label: 'Memory', icon: 'psychology' },
    { view: 'life', label: 'Life', icon: 'favorite' },
    { view: 'work', label: 'Work', icon: 'work' },
    { view: 'artifacts', label: 'Studio', icon: 'auto_awesome' },
    { view: 'interior', label: 'Interior', icon: 'insights' },
    { view: 'settings', label: 'Settings', icon: 'settings' },
  ]

  // "More" tier first, then the more specialized/introspective "Advanced"
  // tier, then Settings last — same flat array renders both the desktop
  // rail's More popover and the mobile menu's More section, so the order
  // here is the only grouping signal (no nested collapse UI this pass).
  const secondaryNavItems: ShellNavItem[] = [
    // Direct access to individual pages that are now ALSO reached as tabs
    // inside Memory/Life/Work/Interior — kept here, unchanged, so nothing
    // that used to be a direct link becomes harder to reach.
    { view: 'notes', label: 'Notes', icon: 'edit_note' },
    { view: 'calendar', label: 'Calendar', icon: 'calendar_today' },
    { view: 'email', label: 'Email', icon: 'email' },
    { view: 'documents', label: 'Documents', icon: 'description' },
    { view: 'tasks', label: 'Tasks', icon: 'check_circle' },
    { view: 'projects', label: 'Projects', icon: 'work' },
    { view: 'fitness', label: 'Fitness', icon: 'fitness_center' },
    { view: 'recipes', label: 'Recipes', icon: 'restaurant_menu' },
    { view: 'learn', label: 'Learn', icon: 'school' },
    { view: 'briefings', label: 'Briefings', icon: 'wb_sunny' },
    { view: 'workspace', label: 'Canvas', icon: 'grid_view' },
    { view: 'automations', label: 'Agent Tasks', icon: 'bolt' },
    { view: 'knowledge', label: 'Facts & People', icon: 'psychology' },
    { view: 'acs', label: 'ACS', icon: 'smart_toy' },
    { view: 'machines', label: 'Machines', icon: 'dns' },
    { view: 'dial', label: 'The Dial', icon: 'tune' },
    { view: 'privacy-dashboard', label: 'Privacy', icon: 'lock' },
  ]
  // item 2.3 (2026-07-30): System/Mind/System Status/Sensory Monitor/
  // Orchestrator Lab demoted out of the nav registry — pure engineering/
  // diagnostics views, same nature as Interior itself. Routes and
  // components are untouched (nothing deleted), reachable now only via
  // Interior's "Legacy dashboards" advanced disclosure. Machines and ACS
  // stayed — real features David reaches directly.

  const mobileBottomNavItems: ShellNavItem[] = primaryNavItems

  if (!isAuthenticated) {
    return (
      <AuthScreen
        assistantName={APP_CONFIG.assistantName}
        subtitle={APP_CONFIG.ui.subtitle}
        email={email}
        password={password}
        isLogin={isLogin}
        loading={authLoading}
        message={authMessage}
        onEmailChange={setEmail}
        onPasswordChange={setPassword}
        onToggleMode={() => setIsLogin((prev) => !prev)}
        onSubmit={handleAuth}
      />
    )
  }

  return (
    <div className="h-screen overflow-hidden flex flex-col px-4 pb-20 pt-4 text-slate-100 md:px-6 md:pb-4 md:pt-6">
      {/* Command Palette */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={navigateToView}
        currentView={view}
      />
      <CaptureModal
        isOpen={captureModalOpen}
        onClose={() => setCaptureModalOpen(false)}
      />

      <div className="flex flex-col md:flex-row md:space-x-6 flex-1 min-h-0">
        <ShellNavigation
          assistantName={APP_CONFIG.assistantName}
          view={view}
          primaryNavItems={primaryNavItems}
          secondaryNavItems={secondaryNavItems}
          mobileBottomNavItems={mobileBottomNavItems}
          isMobileMenuOpen={isMobileMenuOpen}
          getNavBadgeCount={getNavBadgeCount}
          onNavigate={navigateToView}
          onLogout={logout}
          onSetMobileMenuOpen={setIsMobileMenuOpen}
        />

        {/* Main Content */}
        <main ref={mainContentRef} className="flex-1 min-w-0 flex flex-col min-h-0 overflow-hidden">
          <ShellHeader
            assistantName={APP_CONFIG.assistantName}
            userEmail={user?.email}
            onOpenAutomations={() => navigateToView('automations')}
            onNavigateToWorkspace={handleWorkspaceNavigation}
          />

          <ShellWorkspaceContent
            view={view}
            onNavigate={navigateToView}
            greeting={getGreeting()}
            attentionItems={attentionItems}
            attentionUnreadCount={attentionUnreadCount}
            missions={missions}
            reminders={reminders}
            timers={timers}
            calendarEvents={calendarEvents}
            weather={weather}
            weatherEmoji={WEATHER_EMOJI}
            missionAwaitingCount={missionAwaitingCount}
            runningMissionCount={runningMissionCount}
            morningBrief={morningBrief}
            morningBriefLoading={morningBriefLoading}
            briefAudioPlaying={briefAudioPlaying}
            briefAudioRef={briefAudioRef}
            onPlayBriefAudio={playBriefAudio}
            onBriefAudioEnded={() => setBriefAudioPlaying(false)}
            onBriefAudioPaused={() => setBriefAudioPlaying(false)}
            onBriefAudioError={() => {
              setBriefAudioPlaying(false)
              showToast('Unable to load brief audio.', 'error')
            }}
            onReviewAttentionInbox={() => {
              navigateToView('inbox')
            }}
            currentTime={currentTime}
            journalEntries={journalEntries}
            expandedJournalEntries={expandedJournalEntries}
            onToggleJournalEntry={toggleJournalEntry}
            emotionEmoji={EMOTION_EMOJI}
            saraStatus={saraStatus}
            connectedDevices={connectedDevices}
            standingOrders={standingOrders}
            formatRelativeTime={formatRelativeTime}
            chatMessages={chatMessages}
            setChatMessages={setChatMessages}
            loading={false}
            onClearChat={clearChat}
            message={message}
            setMessage={setMessage}
            abortControllerRef={abortControllerRef}
            inboxUnreadCount={inboxUnreadCount}
            standingOrdersCount={standingOrders.length}
            onChatQuickAction={handleChatQuickAction}
            workbenchUrl={APP_CONFIG.workbenchUrl}
            onOpenCanvas={openWorkspaceCanvas}
            onBackToChat={() => navigateToView('chat')}
            selectedFile={selectedFile}
            uploading={uploading}
            documents={documents}
            editingDocumentId={editingDocumentId}
            editingDocumentTitle={editingDocumentTitle}
            onSelectFile={setSelectedFile}
            onUploadDocument={uploadDocument}
            onEditDocumentTitleChange={setEditingDocumentTitle}
            onStartEditDocumentTitle={startEditDocumentTitle}
            onUpdateDocumentTitle={updateDocumentTitle}
            onCancelEditDocumentTitle={cancelEditDocumentTitle}
            onDownloadDocument={downloadDocument}
            onDeleteDocument={deleteDocument}
            onToast={showToast}
            onOrchestratorBack={() => navigateToView('settings')}
            onOpenAttentionChat={(prompt) => {
              setMessage(prompt)
              navigateToView('chat')
            }}
            onAskSara={(prompt) => {
              setMessage(prompt)
              setChatAutoSendToken(Date.now())
              navigateToView('chat')
            }}
            chatAutoSendToken={chatAutoSendToken}
            onChatAboutNote={(title, content) => {
              const trimmed = (content || '').trim()
              const excerpt = trimmed.length > 600 ? `${trimmed.slice(0, 600)}…` : trimmed
              const noteName = (title || '').trim() || 'this note'
              setMessage(
                excerpt
                  ? `Let's talk about my note "${noteName}":\n\n${excerpt}`
                  : `Let's talk about my note "${noteName}".`
              )
              navigateToView('chat')
            }}
            onNavigateToWorkspace={handleWorkspaceNavigation}
          />
        </main>
      </div>
      
      {/* Background Task Notifications */}
      <NotificationBanner
        onNavigateToWorkspace={handleWorkspaceNavigation}
        onShowToast={(message, type) => {
          const newToast = { id: Date.now().toString(), message, type }
          setToasts(prev => [...prev, newToast])
          setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== newToast.id))
          }, 5000)
        }}
      />

      {/* Mini Chat Overlay for Agent Clarifications */}
      <MiniChatOverlay />

      {/* Jarvis-style overlays summoned from chat ("bring up my morning brief") */}
      <SaraOverlayHost />

      {/* Health Alert Chat Overlay — DISABLED: health notifications are hard-banned per HEARTBEAT.md */}

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmLabel={confirmDialog.confirmLabel}
        tone={confirmDialog.tone}
        busy={confirmDialog.busy}
        onConfirm={confirmDialogAction}
        onCancel={closeConfirmDialog}
      />

      <ToastStack toasts={toasts} onRemoveToast={removeToast} onClearAll={() => setToasts([])} />
    </div>
  )
}

export default App
