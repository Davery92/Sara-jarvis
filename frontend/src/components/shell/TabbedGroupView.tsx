import { useState, type ReactNode } from 'react'

export interface GroupTab {
  key: string
  label: string
  icon?: string
  content: ReactNode
}

/**
 * Shared tab shell for the SINGULAR_SARA_MASTER_PLAN §U0 grouped views
 * (Life, Work, Memory) — each existing page keeps its own component and
 * data-fetching untouched; this only changes how they're reached. Nothing
 * is duplicated or rewritten, so none of the individual pages' behavior
 * changes by being grouped here.
 */
export default function TabbedGroupView({ tabs, initialTab }: { tabs: GroupTab[]; initialTab?: string }) {
  const [active, setActive] = useState(initialTab || tabs[0]?.key)
  const activeTab = tabs.find((t) => t.key === active) || tabs[0]

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-1 px-4 pt-3 border-b border-gray-800 flex-shrink-0 overflow-x-auto scrollbar-hidden">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActive(tab.key)}
            className={[
              'flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-md whitespace-nowrap transition-colors flex-shrink-0',
              activeTab?.key === tab.key
                ? 'bg-gray-800/70 text-white border-b-2 border-teal-400'
                : 'text-gray-400 hover:text-gray-200 border-b-2 border-transparent',
            ].join(' ')}
          >
            {tab.icon && <span className="material-icons text-[16px]">{tab.icon}</span>}
            {tab.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTab?.content}
      </div>
    </div>
  )
}
