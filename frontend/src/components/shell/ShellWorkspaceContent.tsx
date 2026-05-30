import React, { Suspense, lazy, useEffect, useState } from 'react'
import type { AppView } from '../../navigation/views'
import DashboardHomeView from './DashboardHomeView'
import DocumentsWorkspaceView from './DocumentsWorkspaceView'
import InboxWorkspaceView from './InboxWorkspaceView'
import WorkspaceCanvasView from './WorkspaceCanvasView'

const loadChatInterface = () => import('../ChatInterface')
const loadNotesPage = () => import('../../pages/Notes')
const loadCalendarView = () => import('../CalendarView')
const loadTasksView = () => import('../TasksView')
const loadSettings = () => import('../../pages/Settings')
const loadFitnessSection = () => import('../fitness/FitnessSection')
const loadRecipesSection = () => import('../fitness/RecipesSection')
const loadLearningSection = () => import('../learning/LearningSection')
const loadProjectSection = () => import('../projects/ProjectSection')
const loadPrivacyDashboard = async () => {
  const module = await import('../privacy/PrivacyDashboard')
  return { default: module.PrivacyDashboard }
}
const loadMorningBrief = () => import('../MorningBrief')
const loadOrchestratorLab = () => import('../OrchestratorLab')
const loadSystemStatus = () => import('../../pages/SystemStatus')
const loadACSPage = () => import('../../pages/ACSPage')
const loadSensoryMonitor = () => import('../SensoryMonitor')
const loadEmailPage = () => import('../EmailPage')
const loadPersonalKnowledge = () => import('../PersonalKnowledge')
const loadAutomationsView = () => import('../AutomationsView')

const ChatInterface = lazy(loadChatInterface)
const NotesPage = lazy(loadNotesPage)
const CalendarView = lazy(loadCalendarView)
const TasksView = lazy(loadTasksView)
const Settings = lazy(loadSettings)
const FitnessSection = lazy(loadFitnessSection)
const RecipesSection = lazy(loadRecipesSection)
const LearningSection = lazy(loadLearningSection)
const ProjectSection = lazy(loadProjectSection)
const PrivacyDashboard = lazy(loadPrivacyDashboard)
const MorningBrief = lazy(loadMorningBrief)
const OrchestratorLab = lazy(loadOrchestratorLab)
const SystemStatus = lazy(loadSystemStatus)
const ACSPage = lazy(loadACSPage)
const SensoryMonitor = lazy(loadSensoryMonitor)
const EmailPage = lazy(loadEmailPage)
const PersonalKnowledge = lazy(loadPersonalKnowledge)
const AutomationsView = lazy(loadAutomationsView)

export function preloadPrimaryShellModules() {
  void loadChatInterface()
  void loadCalendarView()
  void loadEmailPage()
  void loadAutomationsView()
  void loadNotesPage()
}

function ViewLoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex-1 min-h-0 flex items-center justify-center">
      <div className="rounded-md border border-card bg-card px-4 py-3 text-sm text-gray-400">
        {label}
      </div>
    </div>
  )
}

interface ShellWorkspaceContentProps {
  view: AppView
  onNavigate: (nextView: AppView, closeMobileMenu?: boolean) => void
  greeting: string
  attentionItems: any[]
  attentionUnreadCount: number
  missions: any[]
  reminders: any[]
  timers: any[]
  calendarEvents: any[]
  weather: any
  weatherEmoji: Record<string, string>
  contentInboxStats: any
  missionAwaitingCount: number
  runningMissionCount: number
  morningBrief: any
  morningBriefLoading: boolean
  briefAudioPlaying: boolean
  briefAudioRef: React.RefObject<HTMLAudioElement>
  onPlayBriefAudio: () => void
  onBriefAudioEnded: () => void
  onBriefAudioPaused: () => void
  onBriefAudioError: () => void
  onReviewAttentionInbox: () => void
  currentTime: Date
  journalEntries: any[]
  expandedJournalEntries: Set<string>
  onToggleJournalEntry: (entryKey: string) => void
  emotionEmoji: Record<string, string>
  saraStatus: any
  connectedDevices: any[]
  standingOrders: any[]
  formatRelativeTime: (value: any) => string
  chatMessages: any[]
  setChatMessages: React.Dispatch<React.SetStateAction<any[]>>
  loading: boolean
  onClearChat: () => void
  message: string
  setMessage: React.Dispatch<React.SetStateAction<string>>
  abortControllerRef: React.MutableRefObject<any>
  inboxUnreadCount: number
  standingOrdersCount: number
  onChatQuickAction: (actionId: 'inbox_attention' | 'missions' | 'standing_orders') => void
  workbenchUrl: string
  onOpenCanvas: () => void
  onBackToChat: () => void
  selectedFile: File | null
  uploading: boolean
  documents: any[]
  editingDocumentId: any
  editingDocumentTitle: string
  onSelectFile: React.Dispatch<React.SetStateAction<File | null>>
  onUploadDocument: (file: File) => void
  onEditDocumentTitleChange: React.Dispatch<React.SetStateAction<string>>
  onStartEditDocumentTitle: (...args: any[]) => void
  onUpdateDocumentTitle: (...args: any[]) => void
  onCancelEditDocumentTitle: () => void
  onDownloadDocument: (...args: any[]) => void
  onDeleteDocument: (...args: any[]) => void
  onToast: (message: string, type?: string) => void
  onOrchestratorBack: () => void
  inboxTab: 'attention' | 'content'
  onSelectInboxTab: React.Dispatch<React.SetStateAction<'attention' | 'content'>>
  onOpenContentChat: (inboxItemId: string, title: string) => void
  onOpenAttentionChat: (prompt: string) => void
  onChatAboutNote: (title: string, content: string) => void
  onNavigateToWorkspace?: (noteId: string) => void
}

