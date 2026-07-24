import { Suspense, lazy } from 'react'
import TabbedGroupView from '../components/shell/TabbedGroupView'

// SINGULAR_SARA_MASTER_PLAN §U0/§U6 — "Work: projects, intents, missions,
// agent work, automations, standing orders, and machines." Reuses the
// existing page components unmodified.
const ProjectSection = lazy(() => import('../components/projects/ProjectSection'))
const AutomationsView = lazy(() => import('../components/AutomationsView'))
const MachinesDashboard = lazy(() => import('../components/machines/MachinesDashboard'))

function Loading() {
  return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
}

export default function Work() {
  return (
    <TabbedGroupView
      tabs={[
        { key: 'projects', label: 'Projects', icon: 'work', content: <Suspense fallback={<Loading />}><ProjectSection /></Suspense> },
        { key: 'automations', label: 'Agent Tasks', icon: 'bolt', content: <Suspense fallback={<Loading />}><AutomationsView /></Suspense> },
        { key: 'machines', label: 'Machines', icon: 'dns', content: <Suspense fallback={<Loading />}><MachinesDashboard /></Suspense> },
      ]}
    />
  )
}
