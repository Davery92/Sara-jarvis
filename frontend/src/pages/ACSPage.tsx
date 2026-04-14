import { useState, Component, type ReactNode } from 'react'
import ACSStatusSection from '../components/acs/ACSStatusSection'
import ACSDailyPlanSection from '../components/acs/ACSDailyPlanSection'
import ACSInterestGraphSection from '../components/acs/ACSInterestGraphSection'
import ACSCuriositySection from '../components/acs/ACSCuriositySection'
import ACSShowDavidSection from '../components/acs/ACSShowDavidSection'
import ACSDirectivesSection from '../components/acs/ACSDirectivesSection'
import ACSSessionHistorySection from '../components/acs/ACSSessionHistorySection'
import ACSSelfModelSection from '../components/acs/ACSSelfModelSection'

class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div className="bg-red-900/20 border border-red-900/30 rounded-lg p-4">
          <p className="text-red-400 text-sm font-medium">Failed to load {this.props.fallback || 'section'}</p>
          <p className="text-red-400/60 text-xs mt-1">{this.state.error.message}</p>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-2 text-xs text-indigo-400 hover:text-indigo-300"
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

const TABS = [
  { key: 'status', label: 'Status' },
  { key: 'plan', label: 'Plan' },
  { key: 'interests', label: 'Interests' },
  { key: 'curiosity', label: 'Curiosity' },
  { key: 'show-david', label: 'Show David' },
  { key: 'directives', label: 'Directives' },
  { key: 'sessions', label: 'Sessions' },
  { key: 'self-model', label: 'Self-Model' },
] as const

type TabKey = typeof TABS[number]['key']

export default function ACSPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('status')

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-bold text-white mb-6">Autonomous Cognition System</h1>

      <div className="flex gap-1 mb-6 overflow-x-auto pb-1">
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap ${
              activeTab === tab.key
                ? 'bg-gray-800 text-white border-b-2 border-indigo-500'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div>
        <ErrorBoundary fallback="status" key={activeTab === 'status' ? 'status' : undefined}>
          {activeTab === 'status' && <ACSStatusSection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="plan" key={activeTab === 'plan' ? 'plan' : undefined}>
          {activeTab === 'plan' && <ACSDailyPlanSection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="interests" key={activeTab === 'interests' ? 'interests' : undefined}>
          {activeTab === 'interests' && <ACSInterestGraphSection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="curiosity" key={activeTab === 'curiosity' ? 'curiosity' : undefined}>
          {activeTab === 'curiosity' && <ACSCuriositySection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="show david" key={activeTab === 'show-david' ? 'show-david' : undefined}>
          {activeTab === 'show-david' && <ACSShowDavidSection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="directives" key={activeTab === 'directives' ? 'directives' : undefined}>
          {activeTab === 'directives' && <ACSDirectivesSection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="sessions" key={activeTab === 'sessions' ? 'sessions' : undefined}>
          {activeTab === 'sessions' && <ACSSessionHistorySection />}
        </ErrorBoundary>
        <ErrorBoundary fallback="self-model" key={activeTab === 'self-model' ? 'self-model' : undefined}>
          {activeTab === 'self-model' && <ACSSelfModelSection />}
        </ErrorBoundary>
      </div>
    </div>
  )
}
