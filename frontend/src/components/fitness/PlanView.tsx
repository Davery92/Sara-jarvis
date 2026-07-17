import React, { useState, useEffect } from 'react'
import { BookOpen, ChevronDown, ChevronRight } from 'lucide-react'
import MarkdownRenderer from '../MarkdownRenderer'
import { APP_CONFIG } from '../../config'

interface PlanSection {
  title: string
  content: string
  level: number
}

function parseSections(markdown: string): PlanSection[] {
  const lines = markdown.split('\n')
  const sections: PlanSection[] = []
  let currentTitle = ''
  let currentLevel = 0
  let currentLines: string[] = []

  for (const line of lines) {
    const h2Match = line.match(/^## (.+)/)
    if (h2Match) {
      if (currentTitle) {
        sections.push({ title: currentTitle, content: currentLines.join('\n').trim(), level: currentLevel })
      }
      currentTitle = h2Match[1]
      currentLevel = 2
      currentLines = []
    } else {
      currentLines.push(line)
    }
  }
  if (currentTitle) {
    sections.push({ title: currentTitle, content: currentLines.join('\n').trim(), level: currentLevel })
  }
  return sections
}

export default function PlanView() {
  const [planMarkdown, setPlanMarkdown] = useState<string | null>(null)
  const [programName, setProgramName] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [expandedSections, setExpandedSections] = useState<Set<number>>(new Set())
  const [viewMode, setViewMode] = useState<'sections' | 'full'>('sections')

  useEffect(() => {
    fetchPlan()
  }, [])

  const fetchPlan = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/programs/active`, {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        if (data.program) {
          setProgramName(data.program.name)
          setPlanMarkdown(data.program.plan_markdown || null)
        }
      }
    } catch (error) {
      console.error('Failed to fetch plan:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const toggleSection = (idx: number) => {
    const next = new Set(expandedSections)
    if (next.has(idx)) next.delete(idx)
    else next.add(idx)
    setExpandedSections(next)
  }

  const expandAll = () => {
    if (!planMarkdown) return
    const sections = parseSections(planMarkdown)
    setExpandedSections(new Set(sections.map((_, i) => i)))
  }

  const collapseAll = () => {
    setExpandedSections(new Set())
  }

  if (isLoading) {
    return (
      <div className="p-6 text-center text-gray-400">
        Loading plan...
      </div>
    )
  }

  if (!planMarkdown) {
    return (
      <div className="p-6 text-center text-gray-400">
        <BookOpen className="w-12 h-12 mx-auto mb-3 opacity-50" />
        <p>No training plan attached to the active program.</p>
        <p className="text-sm mt-1">Ask Sara to create or attach a plan.</p>
      </div>
    )
  }

  const sections = parseSections(planMarkdown)
  // Extract the header (everything before first ## section)
  const headerEnd = planMarkdown.indexOf('\n## ')
  const header = headerEnd > 0 ? planMarkdown.slice(0, headerEnd).trim() : ''

  return (
    <div className="p-4 sm:p-6 max-w-4xl mx-auto">
      {/* Header */}
      {header && (
        <div className="mb-6 text-center">
          <MarkdownRenderer content={header} className="plan-header" />
        </div>
      )}

      {/* View Toggle + Controls */}
      <div className="flex items-center justify-between mb-4 sticky top-0 z-10 bg-gray-900 py-2">
        <div className="flex gap-2">
          <button
            onClick={() => setViewMode('sections')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              viewMode === 'sections' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            Sections
          </button>
          <button
            onClick={() => setViewMode('full')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              viewMode === 'full' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            Full Plan
          </button>
        </div>
        {viewMode === 'sections' && (
          <div className="flex gap-2 text-sm">
            <button onClick={expandAll} className="text-blue-400 hover:text-blue-300">
              Expand all
            </button>
            <span className="text-gray-600">|</span>
            <button onClick={collapseAll} className="text-blue-400 hover:text-blue-300">
              Collapse all
            </button>
          </div>
        )}
      </div>

      {viewMode === 'full' ? (
        <div className="bg-gray-800 rounded-lg p-4 sm:p-6 border border-gray-700">
          <MarkdownRenderer content={planMarkdown} className="prose-fitness" />
        </div>
      ) : (
        <div className="space-y-2">
          {sections.map((section, idx) => {
            const isExpanded = expandedSections.has(idx)
            const isPhase = section.title.startsWith('Phase')
            const isNutrition = section.title.includes('Nutrition')

            let accentColor = 'border-gray-700'
            if (isPhase) accentColor = 'border-blue-500/50'
            else if (isNutrition) accentColor = 'border-green-500/50'

            return (
              <div key={idx} className={`bg-gray-800 rounded-lg border ${accentColor} overflow-hidden`}>
                <button
                  onClick={() => toggleSection(idx)}
                  className="w-full p-4 flex items-center justify-between text-left hover:bg-gray-750 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    {isExpanded ? (
                      <ChevronDown className="w-5 h-5 text-gray-400 flex-shrink-0" />
                    ) : (
                      <ChevronRight className="w-5 h-5 text-gray-400 flex-shrink-0" />
                    )}
                    <span className="font-semibold text-base">{section.title}</span>
                  </div>
                </button>
                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-gray-700">
                    <div className="pt-4">
                      <MarkdownRenderer content={section.content} className="prose-fitness" />
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
