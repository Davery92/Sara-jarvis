import React, { useEffect, useMemo, useState } from 'react'
import { APP_CONFIG } from '../../config'

interface BlueprintImporterProps {
  isVisible: boolean
  onClose: () => void
  onMaterialized?: (rootTopicId?: string) => void
  onOpenArtifact?: (artifact: any) => void
  parentTopicId?: string | null
  parentTopicTitle?: string | null
  availableTopics?: Array<{
    id: string
    title: string
    parent_id?: string | null
  }>
}

interface BlueprintPreview {
  blueprint?: {
    title?: string
    subtitle?: string | null
    description?: string | null
    estimated_duration_weeks?: number | null
  }
  phases?: Array<{
    index?: number
    title?: string
    modules?: Array<{ code?: string; title?: string }>
  }>
  connections?: Array<unknown>
  metadata?: {
    warnings?: string[]
  }
}

interface StoredBlueprintSummary {
  id: string
  title: string
  subtitle?: string | null
  description?: string | null
  status: string
  import_confidence?: number | null
  source_format?: string
  pace_mode?: string
  materialized_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

interface StoredBlueprintDetail extends StoredBlueprintSummary {
  raw_text?: string | null
  parsed_json?: BlueprintPreview
  meta?: Record<string, unknown>
}

interface BlueprintProgress {
  completed_modules: number
  total_modules: number
  percent_complete: number
  current_phase?: number | null
  current_module_code?: string | null
  current_module_title?: string | null
}

interface GuideGenerationJob {
  id: string
  status: string
  progress: number
  current_step?: string | null
  total_modules?: number
  completed_modules?: number
  artifacts_created?: number
  model?: string | null
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  completed_at?: string | null
}

interface GuideArtifactSummary {
  id: string
  topic_id?: string | null
  artifact_type: string
  title?: string | null
  version?: number
  content?: {
    module_code?: string
    module_title?: string
    generated_at?: string
    model?: string
  }
  created_at?: string | null
  updated_at?: string | null
}

type BlueprintTab = 'import' | 'library'

function getPreviewCounts(payload: BlueprintPreview | null): { phases: number; modules: number; connections: number } {
  const phases = payload?.phases?.length || 0
  const modules = (payload?.phases || []).reduce((acc, phase) => acc + (phase.modules?.length || 0), 0)
  const connections = payload?.connections?.length || 0
  return { phases, modules, connections }
}

export default function BlueprintImporter({
  isVisible,
  onClose,
  onMaterialized,
  onOpenArtifact,
  parentTopicId,
  parentTopicTitle,
  availableTopics = []
}: BlueprintImporterProps) {
  const [activeTab, setActiveTab] = useState<BlueprintTab>('import')
  const [planText, setPlanText] = useState('')
  const [titleOverride, setTitleOverride] = useState('')
  const [sourceFormat, setSourceFormat] = useState<'text' | 'markdown'>('markdown')
  const [parseMode, setParseMode] = useState<'fast' | 'balanced' | 'deep'>('balanced')
  const [paceMode, setPaceMode] = useState<'self_directed' | 'structured'>('self_directed')
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null)
  const [isReadingFile, setIsReadingFile] = useState(false)

