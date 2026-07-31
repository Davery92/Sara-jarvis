import React from 'react'
import { AppView } from '../../navigation/views'

export interface ShellNavItem {
  view: AppView
  label: string
  icon: string
}

interface ShellNavigationProps {
  assistantName: string
  view: AppView
  primaryNavItems: ShellNavItem[]
  secondaryNavItems: ShellNavItem[]
  mobileBottomNavItems: ShellNavItem[]
  isMobileMenuOpen: boolean
  getNavBadgeCount: (view: AppView) => number
  onNavigate: (view: AppView, closeMobileMenu?: boolean) => void
  onLogout: () => void
  onSetMobileMenuOpen: (open: boolean) => void
}

const ShellNavigation: React.FC<ShellNavigationProps> = ({
  assistantName,
  view,
  primaryNavItems,
  secondaryNavItems,
  mobileBottomNavItems,
  isMobileMenuOpen,
  getNavBadgeCount,
  onNavigate,
  onLogout,
  onSetMobileMenuOpen,
}) => {
  const navDescriptions: Partial<Record<AppView, string>> = {
    dashboard: 'Home and overview',
    chat: 'Talk with Sara',
    inbox: 'Today’s priorities',
    calendar: 'Schedule and reminders',
    email: 'Messages to triage',
    documents: 'Files and uploads',
    learn: 'Study and memory',
    projects: 'Plans and outcomes',
    recipes: 'Meals and kitchen',
    briefings: 'Daily brief',
    fitness: 'Training and recovery',
    acs: 'Sara’s mind',
    notes: 'Notes, graph, connections',
    knowledge: 'Facts and people',
    automations: 'Background work',
    settings: 'System controls',
    'orchestrator-lab': 'Automation lab',
    'privacy-dashboard': 'Privacy and security',
    workspace: 'Canvas workbench',
    tasks: 'Daily checklist',
  }

  const renderBadge = (count: number) =>
    count > 0 ? (
      <span className="rounded-full border border-teal-400/20 bg-teal-400/12 px-2 py-1 text-[11px] font-semibold text-teal-200">
        {count > 99 ? '99+' : count}
      </span>
    ) : null

  const renderRailButton = (item: ShellNavItem) => {
    const isActive = view === item.view
    const badgeCount = getNavBadgeCount(item.view)

    return (
      <button
        key={item.view}
        onClick={() => onNavigate(item.view)}
        className={[
          'group relative flex h-11 w-11 items-center justify-center rounded-xl transition',
          isActive
            ? 'bg-teal-400/12 text-teal-200'
            : 'text-slate-500 hover:bg-white/[0.05] hover:text-slate-200',
        ].join(' ')}
        aria-label={item.label}
        aria-current={isActive ? 'page' : undefined}
      >
        <span className="material-icons text-[20px]">{item.icon}</span>
        {badgeCount > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-teal-400/90 px-1 text-[10px] font-semibold leading-none text-slate-950">
            {badgeCount > 9 ? '9+' : badgeCount}
          </span>
        )}
        <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 hidden -translate-y-1/2 whitespace-nowrap rounded-lg border border-white/10 bg-[#0d1828] px-2.5 py-1.5 text-xs font-medium text-slate-200 shadow-xl group-hover:block">
          {item.label}
        </span>
      </button>
    )
  }

  const renderNavButton = (item: ShellNavItem, options?: { mobile?: boolean; closeMenu?: boolean }) => {
    const isActive = view === item.view
    const badgeCount = getNavBadgeCount(item.view)
    const mobile = options?.mobile ?? false

    return (
      <button
        key={item.view}
        onClick={() => onNavigate(item.view, options?.closeMenu)}
        className={[
          'group flex items-center gap-3 rounded-2xl px-3 py-3 text-left transition',
          mobile ? 'w-full' : 'w-full',
          isActive
            ? 'bg-teal-400/10 text-white ring-1 ring-teal-300/25 shadow-[0_12px_30px_rgba(13,148,136,0.14)]'
            : 'text-slate-300 hover:bg-white/[0.04] hover:text-white',
        ].join(' ')}
      >
        <span
          className={[
            'flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl transition',
            isActive
              ? 'bg-teal-300/14 text-teal-100'
              : 'bg-white/[0.04] text-slate-400 group-hover:text-slate-100',
          ].join(' ')}
        >
          <span className="material-icons text-[20px]">{item.icon}</span>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{item.label}</span>
          <span
            className={[
              'mt-1 text-xs text-slate-500 transition group-hover:text-slate-400',
              isActive || mobile ? 'block' : 'hidden',
            ].join(' ')}
          >
            {navDescriptions[item.view] || 'Open workspace'}
          </span>
        </span>
        {renderBadge(badgeCount)}
      </button>
    )
  }

  return (
    <>
      <div className="assistant-panel md:hidden mb-4 flex items-center justify-between rounded-2xl px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-md border border-white/12 bg-white text-lg font-bold text-slate-950">
            S
          </div>
          <div>
            <div className="assistant-kicker mb-2">Assistant Workspace</div>
            <h1 className="font-display text-xl font-semibold text-white">{assistantName}</h1>
          </div>
        </div>
        <button
          onClick={() => onSetMobileMenuOpen(!isMobileMenuOpen)}
          className="tap-target rounded-md border border-white/8 bg-white/[0.03] px-3 text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
        >
          <span className="material-icons text-[22px]">{isMobileMenuOpen ? 'close' : 'menu'}</span>
        </button>
      </div>

      {isMobileMenuOpen && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/72 backdrop-blur-sm"
          onClick={() => onSetMobileMenuOpen(false)}
        >
          <div
            className="assistant-panel ml-auto flex h-full w-full max-w-sm flex-col overflow-hidden rounded-none border-l border-white/8 p-4"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="assistant-panel-soft mb-4 rounded-2xl p-4">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-md border border-white/12 bg-white text-lg font-bold text-slate-950">
                    S
                  </div>
                  <div>
                    <div className="assistant-kicker mb-2">Now Open</div>
                    <p className="font-display text-lg text-white">{assistantName}</p>
                  </div>
                </div>
                <button
                  onClick={() => onSetMobileMenuOpen(false)}
                  className="tap-target rounded-md border border-white/8 bg-white/[0.03] px-3 text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
                >
                  <span className="material-icons text-[20px]">close</span>
                </button>
              </div>
              <p className="text-sm leading-relaxed text-slate-400">
                Move between home, conversation, and assistant activity without dropping into the older tool-heavy layout.
              </p>
            </div>

            <nav className="flex-1 space-y-5 overflow-y-auto pr-1">
              <div>
                <p className="assistant-kicker px-1">Primary</p>
                <div className="mt-3 space-y-2">
                  {primaryNavItems.map((item) => renderNavButton(item, { mobile: true, closeMenu: true }))}
                </div>
              </div>

              {secondaryNavItems.length > 0 && (
                <div className="border-t border-white/8 pt-5">
                  <p className="assistant-kicker px-1">More</p>
                  <div className="mt-3 space-y-2">
                    {secondaryNavItems.map((item) => renderNavButton(item, { mobile: true, closeMenu: true }))}
                  </div>
                </div>
              )}
            </nav>

            <button
              onClick={() => {
                onLogout()
                onSetMobileMenuOpen(false)
              }}
              className="mt-4 flex items-center justify-between rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3 text-slate-300 transition hover:bg-white/[0.06] hover:text-white"
            >
              <span className="flex items-center gap-3">
                <span className="material-icons text-[20px]">logout</span>
                <span className="font-medium">Logout</span>
              </span>
              <span className="material-icons text-[18px] text-slate-500">arrow_forward</span>
            </button>
          </div>
        </div>
      )}

      <aside className="hidden md:flex w-16 flex-col items-center flex-shrink-0 py-2">
        <button
          onClick={() => onNavigate('dashboard')}
          className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-base font-bold text-slate-950 shadow-lg shadow-cyan-950/20 transition hover:scale-105"
          title={assistantName}
          aria-label={`${assistantName} home`}
        >
          S
        </button>

        <nav className="mt-6 flex flex-1 flex-col items-center gap-1">
          {primaryNavItems.map((item) => renderRailButton(item))}

          {secondaryNavItems.length > 0 && (
            <button
              onClick={() => onSetMobileMenuOpen(true)}
              className="flex h-11 w-11 items-center justify-center rounded-xl text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200"
              aria-label="More"
            >
              <span className="material-icons text-[20px]">more_horiz</span>
            </button>
          )}
        </nav>

        <button
          onClick={onLogout}
          className="group relative flex h-11 w-11 items-center justify-center rounded-xl text-slate-500 transition hover:bg-white/[0.05] hover:text-slate-200"
          aria-label="Logout"
        >
          <span className="material-icons text-[20px]">logout</span>
          <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 hidden -translate-y-1/2 whitespace-nowrap rounded-lg border border-white/10 bg-[#0d1828] px-2.5 py-1.5 text-xs font-medium text-slate-200 shadow-xl group-hover:block">
            Logout
          </span>
        </button>
      </aside>

      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-white/8 bg-[#09111ef2] backdrop-blur-xl overflow-x-auto scrollbar-hidden">
        <div className="flex items-center gap-1 px-2 py-2.5" style={{ minWidth: 'fit-content' }}>
          {mobileBottomNavItems.map((item) => (
            <button
              key={item.view}
              onClick={() => onNavigate(item.view)}
              className={[
                'tap-target flex flex-col items-center rounded-md px-3 py-2 flex-shrink-0 transition',
                view === item.view
                  ? 'bg-teal-400/10 text-teal-200'
                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-white',
              ].join(' ')}
            >
              <div className="relative">
                <span className="material-icons text-lg">{item.icon}</span>
                {getNavBadgeCount(item.view) > 0 && (
                  <span className="absolute -top-2 -right-3">{renderBadge(getNavBadgeCount(item.view))}</span>
                )}
              </div>
              <span className="mt-1 text-[11px] whitespace-nowrap">{item.label}</span>
            </button>
          ))}
          <button
            onClick={() => onSetMobileMenuOpen(true)}
            className="tap-target flex flex-col items-center rounded-md px-3 py-2 text-slate-400 transition hover:bg-white/[0.04] hover:text-white flex-shrink-0"
          >
            <span className="material-icons text-lg">more_horiz</span>
            <span className="mt-1 text-[11px] whitespace-nowrap">More</span>
          </button>
        </div>
      </nav>
    </>
  )
}

export default ShellNavigation
