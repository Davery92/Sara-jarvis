import { Suspense, lazy } from 'react'
import TabbedGroupView from '../components/shell/TabbedGroupView'

// SINGULAR_SARA_MASTER_PLAN §U0/§U6 — "Life: calendar, communications,
// people, routines, fitness/recovery, food, location, and home." Each tab
// reuses the existing, unmodified page component — this is a navigation
// regrouping, not a rewrite.
const CalendarView = lazy(() => import('../components/CalendarView'))
const EmailPage = lazy(() => import('../components/EmailPage'))
const FitnessSection = lazy(() => import('../components/fitness/FitnessSection'))
const RecipesSection = lazy(() => import('../components/fitness/RecipesSection'))

function Loading() {
  return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
}

export default function Life() {
  return (
    <TabbedGroupView
      tabs={[
        { key: 'calendar', label: 'Calendar', icon: 'calendar_today', content: <Suspense fallback={<Loading />}><CalendarView /></Suspense> },
        { key: 'email', label: 'Email', icon: 'mail', content: <Suspense fallback={<Loading />}><EmailPage /></Suspense> },
        { key: 'fitness', label: 'Fitness', icon: 'fitness_center', content: <Suspense fallback={<Loading />}><FitnessSection /></Suspense> },
        { key: 'recipes', label: 'Recipes', icon: 'restaurant_menu', content: <Suspense fallback={<Loading />}><RecipesSection /></Suspense> },
      ]}
    />
  )
}