const renderDeferredView = (label: string, content: React.ReactNode) => (
  <Suspense fallback={<ViewLoadingState label={label} />}>
    {content}
  </Suspense>
)

export default function ShellWorkspaceContent({
  view,
  onNavigate,
  greeting,
  attentionItems,
  attentionUnreadCount,
  missions,
  reminders,
  timers,
  calendarEvents,
  weather,
  weatherEmoji,
  contentInboxStats,
  missionAwaitingCount,
  runningMissionCount,
  morningBrief,
  morningBriefLoading,
  briefAudioPlaying,
  briefAudioRef,
  onPlayBriefAudio,
  onBriefAudioEnded,
  onBriefAudioPaused,
  onBriefAudioError,
  onReviewAttentionInbox,
  currentTime,
  journalEntries,
  expandedJournalEntries,
  onToggleJournalEntry,
  emotionEmoji,
  saraStatus,
  connectedDevices,
  standingOrders,
  formatRelativeTime,
  chatMessages,
  setChatMessages,
  loading,
  onClearChat,
  message,
  setMessage,
  abortControllerRef,
  inboxUnreadCount,
  standingOrdersCount,
  onChatQuickAction,
  workbenchUrl,
  onOpenCanvas,
  onBackToChat,
  selectedFile,
  uploading,
  documents,
  editingDocumentId,
  editingDocumentTitle,
  onSelectFile,
  onUploadDocument,
  onEditDocumentTitleChange,
  onStartEditDocumentTitle,
  onUpdateDocumentTitle,
  onCancelEditDocumentTitle,
  onDownloadDocument,
  onDeleteDocument,
  onToast,
  onOrchestratorBack,
  inboxTab,
  onSelectInboxTab,
  onOpenContentChat,
  onOpenAttentionChat,
  onChatAboutNote,
  onNavigateToWorkspace,
}: ShellWorkspaceContentProps) {
  const [mountedViews, setMountedViews] = useState<AppView[]>(() => [view])

  useEffect(() => {
    setMountedViews((prev) => (prev.includes(view) ? prev : [...prev, view]))
  }, [view])

  const renderView = (targetView: AppView) => {
  if (targetView === 'dashboard') {
    return (
      <DashboardHomeView
        attentionItems={attentionItems}
        attentionUnreadCount={attentionUnreadCount}
        missions={missions}
        reminders={reminders}
        timers={timers}
        calendarEvents={calendarEvents}
        onNavigate={onNavigate}
        greeting={greeting}
        weather={weather}
        weatherEmoji={weatherEmoji}
        contentInboxStats={contentInboxStats}
        missionAwaitingCount={missionAwaitingCount}
        runningMissionCount={runningMissionCount}
        morningBrief={morningBrief}
        morningBriefLoading={morningBriefLoading}
        briefAudioPlaying={briefAudioPlaying}
        briefAudioRef={briefAudioRef}
        onPlayBriefAudio={onPlayBriefAudio}
        onBriefAudioEnded={onBriefAudioEnded}
        onBriefAudioPaused={onBriefAudioPaused}
        onBriefAudioError={onBriefAudioError}
        onReviewAttentionInbox={onReviewAttentionInbox}
        currentTime={currentTime}
        journalEntries={journalEntries}
        expandedJournalEntries={expandedJournalEntries}
        onToggleJournalEntry={onToggleJournalEntry}
        emotionEmoji={emotionEmoji}
        saraStatus={saraStatus}
        connectedDevices={connectedDevices}
        standingOrders={standingOrders}
        formatRelativeTime={formatRelativeTime}
      />
    )
  }

  if (targetView === 'chat') {
    return (
      <div className="flex-1 min-h-0 flex flex-col">
        <div className="flex-1 min-h-0">
          {renderDeferredView('Loading chat…', (
            <ChatInterface
              messages={chatMessages}
              setMessages={setChatMessages}
              loading={loading}
              onSendMessage={null}
              onClearChat={onClearChat}
              message={message}
              setMessage={setMessage}
              abortControllerRef={abortControllerRef}
              quickActionContext={{
                inboxUnreadCount,
                attentionUnreadCount,
                missionAwaitingCount,
                runningMissionCount,
                standingOrdersCount,
              }}
              onQuickAction={onChatQuickAction}
            />
          ))}
        </div>
      </div>
    )
  }

  if (targetView === 'notes') {
    return (
      <div className="flex-1 min-h-0 overflow-y-auto">
        {renderDeferredView('Loading notes…', <NotesPage onChatAboutNote={onChatAboutNote} />)}
      </div>
    )
  }

  if (targetView === 'workspace') {
    return (
      <WorkspaceCanvasView
        workbenchUrl={workbenchUrl}
        onOpenCanvas={onOpenCanvas}
        onBackToChat={onBackToChat}
      />
    )
  }

  if (targetView === 'documents') {
    return (
      <DocumentsWorkspaceView
        selectedFile={selectedFile}
        uploading={uploading}
        documents={documents}
        editingDocumentId={editingDocumentId}
        editingDocumentTitle={editingDocumentTitle}
        onSelectFile={onSelectFile}
        onUploadDocument={onUploadDocument}
        onEditDocumentTitleChange={onEditDocumentTitleChange}
        onStartEditDocumentTitle={onStartEditDocumentTitle}
        onUpdateDocumentTitle={onUpdateDocumentTitle}
        onCancelEditDocumentTitle={onCancelEditDocumentTitle}
        onDownloadDocument={onDownloadDocument}
        onDeleteDocument={onDeleteDocument}
      />
    )
  }

  if (targetView === 'tasks') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading tasks…', <TasksView />)}
      </div>
    )
  }

  if (targetView === 'calendar') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading calendar…', <CalendarView />)}
      </div>
    )
  }

  if (targetView === 'fitness') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading fitness…', <FitnessSection />)}
      </div>
    )
  }

  if (targetView === 'learn') {
    return (
      <div className="flex-1 min-h-0">
        {renderDeferredView('Loading learning…', <LearningSection />)}
      </div>
    )
  }

  if (targetView === 'projects') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading projects…', <ProjectSection />)}
      </div>
    )
  }

  if (targetView === 'recipes') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading recipes…', <RecipesSection />)}
      </div>
    )
  }

  if (targetView === 'privacy-dashboard') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0 max-w-4xl mx-auto">
        {renderDeferredView('Loading privacy dashboard…', (
          <PrivacyDashboard
            onToast={(message, type) => {
              onToast(message, type || 'info')
            }}
          />
        ))}
      </div>
    )
  }

  if (targetView === 'settings') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0 space-y-6">
        {renderDeferredView('Loading settings…', <Settings />)}
      </div>
    )
  }

  if (targetView === 'automations') {
    return (
      <div className="flex-1 min-h-0">
        {renderDeferredView('Loading automations…', <AutomationsView />)}
      </div>
    )
  }

  if (targetView === 'orchestrator-lab') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading lab…', <OrchestratorLab onBack={onOrchestratorBack} />)}
      </div>
    )
  }

  if (targetView === 'system-status') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading system status…', <SystemStatus />)}
      </div>
    )
  }

  if (targetView === 'acs') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading ACS…', <ACSPage />)}
      </div>
    )
  }

  if (targetView === 'briefings') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading briefings…', <MorningBrief />)}
      </div>
    )
  }

  if (targetView === 'sensory-monitor') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading sensory monitor…', <SensoryMonitor />)}
      </div>
    )
  }


  if (targetView === 'knowledge') {
    return (
      <div className="flex-1 min-h-0">
        {renderDeferredView('Loading knowledge…', <PersonalKnowledge />)}
      </div>
    )
  }

  if (targetView === 'email') {
    return (
      <div className="flex-1 overflow-y-auto min-h-0">
        {renderDeferredView('Loading email…', <EmailPage />)}
      </div>
    )
  }

  if (targetView === 'inbox') {
    return (
      <InboxWorkspaceView
        inboxUnreadCount={inboxUnreadCount}
        inboxTab={inboxTab}
        contentInboxStats={contentInboxStats}
        attentionUnreadCount={attentionUnreadCount}
        onSelectInboxTab={onSelectInboxTab}
        onOpenContentChat={onOpenContentChat}
        onOpenAttentionChat={onOpenAttentionChat}
        onOpenNote={onNavigateToWorkspace}
      />
    )
  }

  return null
  }

  return (
    <div className="relative flex-1 min-h-0">
      {mountedViews.map((mountedView) => {
        const isActive = mountedView === view

        return (
          <section
            key={mountedView}
            data-shell-active-scroll={isActive ? 'true' : undefined}
            className={isActive ? 'flex h-full min-h-0 flex-col' : 'hidden'}
          >
            {renderView(mountedView)}
          </section>
        )
      })}
    </div>
  )
}
