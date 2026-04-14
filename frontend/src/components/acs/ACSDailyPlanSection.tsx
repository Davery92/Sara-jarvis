import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { APP_CONFIG } from '../../config'

export default function ACSDailyPlanSection() {
  const [plan, setPlan] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchPlan = useCallback(async () => {
    try {
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/acs/snapshot`, { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setPlan(data.daily_plan || null)
        setError(null)
      } else {
        setError('Failed to load plan')
      }
    } catch {
      setError('Failed to load plan')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPlan()
  }, [fetchPlan])

  if (loading) return <div className="text-gray-400 p-4">Loading...</div>
  if (error) return <div className="text-red-400 p-4">{error}</div>

  if (!plan) {
    return (
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-8 text-center">
        <p className="text-gray-400">No plan generated yet.</p>
        <p className="text-gray-500 text-sm mt-1">The ACS will generate a daily plan during its next session.</p>
      </div>
    )
  }

  return (
    <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-6">
      <h2 className="text-lg font-semibold text-white mb-4">Today's Plan</h2>
      <div className="prose prose-invert prose-sm max-w-none prose-headings:text-gray-200 prose-headings:mt-4 prose-headings:mb-2 prose-p:text-gray-300 prose-p:my-1 prose-strong:text-gray-200 prose-li:text-gray-300 prose-li:my-0.5">
        <ReactMarkdown>{plan}</ReactMarkdown>
      </div>
    </div>
  )
}
