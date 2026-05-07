import ACSMindSection from '../components/acs/ACSMindSection'
import InterestsPanel from '../components/acs/InterestsPanel'
import UserToolsPanel from '../components/acs/UserToolsPanel'

/**
 * ACS page — direct view of Sara's daemon.
 *
 * Mind section: liveness, focus, queue, activity.
 * Interests: what she's been gravitating toward; David can prune.
 * Tools: her self-authored toolkit; David approves new tools and can disable.
 *
 * The legacy v1 tabs (Status / Plan / Curiosity / Show David / Directives /
 * Sessions / Deliverables / Self-Model) are gone — those read from v1 ACS
 * tables that the new daemon doesn't write to anymore.
 */
export default function ACSPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6 lg:px-8 space-y-4">
      <ACSMindSection />
      <InterestsPanel />
      <UserToolsPanel />
    </div>
  )
}
