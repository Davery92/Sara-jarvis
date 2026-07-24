import { Suspense, lazy } from 'react'
import TabbedGroupView from '../components/shell/TabbedGroupView'

// SINGULAR_SARA_MASTER_PLAN §U0/§U5 — "Memory: unified search across
// traces... notes, documents, learned preferences, and Sara's operating
// lessons as views of one memory." Reuses the existing page components
// unmodified; the plan's deeper §U5 goal (one search, provenance labeling,
// contradiction review) is a separate, later data-layer change — this is
// the navigation grouping step only.
const NotesPage = lazy(() => import('./Notes'))
const DocumentsPage = lazy(() => import('./Documents'))
const PersonalKnowledge = lazy(() => import('../components/PersonalKnowledge'))
const LearningSection = lazy(() => import('../components/learning/LearningSection'))

function Loading() {
  return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
}

export default function Memory() {
  return (
    <TabbedGroupView
      tabs={[
        { key: 'notes', label: 'Notes', icon: 'edit_note', content: <Suspense fallback={<Loading />}><NotesPage /></Suspense> },
        { key: 'documents', label: 'Documents', icon: 'description', content: <Suspense fallback={<Loading />}><DocumentsPage /></Suspense> },
        { key: 'knowledge', label: 'Facts & People', icon: 'psychology', content: <Suspense fallback={<Loading />}><PersonalKnowledge /></Suspense> },
        { key: 'learn', label: 'Learn', icon: 'school', content: <Suspense fallback={<Loading />}><LearningSection /></Suspense> },
      ]}
    />
  )
}