  const [isParsing, setIsParsing] = useState(false)
  const [materializingTargetId, setMaterializingTargetId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [blueprintId, setBlueprintId] = useState<string | null>(null)
  const [importConfidence, setImportConfidence] = useState<number | null>(null)
  const [preview, setPreview] = useState<BlueprintPreview | null>(null)

  const [libraryBlueprints, setLibraryBlueprints] = useState<StoredBlueprintSummary[]>([])
  const [isLoadingLibrary, setIsLoadingLibrary] = useState(false)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [selectedLibraryId, setSelectedLibraryId] = useState<string | null>(null)
  const [selectedLibraryDetail, setSelectedLibraryDetail] = useState<StoredBlueprintDetail | null>(null)
  const [selectedLibraryProgress, setSelectedLibraryProgress] = useState<BlueprintProgress | null>(null)
  const [selectedGuideJob, setSelectedGuideJob] = useState<GuideGenerationJob | null>(null)
  const [selectedGuideArtifacts, setSelectedGuideArtifacts] = useState<GuideArtifactSummary[]>([])
  const [guidesBusyTargetId, setGuidesBusyTargetId] = useState<string | null>(null)
  const [nestUnderParentTopic, setNestUnderParentTopic] = useState<boolean>(Boolean(parentTopicId))
  const [selectedParentTopicId, setSelectedParentTopicId] = useState<string>(parentTopicId || '')

  const { phases: phaseCount, modules: moduleCount, connections: connectionCount } = useMemo(
    () => getPreviewCounts(preview),
    [preview]
  )
  const libraryPreview = (selectedLibraryDetail?.parsed_json || null) as BlueprintPreview | null
  const libraryCounts = useMemo(() => getPreviewCounts(libraryPreview), [libraryPreview])
  const warnings = preview?.metadata?.warnings || []
  const orderedTopicOptions = useMemo(() => {
    if (!availableTopics.length) return []

    const byId = new Map(availableTopics.map((topic) => [topic.id, topic]))
    const children = new Map<string | null, Array<{ id: string; title: string; parent_id?: string | null }>>()

    for (const topic of availableTopics) {
      const key = topic.parent_id || null
      const group = children.get(key)
      if (group) {
        group.push(topic)
      } else {
        children.set(key, [topic])
      }
    }

    for (const group of children.values()) {
      group.sort((a, b) => a.title.localeCompare(b.title))
    }

    const ordered: Array<{ id: string; title: string; depth: number }> = []
    const visited = new Set<string>()

    const walk = (topicId: string, depth: number) => {
      if (visited.has(topicId)) return
      visited.add(topicId)
      const node = byId.get(topicId)
      if (!node) return
      ordered.push({ id: node.id, title: node.title, depth })
      const kids = children.get(topicId) || []
      for (const child of kids) {
        walk(child.id, depth + 1)
      }
    }

    const roots = children.get(null) || []
    for (const root of roots) {
      walk(root.id, 0)
    }
    for (const topic of availableTopics) {
      if (!visited.has(topic.id)) {
        walk(topic.id, 0)
      }
    }
    return ordered
  }, [availableTopics])

  const resetState = () => {
    setError(null)
    setLibraryError(null)
    setBlueprintId(null)
    setImportConfidence(null)
    setPreview(null)
  }

  const formatDate = (value?: string | null) => {
    if (!value) return 'N/A'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return 'N/A'
    return parsed.toLocaleDateString()
  }

  const statusBadgeClass = (status?: string) => {
    if (status === 'materialized') return 'bg-green-900/50 text-green-300'
    if (status === 'parsed') return 'bg-blue-900/50 text-blue-300'
    return 'bg-gray-800 text-gray-300'
  }

  const guideStatusBadgeClass = (status?: string) => {
    if (status === 'completed') return 'bg-green-900/50 text-green-300'
    if (status === 'running') return 'bg-blue-900/50 text-blue-300'
    if (status === 'queued') return 'bg-yellow-900/50 text-yellow-300'
    if (status === 'cancelling') return 'bg-orange-900/50 text-orange-300'
    if (status === 'cancelled') return 'bg-gray-700 text-gray-200'
    if (status === 'failed') return 'bg-red-900/50 text-red-300'
    return 'bg-gray-800 text-gray-300'
  }

  const loadGuideArtifacts = async (blueprintId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${blueprintId}/guides`, {
        credentials: 'include'
      })
      if (!response.ok) {
        setSelectedGuideArtifacts([])
        return
      }
      const data = await response.json()
      const guides = Array.isArray(data?.guides) ? (data.guides as GuideArtifactSummary[]) : []
      setSelectedGuideArtifacts(guides)
    } catch {
      setSelectedGuideArtifacts([])
    }
  }

  const loadLatestGuideJob = async (blueprintId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${blueprintId}/guides/jobs?limit=1`, {
        credentials: 'include'
      })
      if (!response.ok) {
        setSelectedGuideJob(null)
        return
      }
      const data = await response.json()
      const jobs = Array.isArray(data?.jobs) ? (data.jobs as GuideGenerationJob[]) : []
      setSelectedGuideJob(jobs[0] || null)
    } catch {
      setSelectedGuideJob(null)
    }
  }

  const loadBlueprintDetail = async (id: string) => {
    const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${id}`, {
      credentials: 'include'
    })
    if (!response.ok) {
      const message = await response.text()
      throw new Error(message || `Failed to load blueprint (${response.status})`)
    }

    const detail = (await response.json()) as StoredBlueprintDetail
    setSelectedLibraryDetail(detail)

    if (detail.status !== 'materialized') {
      setSelectedLibraryProgress(null)
      await Promise.all([loadGuideArtifacts(id), loadLatestGuideJob(id)])
      return
    }

    try {
      const progressResponse = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${id}/progress`, {
        credentials: 'include'
      })
      if (!progressResponse.ok) {
        setSelectedLibraryProgress(null)
        return
      }
      const progress = (await progressResponse.json()) as BlueprintProgress
      setSelectedLibraryProgress(progress)
    } catch {
      setSelectedLibraryProgress(null)
    }
    await Promise.all([loadGuideArtifacts(id), loadLatestGuideJob(id)])
  }

  const loadBlueprintLibrary = async (preferredBlueprintId?: string) => {
    setIsLoadingLibrary(true)
    setLibraryError(null)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints`, {
        credentials: 'include'
      })
      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || `Failed to list blueprints (${response.status})`)
      }

      const data = await response.json()
      const rows = Array.isArray(data?.blueprints) ? (data.blueprints as StoredBlueprintSummary[]) : []
      setLibraryBlueprints(rows)

      const nextId =
        preferredBlueprintId ||
        (selectedLibraryId && rows.some((row) => row.id === selectedLibraryId) ? selectedLibraryId : null) ||
        rows[0]?.id ||
        null

      setSelectedLibraryId(nextId)
      if (nextId) {
        await loadBlueprintDetail(nextId)
      } else {
        setSelectedLibraryDetail(null)
        setSelectedLibraryProgress(null)
        setSelectedGuideJob(null)
        setSelectedGuideArtifacts([])
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load blueprint history'
      setLibraryError(message)
    } finally {
      setIsLoadingLibrary(false)
    }
  }

  useEffect(() => {
    if (!isVisible) return
    void loadBlueprintLibrary()
  }, [isVisible])

  useEffect(() => {
    if (parentTopicId) {
      setNestUnderParentTopic(true)
      setSelectedParentTopicId(parentTopicId)
    } else if (!selectedParentTopicId && availableTopics.length) {
      setSelectedParentTopicId(availableTopics[0].id)
    }
  }, [parentTopicId, availableTopics, selectedParentTopicId])

  const handleParse = async () => {
    if (!planText.trim() || isParsing) return

    setError(null)
    setLibraryError(null)
    setIsParsing(true)
    setBlueprintId(null)
    setPreview(null)
    setImportConfidence(null)

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/parse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          text: planText,
          source_format: sourceFormat,
          parse_mode: parseMode,
          pace_mode: paceMode,
          title_override: titleOverride.trim() || undefined
        })
      })

      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || `Parse failed (${response.status})`)
      }

      const data = await response.json()
      setBlueprintId(data.blueprint_id)
      setImportConfidence(typeof data.import_confidence === 'number' ? data.import_confidence : null)
      setPreview(data.preview || null)
      void loadBlueprintLibrary(data.blueprint_id)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to parse blueprint'
      setError(message)
    } finally {
      setIsParsing(false)
    }
  }

  const handleLoadPlanFile = async (file: File | null) => {
    if (!file) return
    const ext = file.name.split('.').pop()?.toLowerCase() || ''
    const allowed = new Set(['txt', 'md', 'markdown', 'docx'])
    if (!allowed.has(ext)) {
      setError('Unsupported file type. Use .txt, .md, .markdown, or .docx')
      return
    }

    setUploadedFileName(file.name)
    setError(null)
    setIsReadingFile(true)

    try {
      let text = ''
      let detectedSourceFormat: 'text' | 'markdown' = 'text'
      if (ext === 'docx') {
        const arrayBuffer = await file.arrayBuffer()
        const mammoth = await import('mammoth')
        const mammothApi = (mammoth as any).default || mammoth
        if (typeof mammothApi.extractRawText === 'function') {
          const result = await mammothApi.extractRawText({ arrayBuffer })
          text = (result.value || '').trim()
        } else if (typeof mammothApi.convertToHtml === 'function') {
          const result = await mammothApi.convertToHtml({ arrayBuffer })
          const html = String(result.value || '')
          text = html
            .replace(/<br\s*\/?>/gi, '\n')
            .replace(/<\/p>/gi, '\n\n')
            .replace(/<[^>]+>/g, ' ')
            .replace(/\u00a0/g, ' ')
            .replace(/[ \t]+\n/g, '\n')
            .replace(/\n{3,}/g, '\n\n')
            .trim()
        } else {
          throw new Error('DOCX parser unavailable')
        }
      } else {
        text = await file.text()
        detectedSourceFormat = ext === 'md' || ext === 'markdown' ? 'markdown' : 'text'
      }

      if (!text.trim()) {
        setError('No readable text found in file')
        return
      }

      setPlanText(text)
      setSourceFormat(detectedSourceFormat)
      setUploadedFileName(file.name)
      if (!titleOverride.trim()) {
        setTitleOverride(file.name.replace(/\.[^/.]+$/, ''))
      }
      setError(null)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown read error'
      setError(`Failed to read file content: ${message}`)
      setUploadedFileName(null)
    } finally {
      setIsReadingFile(false)
    }
  }

  const materializeBlueprint = async (targetBlueprintId: string, replaceExisting: boolean = false) => {
    if (!targetBlueprintId || materializingTargetId) return

    setError(null)
    setLibraryError(null)
    setMaterializingTargetId(targetBlueprintId)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${targetBlueprintId}/materialize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          mode: 'adaptive',
          create_sources: true,
          create_connections: true,
          create_curriculum: true,
          seed_reviews: true,
          replace_existing: replaceExisting,
          parent_topic_id: (nestUnderParentTopic && selectedParentTopicId) ? selectedParentTopicId : undefined
        })
      })

      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || `Materialization failed (${response.status})`)
      }

      const data = await response.json()
      await loadBlueprintLibrary(targetBlueprintId)
      onMaterialized?.(data.root_topic_id)
      onClose()
      resetState()
      setPlanText('')
      setTitleOverride('')
      setSourceFormat('markdown')
      setUploadedFileName(null)
      setActiveTab('import')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to materialize blueprint'
      if (targetBlueprintId === blueprintId) {
        setError(message)
      } else {
        setLibraryError(message)
      }
    } finally {
      setMaterializingTargetId(null)
    }
  }

  const handleMaterialize = async () => {
    if (!blueprintId) return
    await materializeBlueprint(blueprintId, false)
  }

  const handleSelectLibraryBlueprint = async (id: string) => {
    setSelectedLibraryId(id)
    setLibraryError(null)
    try {
      await loadBlueprintDetail(id)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load blueprint details'
      setLibraryError(message)
    }
  }

  const generateGuidesForBlueprint = async (targetBlueprintId: string) => {
    if (!targetBlueprintId || guidesBusyTargetId) return

    setLibraryError(null)
    setGuidesBusyTargetId(targetBlueprintId)
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/learn/blueprints/${targetBlueprintId}/guides/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          force_regenerate: false,
          num_ctx: 16384
        })
      })

      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || `Guide generation failed (${response.status})`)
      }

      const data = await response.json()
      const jobId = data?.job_id as string | undefined
      if (jobId) {
        const jobResponse = await fetch(
          `${APP_CONFIG.apiUrl}/api/learn/blueprints/${targetBlueprintId}/guides/jobs/${jobId}`,
          { credentials: 'include' }
        )
        if (jobResponse.ok) {
          const job = (await jobResponse.json()) as GuideGenerationJob
          setSelectedGuideJob(job)
        }
      } else {
        await loadLatestGuideJob(targetBlueprintId)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to generate guides'
      setLibraryError(message)
    } finally {
      setGuidesBusyTargetId(null)
    }
  }

  const cancelGuideJob = async (blueprintId: string, jobId: string) => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/learn/blueprints/${blueprintId}/guides/jobs/${jobId}/cancel`,
        {
          method: 'POST',
          credentials: 'include'
        }
      )
      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || `Cancel failed (${response.status})`)
      }
      const data = await response.json()
      if (data?.job) {
        setSelectedGuideJob(data.job as GuideGenerationJob)
      } else {
        await loadLatestGuideJob(blueprintId)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to cancel job'
      setLibraryError(message)
    }
  }

  useEffect(() => {
    if (!selectedLibraryId || !selectedGuideJob) return
    if (!['queued', 'running', 'cancelling'].includes(selectedGuideJob.status)) return

    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `${APP_CONFIG.apiUrl}/api/learn/blueprints/${selectedLibraryId}/guides/jobs/${selectedGuideJob.id}`,
          { credentials: 'include' }
        )
        if (!response.ok) return
        const latest = (await response.json()) as GuideGenerationJob
        setSelectedGuideJob(latest)
        if (latest.status === 'completed') {
          await loadGuideArtifacts(selectedLibraryId)
        }
      } catch {
        // Ignore transient poll failures
      }
    }, 2500)

    return () => window.clearTimeout(timer)
  }, [selectedLibraryId, selectedGuideJob])

  if (!isVisible) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
      <div className="w-full max-w-5xl max-h-[88vh] bg-gray-900 border border-gray-700 rounded-xl overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <span className="material-icons text-teal-400">upload_file</span>
              Import Learning Plan
            </h2>
            <p className="text-sm text-gray-400">
              Paste a premade roadmap and convert it into topics, curriculum, sources, and dependencies.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
          >
            <span className="material-icons">close</span>
          </button>
        </div>

        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTab('import')}
              className={`px-3 py-1.5 rounded-lg text-sm ${activeTab === 'import' ? 'bg-teal-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}`}
            >
              Import
            </button>
            <button
              onClick={() => setActiveTab('library')}
              className={`px-3 py-1.5 rounded-lg text-sm ${activeTab === 'library' ? 'bg-teal-600 text-white' : 'bg-gray-800 text-gray-300 hover:text-white'}`}
            >
              History
            </button>
          </div>
          {activeTab === 'library' && (
            <button
              onClick={() => void loadBlueprintLibrary(selectedLibraryId || undefined)}
              disabled={isLoadingLibrary}
              className="px-3 py-1.5 rounded-lg text-xs bg-gray-800 text-gray-300 hover:text-white disabled:opacity-50"
            >
              {isLoadingLibrary ? 'Refreshing...' : 'Refresh'}
            </button>
          )}
        </div>

        <div className="px-4 py-3 border-b border-gray-800 bg-teal-900/10">
          <div className="bg-teal-900/20 border border-teal-700/40 rounded-lg p-3 space-y-2">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span className="text-teal-200">
                Nest under topic
              </span>
              <input
                type="checkbox"
                checked={nestUnderParentTopic}
                onChange={(e) => setNestUnderParentTopic(e.target.checked)}
                className="w-4 h-4 rounded border-teal-700 bg-gray-800 text-teal-500 focus:ring-teal-500"
              />
            </label>

            {availableTopics.length === 0 ? (
              <p className="text-xs text-teal-200/80">
                No topics available yet. Create a topic first to nest imports.
              </p>
            ) : (
              <select
                value={selectedParentTopicId}
                onChange={(e) => setSelectedParentTopicId(e.target.value)}
                disabled={!nestUnderParentTopic}
                className="w-full bg-gray-800 border border-teal-700/40 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal-500 disabled:opacity-60"
              >
                {orderedTopicOptions.map((topic) => (
                  <option key={topic.id} value={topic.id}>
                    {`${'  '.repeat(Math.min(topic.depth, 6))}${topic.title}`}
                  </option>
                ))}
              </select>
            )}

            {parentTopicTitle && parentTopicId && (
              <p className="text-xs text-teal-200/80">
                Current selected topic: {parentTopicTitle}
              </p>
            )}
          </div>
        </div>

        {activeTab === 'import' && (
          <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-2">
            <div className="border-r border-gray-800 p-4 flex flex-col gap-3 overflow-y-auto">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <input
                  value={titleOverride}
                  onChange={(e) => setTitleOverride(e.target.value)}
                  placeholder="Optional title override"
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-teal-500"
                />
                <select
                  value={parseMode}
                  onChange={(e) => setParseMode(e.target.value as 'fast' | 'balanced' | 'deep')}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-teal-500"
                >
                  <option value="fast">Parse Mode: Fast</option>
                  <option value="balanced">Parse Mode: Balanced</option>
                  <option value="deep">Parse Mode: Deep</option>
                  </select>
              </div>

              <div className="bg-gray-800/70 border border-dashed border-gray-700 rounded-lg p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs text-gray-400">
                    <div className="font-medium text-gray-300">Load plan from file</div>
                    <div>.txt, .md, .markdown, .docx</div>
                  </div>
                  <label className="cursor-pointer px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-xs text-white">
                    Choose File
                    <input
                      type="file"
                      accept=".txt,.md,.markdown,.docx"
                      className="hidden"
                      onChange={(e) => {
                        handleLoadPlanFile(e.target.files?.[0] || null)
                        e.target.value = ''
                      }}
                    />
                  </label>
                </div>
                {uploadedFileName && (
                  <div className="mt-2 text-xs text-teal-300 truncate">
                    {isReadingFile ? `Reading ${uploadedFileName}...` : `Loaded: ${uploadedFileName}`}
                  </div>
                )}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => setPaceMode('self_directed')}
                  className={`px-3 py-1.5 text-sm rounded-lg ${
                    paceMode === 'self_directed' ? 'bg-teal-600 text-white' : 'bg-gray-800 text-gray-300'
                  }`}
                >
                  Self Directed
                </button>
                <button
                  onClick={() => setPaceMode('structured')}
                  className={`px-3 py-1.5 text-sm rounded-lg ${
                    paceMode === 'structured' ? 'bg-teal-600 text-white' : 'bg-gray-800 text-gray-300'
                  }`}
                >
                  Structured
                </button>
              </div>

              <textarea
                value={planText}
                onChange={(e) => setPlanText(e.target.value)}
                placeholder="Paste your full learning plan here..."
                className="w-full min-h-[380px] bg-gray-800 border border-gray-700 rounded-lg px-3 py-3 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-teal-500 resize-y"
              />

              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">
                  {planText.trim().length.toLocaleString()} chars
                </span>
                <button
                  onClick={handleParse}
                  disabled={!planText.trim() || isParsing}
                  className="px-4 py-2 rounded-lg text-sm bg-teal-600 hover:bg-teal-700 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                >
                  {isParsing ? 'Parsing...' : 'Parse Blueprint'}
                </button>
              </div>
            </div>

            <div className="p-4 overflow-y-auto">
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">Preview</h3>

              {!preview && (
                <div className="h-full flex items-center justify-center text-center text-gray-500">
                  <div>
                    <span className="material-icons text-4xl mb-2">schema</span>
                    <p>Parse your plan to preview phases and modules.</p>
                  </div>
                </div>
              )}

              {preview && (
                <div className="space-y-4">
                  <div className="bg-gray-800/70 border border-gray-700 rounded-lg p-4">
                    <h4 className="text-white font-semibold text-base">
                      {preview.blueprint?.title || 'Imported Blueprint'}
                    </h4>
                    {preview.blueprint?.subtitle && (
                      <p className="text-sm text-gray-400 mt-1">{preview.blueprint.subtitle}</p>
                    )}
                    {preview.blueprint?.description && (
                      <p className="text-sm text-gray-300 mt-2">{preview.blueprint.description}</p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-400">
                      <span>{phaseCount} phase(s)</span>
                      <span>{moduleCount} module(s)</span>
                      <span>{connectionCount} connection(s)</span>
                      {typeof importConfidence === 'number' && (
                        <span>confidence {Math.round(importConfidence * 100)}%</span>
                      )}
                    </div>
                  </div>

                  <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                    {(preview.phases || []).map((phase, idx) => (
                      <div key={`${phase.index || idx}-${phase.title || idx}`} className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
                        <div className="text-sm text-white font-medium">
                          Phase {phase.index || idx + 1}: {phase.title || 'Untitled Phase'}
                        </div>
                        <div className="text-xs text-gray-400 mt-1">
                          {(phase.modules || []).length} module(s)
                        </div>
                        {(phase.modules || []).slice(0, 4).map((m, moduleIdx) => (
                          <div key={`${m.code || moduleIdx}-${m.title || moduleIdx}`} className="text-xs text-gray-300 mt-1">
                            {m.code || `${idx + 1}.${moduleIdx + 1}`} {m.title || 'Untitled Module'}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>

                  {warnings.length > 0 && (
                    <div className="bg-yellow-900/20 border border-yellow-700/40 rounded-lg p-3">
                      <div className="text-yellow-300 text-sm font-medium mb-1">Parser Warnings</div>
                      {warnings.map((w, idx) => (
                        <div key={`${w}-${idx}`} className="text-xs text-yellow-200/90">{w}</div>
                      ))}
                    </div>
                  )}

                  <div className="pt-2">
                    <button
                      onClick={handleMaterialize}
                      disabled={!blueprintId || !!materializingTargetId}
                      className="w-full px-4 py-2 rounded-lg text-sm bg-green-600 hover:bg-green-700 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                    >
                      {materializingTargetId === blueprintId ? 'Materializing...' : 'Materialize Into Learn Topics'}
                    </button>
                  </div>
                </div>
              )}

              {error && (
                <div className="mt-4 bg-red-900/20 border border-red-700/40 rounded-lg p-3 text-sm text-red-300">
                  {error}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'library' && (
          <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-[340px_1fr]">
            <div className="border-r border-gray-800 p-3 overflow-y-auto">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-200">Saved Blueprints</h3>
                <span className="text-xs text-gray-400">{libraryBlueprints.length}</span>
              </div>

              {isLoadingLibrary && libraryBlueprints.length === 0 && (
                <div className="text-sm text-gray-500 py-4">Loading blueprint history...</div>
              )}

              {!isLoadingLibrary && libraryBlueprints.length === 0 && (
                <div className="text-sm text-gray-500 py-4">No imported blueprints yet.</div>
              )}

              <div className="space-y-2">
                {libraryBlueprints.map((bp) => {
                  const isSelected = bp.id === selectedLibraryId
                  const isMaterializingThis = materializingTargetId === bp.id
                  const alreadyMaterialized = bp.status === 'materialized'
                  return (
                    <button
                      key={bp.id}
                      type="button"
                      onClick={() => void handleSelectLibraryBlueprint(bp.id)}
                      className={`w-full text-left rounded-lg border p-3 transition-colors ${
                        isSelected
                          ? 'border-teal-500/70 bg-teal-900/20'
                          : 'border-gray-700 bg-gray-800/50 hover:bg-gray-800'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <div className="text-sm font-medium text-white truncate">{bp.title || 'Untitled Blueprint'}</div>
                        <span className={`px-2 py-0.5 rounded text-[11px] uppercase ${statusBadgeClass(bp.status)}`}>
                          {bp.status || 'unknown'}
                        </span>
                      </div>
                      <div className="text-[11px] text-gray-400">
                        Created {formatDate(bp.created_at)}
                      </div>
                      <div className="text-[11px] text-gray-400">
                        Confidence {typeof bp.import_confidence === 'number' ? `${Math.round(bp.import_confidence * 100)}%` : 'N/A'}
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation()
                            void materializeBlueprint(bp.id, alreadyMaterialized)
                          }}
                          disabled={!!materializingTargetId}
                          className="px-2.5 py-1 rounded text-xs bg-green-700 hover:bg-green-600 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                        >
                          {isMaterializingThis
                            ? alreadyMaterialized ? 'Rematerializing...' : 'Materializing...'
                            : alreadyMaterialized ? 'Rematerialize' : 'Materialize'}
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation()
                            void generateGuidesForBlueprint(bp.id)
                          }}
                          disabled={!!guidesBusyTargetId}
                          className="px-2.5 py-1 rounded text-xs bg-indigo-700 hover:bg-indigo-600 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                        >
                          {guidesBusyTargetId === bp.id ? 'Queueing...' : 'Generate Guides'}
                        </button>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="p-4 overflow-y-auto">
              {!selectedLibraryDetail && (
                <div className="h-full flex items-center justify-center text-center text-gray-500">
                  <div>
                    <span className="material-icons text-4xl mb-2">history</span>
                    <p>Select a saved blueprint to inspect and manage it.</p>
                  </div>
                </div>
              )}

              {selectedLibraryDetail && (
                <div className="space-y-4">
                  <div className="bg-gray-800/70 border border-gray-700 rounded-lg p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h4 className="text-white font-semibold text-base">
                          {selectedLibraryDetail.title || 'Untitled Blueprint'}
                        </h4>
                        {selectedLibraryDetail.subtitle && (
                          <p className="text-sm text-gray-400 mt-1">{selectedLibraryDetail.subtitle}</p>
                        )}
                      </div>
                      <span className={`px-2 py-0.5 rounded text-[11px] uppercase ${statusBadgeClass(selectedLibraryDetail.status)}`}>
                        {selectedLibraryDetail.status || 'unknown'}
                      </span>
                    </div>

                    {selectedLibraryDetail.description && (
                      <p className="text-sm text-gray-300 mt-2">{selectedLibraryDetail.description}</p>
                    )}

                    <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-400">
                      <span>{libraryCounts.phases} phase(s)</span>
                      <span>{libraryCounts.modules} module(s)</span>
                      <span>{libraryCounts.connections} connection(s)</span>
                      <span>created {formatDate(selectedLibraryDetail.created_at)}</span>
                      {selectedLibraryDetail.materialized_at && (
                        <span>materialized {formatDate(selectedLibraryDetail.materialized_at)}</span>
                      )}
                    </div>
                  </div>

                  {selectedLibraryProgress && (
                    <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
                      <div className="text-sm font-medium text-white">Progress</div>
                      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-300">
                        <span>{selectedLibraryProgress.completed_modules}/{selectedLibraryProgress.total_modules} completed</span>
                        <span>{selectedLibraryProgress.percent_complete}% complete</span>
                        {selectedLibraryProgress.current_module_code && (
                          <span>current {selectedLibraryProgress.current_module_code}</span>
                        )}
                      </div>
                      {selectedLibraryProgress.current_module_title && (
                        <div className="mt-1 text-xs text-gray-400">{selectedLibraryProgress.current_module_title}</div>
                      )}
                    </div>
                  )}

                  <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium text-white">Study Guide Generation</div>
                      {selectedGuideJob && (
                        <span className={`px-2 py-0.5 rounded text-[11px] uppercase ${guideStatusBadgeClass(selectedGuideJob.status)}`}>
                          {selectedGuideJob.status}
                        </span>
                      )}
                    </div>
                    {!selectedGuideJob && (
                      <div className="mt-2 text-xs text-gray-400">No guide jobs yet for this blueprint.</div>
                    )}
                    {selectedGuideJob && (
                      <div className="mt-2 space-y-1 text-xs text-gray-300">
                        <div>
                          {selectedGuideJob.progress || 0}% complete
                          {selectedGuideJob.current_step ? ` - ${selectedGuideJob.current_step}` : ''}
                        </div>
                        <div>
                          Modules {selectedGuideJob.completed_modules || 0}/{selectedGuideJob.total_modules || 0}
                          {' | '}Artifacts {selectedGuideJob.artifacts_created || 0}
                        </div>
                        <div>Model {selectedGuideJob.model || 'gpt-oss:20b'}</div>
                        {selectedGuideJob.error_message && (
                          <div className="text-red-300">{selectedGuideJob.error_message}</div>
                        )}
                        {selectedLibraryId && selectedGuideJob.id && ['queued', 'running', 'cancelling'].includes(selectedGuideJob.status) && (
                          <div className="pt-1">
                            <button
                              onClick={() => void cancelGuideJob(selectedLibraryId, selectedGuideJob.id)}
                              disabled={selectedGuideJob.status === 'cancelling'}
                              className="px-2.5 py-1 rounded text-xs bg-red-700 hover:bg-red-600 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                            >
                              {selectedGuideJob.status === 'cancelling' ? 'Cancelling...' : 'Cancel Generation'}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium text-white">Generated Guides</div>
                      <span className="text-xs text-gray-400">{selectedGuideArtifacts.length}</span>
                    </div>
                    {selectedGuideArtifacts.length === 0 && (
                      <div className="mt-2 text-xs text-gray-400">No study guides generated yet.</div>
                    )}
                    {selectedGuideArtifacts.length > 0 && (
                      <div className="mt-2 space-y-2 max-h-48 overflow-y-auto pr-1">
                        {selectedGuideArtifacts.slice(0, 20).map((guide) => (
                          <div key={guide.id} className="border border-gray-700 rounded p-2">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className="text-xs text-white font-medium truncate">
                                  {guide.title || guide.content?.module_title || 'Study Guide'}
                                </div>
                                <div className="text-[11px] text-gray-400 mt-0.5">
                                  {(guide.content?.module_code || 'module')} - {guide.artifact_type.replace('study_guide_', '')}
                                </div>
                                <div className="text-[11px] text-gray-500 mt-0.5">
                                  {formatDate(guide.updated_at || guide.created_at)}
                                </div>
                              </div>
                              {onOpenArtifact && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    onOpenArtifact(guide)
                                  }}
                                  className="shrink-0 px-2 py-1 rounded text-[11px] bg-teal-700 hover:bg-teal-600 text-white transition-colors"
                                >
                                  Read
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                    {(libraryPreview?.phases || []).map((phase, idx) => (
                      <div key={`${phase.index || idx}-${phase.title || idx}`} className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
                        <div className="text-sm text-white font-medium">
                          Phase {phase.index || idx + 1}: {phase.title || 'Untitled Phase'}
                        </div>
                        <div className="text-xs text-gray-400 mt-1">
                          {(phase.modules || []).length} module(s)
                        </div>
                        {(phase.modules || []).slice(0, 4).map((module, moduleIdx) => (
                          <div key={`${module.code || moduleIdx}-${module.title || moduleIdx}`} className="text-xs text-gray-300 mt-1">
                            {module.code || `${idx + 1}.${moduleIdx + 1}`} {module.title || 'Untitled Module'}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>

                  <div className="flex gap-2 pt-2">
                    <button
                      onClick={() => void materializeBlueprint(selectedLibraryDetail.id, selectedLibraryDetail.status === 'materialized')}
                      disabled={!!materializingTargetId}
                      className="px-4 py-2 rounded-lg text-sm bg-green-600 hover:bg-green-700 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                    >
                      {materializingTargetId === selectedLibraryDetail.id
                        ? selectedLibraryDetail.status === 'materialized' ? 'Rematerializing...' : 'Materializing...'
                        : selectedLibraryDetail.status === 'materialized' ? 'Rematerialize Blueprint' : 'Materialize Blueprint'}
                    </button>
                    <button
                      onClick={() => void generateGuidesForBlueprint(selectedLibraryDetail.id)}
                      disabled={!!guidesBusyTargetId}
                      className="px-4 py-2 rounded-lg text-sm bg-indigo-700 hover:bg-indigo-600 disabled:bg-gray-700 disabled:text-gray-500 text-white transition-colors"
                    >
                      {guidesBusyTargetId === selectedLibraryDetail.id ? 'Queueing Guides...' : 'Generate Study Guides'}
                    </button>
                    <button
                      onClick={() => {
                        setActiveTab('import')
                        setPlanText(selectedLibraryDetail.raw_text || '')
                        setTitleOverride(selectedLibraryDetail.title || '')
                        setError(null)
                      }}
                      className="px-4 py-2 rounded-lg text-sm bg-gray-700 hover:bg-gray-600 text-white transition-colors"
                    >
                      Load Into Import Editor
                    </button>
                  </div>
                </div>
              )}

              {libraryError && (
                <div className="mt-4 bg-red-900/20 border border-red-700/40 rounded-lg p-3 text-sm text-red-300">
                  {libraryError}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
