import React, { useState, useEffect, useCallback } from 'react'
import {
  Briefcase,
  Plus,
  Settings,
  Activity,
  GitCommit,
  GitPullRequest,
  Bug,
  Sparkles,
  CheckSquare,
  Wrench,
  ChevronDown,
  X,
  GripVertical,
  ExternalLink,
  Github,
  Clock,
  Calendar,
  TrendingUp,
  BarChart3,
  ClipboardCheck,
  Check,
  MessageSquare,
  Trash2,
  Edit3,
  Save,
  FolderOpen,
  FileText,
  Upload,
  Download,
  ChevronRight,
  Home,
  FolderPlus,
  File
} from 'lucide-react'
import { APP_CONFIG } from '../../config'

// ============================================================================
// TYPES
// ============================================================================

interface Project {
  id: string
  name: string
  prefix: string
  description: string | null
  tech_stack: string | null
  business_context: string | null
  github_repo_owner: string | null
  github_repo_name: string | null
  github_repo_url: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  task_counts: Record<string, number> | null
}

interface Task {
  id: string
  project_id: string
  task_number: number
  tag: string
  title: string
  description: string | null
  task_type: string
  status: string
  priority: string | null
  tags: string[] | null
  sort_order: number
  created_at: string
  updated_at: string
  completed_at: string | null
  commit_count: number
}

interface TaskBoard {
  backlog: Task[]
  in_progress: Task[]
  in_qa: Task[]
  completed: Task[]
  total: number
}

interface ProjectStats {
  task_counts: Record<string, number>
  commits_this_week: number
  tasks_completed_this_week: number
  open_bugs: number
  active_branches: number
  velocity: {
    commits_per_day: number
    tasks_per_week: number
  }
}

interface Commit {
  id: string
  sha: string
  short_sha: string
  message: string
  author_name: string | null
  author_email: string | null
  committed_at: string
  branch: string | null
  additions: number | null
  deletions: number | null
  linked_tasks: string[]
}

interface ActivityItem {
  id: string
  type: string
  title: string
  description: string | null
  timestamp: string
  metadata: Record<string, unknown>
}

interface QAChecklistItem {
  id: string
  label: string
  sort_order: number
  is_active: boolean
  created_at: string
}

interface QAPendingCommit {
  id: string
  sha: string
  message: string
  author_name: string | null
  committed_at: string
  qa_status: string | null
}

interface QAPendingTask {
  task_id: string
  task_tag: string
  task_title: string
  commits: QAPendingCommit[]
}

interface ProjectFolder {
  id: string
  name: string
  parent_id: string | null
  created_at: string
  updated_at: string
}

interface ProjectFile {
  id: string
  filename: string
  folder_id: string | null
  mime_type: string | null
  file_size: number
  file_size_formatted: string
  description: string | null
  created_at: string
  updated_at: string
}

interface FileListResponse {
  files: ProjectFile[]
  folders: ProjectFolder[]
  total_files: number
  total_folders: number
  current_folder_id: string | null
  breadcrumb: ProjectFolder[]
}

type ProjectView = 'board' | 'activity' | 'commits' | 'qa' | 'files' | 'settings'

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function ProjectSection() {
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [currentView, setCurrentView] = useState<ProjectView>('board')
  const [loading, setLoading] = useState(true)
  const [showCreateProject, setShowCreateProject] = useState(false)
  const [showCreateTask, setShowCreateTask] = useState(false)
  const [boardRefreshKey, setBoardRefreshKey] = useState(0)

  // Load projects on mount
  useEffect(() => {
    loadProjects()
  }, [])

  const loadProjects = async () => {
    try {
      setLoading(true)
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects`, {
        credentials: 'include'
      })
      if (response.ok) {
        const data = await response.json()
        setProjects(data.projects || [])
        // Select first active project by default
        if (data.projects?.length > 0 && !selectedProject) {
          setSelectedProject(data.projects[0])
        }
      }
    } catch (error) {
      console.error('Failed to load projects:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleProjectCreated = (project: Project) => {
    setProjects(prev => [...prev, project])
    setSelectedProject(project)
    setShowCreateProject(false)
  }

  const tabs = [
    { id: 'board' as ProjectView, label: 'Task Board', icon: CheckSquare },
    { id: 'activity' as ProjectView, label: 'Activity', icon: Activity },
    { id: 'commits' as ProjectView, label: 'Commits', icon: GitCommit },
    { id: 'qa' as ProjectView, label: 'QA', icon: ClipboardCheck },
    { id: 'files' as ProjectView, label: 'Files', icon: FolderOpen },
    { id: 'settings' as ProjectView, label: 'Settings', icon: Settings },
  ]

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-900">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-gray-900 text-white">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-800">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Briefcase className="w-6 h-6" />
              Project Tracker
            </h1>

            {/* Project Selector */}
            <div className="relative">
              <select
                value={selectedProject?.id || ''}
                onChange={(e) => {
                  const project = projects.find(p => p.id === e.target.value)
                  setSelectedProject(project || null)
                }}
                className="bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 pr-8
                           text-white appearance-none cursor-pointer min-w-[200px]"
              >
                <option value="" disabled>Select Project</option>
                {projects.map(project => (
                  <option key={project.id} value={project.id}>
                    [{project.prefix}] {project.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none text-gray-400" />
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setShowCreateProject(true)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg
                         flex items-center gap-2 transition-colors"
            >
              <Plus className="w-4 h-4" />
              New Project
            </button>
            {selectedProject && (
              <button
                onClick={() => setShowCreateTask(true)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg
                           flex items-center gap-2 transition-colors"
              >
                <Plus className="w-4 h-4" />
                New Task
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        {selectedProject && (
          <div className="flex gap-1 px-6 overflow-x-auto">
            {tabs.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.id}
                  onClick={() => setCurrentView(tab.id)}
                  className={`
                    px-4 py-2 rounded-t-lg flex items-center gap-2 transition-colors
                    whitespace-nowrap flex-shrink-0
                    ${
                      currentView === tab.id
                        ? 'bg-gray-900 text-white'
                        : 'text-gray-400 hover:text-white hover:bg-gray-700'
                    }
                  `}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {!selectedProject ? (
          <EmptyState onCreateProject={() => setShowCreateProject(true)} />
        ) : (
          <>
            {currentView === 'board' && (
              <TaskBoard
                project={selectedProject}
                refreshKey={boardRefreshKey}
              />
            )}
            {currentView === 'activity' && (
              <ActivityFeed project={selectedProject} />
            )}
            {currentView === 'commits' && (
              <CommitsList project={selectedProject} />
            )}
            {currentView === 'qa' && (
              <QATab project={selectedProject} />
            )}
            {currentView === 'files' && (
              <FilesTab project={selectedProject} />
            )}
            {currentView === 'settings' && (
              <ProjectSettings
                project={selectedProject}
                onUpdate={(updated) => {
                  setSelectedProject(updated)
                  setProjects(prev => prev.map(p => p.id === updated.id ? updated : p))
                }}
              />
            )}
          </>
        )}
      </div>

      {/* Modals */}
      {showCreateProject && (
        <CreateProjectModal
          onClose={() => setShowCreateProject(false)}
          onCreate={handleProjectCreated}
        />
      )}

      {showCreateTask && selectedProject && (
        <CreateTaskModal
          project={selectedProject}
          onClose={() => setShowCreateTask(false)}
          onCreate={() => {
            setShowCreateTask(false)
            setBoardRefreshKey(prev => prev + 1)
          }}
        />
      )}
    </div>
  )
}

// ============================================================================
// EMPTY STATE
// ============================================================================

function EmptyState({ onCreateProject }: { onCreateProject: () => void }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center p-8">
      <Briefcase className="w-16 h-16 text-gray-600 mb-4" />
      <h2 className="text-xl font-semibold text-gray-300 mb-2">
        No Projects Yet
      </h2>
      <p className="text-gray-500 mb-6 max-w-md">
        Create your first project to start tracking tasks, commits, and development progress.
      </p>
      <button
        onClick={onCreateProject}
        className="px-6 py-3 bg-blue-600 hover:bg-blue-500 rounded-lg
                   flex items-center gap-2 transition-colors"
      >
        <Plus className="w-5 h-5" />
        Create First Project
      </button>
    </div>
  )
}

// ============================================================================
// TASK BOARD (KANBAN)
// ============================================================================

function TaskBoard({
  project,
  refreshKey = 0
}: {
  project: Project
  refreshKey?: number
}) {
  const [board, setBoard] = useState<TaskBoard | null>(null)
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [draggingTask, setDraggingTask] = useState<Task | null>(null)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)

  useEffect(() => {
    loadBoard()
    loadStats()
  }, [project.id, refreshKey])

  const loadBoard = async () => {
    try {
      setLoading(true)
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/board`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setBoard(data)
      }
    } catch (error) {
      console.error('Failed to load board:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/stats`,
        { credentials: 'include' }
      )
      if (response.ok) {
        setStats(await response.json())
      }
    } catch (error) {
      console.error('Failed to load stats:', error)
    }
  }

  const handleStatusChange = async (task: Task, newStatus: string) => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/tasks/${task.id}/status?status=${newStatus}`,
        {
          method: 'PATCH',
          credentials: 'include'
        }
      )
      if (response.ok) {
        loadBoard() // Refresh
      }
    } catch (error) {
      console.error('Failed to update task status:', error)
    }
  }

  const handleDragStart = (task: Task) => {
    setDraggingTask(task)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const handleDrop = (e: React.DragEvent, status: string) => {
    e.preventDefault()
    if (draggingTask && draggingTask.status !== status) {
      handleStatusChange(draggingTask, status)
    }
    setDraggingTask(null)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  const columns = [
    { id: 'backlog', label: 'Backlog', tasks: board?.backlog || [], color: 'gray' },
    { id: 'in_progress', label: 'In Progress', tasks: board?.in_progress || [], color: 'blue' },
    { id: 'in_qa', label: 'In QA', tasks: board?.in_qa || [], color: 'yellow' },
    { id: 'completed', label: 'Completed', tasks: board?.completed || [], color: 'green' },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Stats Bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard
            icon={<CheckSquare className="w-5 h-5" />}
            label="Total Tasks"
            value={board?.total || 0}
          />
          <StatCard
            icon={<Bug className="w-5 h-5 text-red-400" />}
            label="Open Bugs"
            value={stats.open_bugs}
          />
          <StatCard
            icon={<GitCommit className="w-5 h-5 text-green-400" />}
            label="Commits (Week)"
            value={stats.commits_this_week}
          />
          <StatCard
            icon={<TrendingUp className="w-5 h-5 text-blue-400" />}
            label="Completed (Week)"
            value={stats.tasks_completed_this_week}
          />
          <StatCard
            icon={<BarChart3 className="w-5 h-5 text-purple-400" />}
            label="Velocity"
            value={`${stats.velocity.commits_per_day}/day`}
          />
        </div>
      )}

      {/* Kanban Board */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 min-h-[500px]">
        {columns.map(column => (
          <div
            key={column.id}
            className="bg-gray-800 rounded-lg flex flex-col"
            onDragOver={handleDragOver}
            onDrop={(e) => handleDrop(e, column.id)}
          >
            {/* Column Header */}
            <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full bg-${column.color}-500`} />
                <span className="font-medium">{column.label}</span>
                <span className="text-gray-500 text-sm">
                  ({column.tasks.length})
                </span>
              </div>
            </div>

            {/* Tasks */}
            <div className="flex-1 p-2 space-y-2 overflow-y-auto max-h-[600px]">
              {column.tasks.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  project={project}
                  onDragStart={() => handleDragStart(task)}
                  onClick={() => setSelectedTask(task)}
                />
              ))}
              {column.tasks.length === 0 && (
                <div className="text-center text-gray-500 py-8">
                  No tasks
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Task Detail Modal */}
      {selectedTask && (
        <TaskDetailModal
          task={selectedTask}
          project={project}
          onClose={() => setSelectedTask(null)}
          onUpdate={loadBoard}
        />
      )}
    </div>
  )
}

// ============================================================================
// TASK CARD
// ============================================================================

function TaskCard({
  task,
  project,
  onDragStart,
  onClick
}: {
  task: Task
  project: Project
  onDragStart: () => void
  onClick: () => void
}) {
  const typeIcons: Record<string, React.ReactNode> = {
    feature: <Sparkles className="w-3 h-3 text-purple-400" />,
    bug: <Bug className="w-3 h-3 text-red-400" />,
    task: <CheckSquare className="w-3 h-3 text-blue-400" />,
    chore: <Wrench className="w-3 h-3 text-gray-400" />,
  }

  const priorityColors: Record<string, string> = {
    critical: 'border-l-red-500',
    high: 'border-l-orange-500',
    medium: 'border-l-yellow-500',
    low: 'border-l-gray-500',
  }

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onClick={onClick}
      className={`
        bg-gray-700 rounded-lg p-3 cursor-pointer
        hover:bg-gray-650 transition-colors border-l-4
        ${task.priority ? priorityColors[task.priority] : 'border-l-transparent'}
      `}
    >
      {/* Header: Type icon + Tag */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {typeIcons[task.task_type] || typeIcons.task}
          <span className="text-xs font-mono text-gray-400">{task.tag}</span>
        </div>
        {task.commit_count > 0 && (
          <div className="flex items-center gap-1 text-xs text-gray-500">
            <GitCommit className="w-3 h-3" />
            {task.commit_count}
          </div>
        )}
      </div>

      {/* Title */}
      <p className="text-sm font-medium text-gray-100 line-clamp-2">
        {task.title}
      </p>

      {/* Tags */}
      {task.tags && task.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {task.tags.slice(0, 3).map(tag => (
            <span
              key={tag}
              className="px-2 py-0.5 bg-gray-600 rounded text-xs text-gray-300"
            >
              {tag}
            </span>
          ))}
          {task.tags.length > 3 && (
            <span className="text-xs text-gray-500">
              +{task.tags.length - 3}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ============================================================================
// STAT CARD
// ============================================================================

function StatCard({
  icon,
  label,
  value
}: {
  icon: React.ReactNode
  label: string
  value: number | string
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 flex items-center gap-3">
      <div className="text-gray-400">{icon}</div>
      <div>
        <div className="text-2xl font-bold">{value}</div>
        <div className="text-xs text-gray-500">{label}</div>
      </div>
    </div>
  )
}

// ============================================================================
// TASK DETAIL MODAL
// ============================================================================

function TaskDetailModal({
  task,
  project,
  onClose,
  onUpdate
}: {
  task: Task
  project: Project
  onClose: () => void
  onUpdate: () => void
}) {
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description || '')
  const [taskType, setTaskType] = useState(task.task_type)
  const [priority, setPriority] = useState(task.priority || '')
  const [status, setStatus] = useState(task.status)
  const [saving, setSaving] = useState(false)
  const [commits, setCommits] = useState<Commit[]>([])

  useEffect(() => {
    loadCommits()
  }, [task.id])

  const loadCommits = async () => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/tasks/${task.id}/commits`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setCommits(data.commits || [])
      }
    } catch (error) {
      console.error('Failed to load commits:', error)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/tasks/${task.id}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title,
            description,
            task_type: taskType,
            priority: priority || null,
            status
          })
        }
      )
      if (response.ok) {
        onUpdate()
        onClose()
      }
    } catch (error) {
      console.error('Failed to save task:', error)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this task?')) return

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/tasks/${task.id}`,
        {
          method: 'DELETE',
          credentials: 'include'
        }
      )
      if (response.ok) {
        onUpdate()
        onClose()
      }
    } catch (error) {
      console.error('Failed to delete task:', error)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-sm font-mono text-gray-400">{task.tag}</span>
            <span className={`px-2 py-0.5 rounded text-xs ${
              status === 'completed' ? 'bg-green-900 text-green-300' :
              status === 'in_progress' ? 'bg-blue-900 text-blue-300' :
              status === 'in_qa' ? 'bg-yellow-900 text-yellow-300' :
              'bg-gray-700 text-gray-300'
            }`}>
              {status.replace('_', ' ')}
            </span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500 resize-none"
              placeholder="Add a description..."
            />
          </div>

          {/* Type, Priority, Status */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Type</label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                           text-white"
              >
                <option value="task">Task</option>
                <option value="feature">Feature</option>
                <option value="bug">Bug</option>
                <option value="chore">Chore</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Priority</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                           text-white"
              >
                <option value="">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                           text-white"
              >
                <option value="backlog">Backlog</option>
                <option value="in_progress">In Progress</option>
                <option value="in_qa">In QA</option>
                <option value="completed">Completed</option>
              </select>
            </div>
          </div>

          {/* Linked Commits */}
          {commits.length > 0 && (
            <div>
              <label className="block text-sm text-gray-400 mb-2">
                Linked Commits ({commits.length})
              </label>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {commits.map(commit => (
                  <div
                    key={commit.id}
                    className="bg-gray-700 rounded-lg p-3 flex items-start gap-3"
                  >
                    <GitCommit className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-blue-400">
                          {commit.short_sha}
                        </span>
                        {commit.branch && (
                          <span className="text-xs text-gray-500">
                            on {commit.branch}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-300 truncate">
                        {commit.message}
                      </p>
                      <div className="text-xs text-gray-500 mt-1">
                        {commit.author_name} - {new Date(commit.committed_at).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="text-xs text-gray-500 flex items-center gap-4">
            <span>Created: {new Date(task.created_at).toLocaleDateString()}</span>
            {task.completed_at && (
              <span>Completed: {new Date(task.completed_at).toLocaleDateString()}</span>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex justify-between">
          <button
            onClick={handleDelete}
            className="px-4 py-2 text-red-400 hover:text-red-300 hover:bg-red-900/20
                       rounded-lg transition-colors"
          >
            Delete
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors
                         disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// ACTIVITY FEED
// ============================================================================

function ActivityFeed({ project }: { project: Project }) {
  const [activities, setActivities] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadActivities()
  }, [project.id])

  const loadActivities = async () => {
    try {
      setLoading(true)
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/activity`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setActivities(data.items || [])
      }
    } catch (error) {
      console.error('Failed to load activities:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  const typeIcons: Record<string, React.ReactNode> = {
    commit: <GitCommit className="w-4 h-4 text-green-400" />,
    task_created: <Plus className="w-4 h-4 text-blue-400" />,
    task_completed: <CheckSquare className="w-4 h-4 text-green-400" />,
    pr_opened: <GitPullRequest className="w-4 h-4 text-purple-400" />,
    pr_merged: <GitPullRequest className="w-4 h-4 text-green-400" />,
  }

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
      <div className="space-y-4">
        {activities.map(activity => (
          <div
            key={activity.id}
            className="flex items-start gap-3 bg-gray-800 rounded-lg p-4"
          >
            {typeIcons[activity.type] || <Activity className="w-4 h-4" />}
            <div className="flex-1 min-w-0">
              <div className="font-medium">{activity.title}</div>
              {activity.description && (
                <p className="text-sm text-gray-400 truncate">
                  {activity.description}
                </p>
              )}
              <div className="text-xs text-gray-500 mt-1">
                {new Date(activity.timestamp).toLocaleString()}
              </div>
            </div>
          </div>
        ))}
        {activities.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            No activity yet
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// COMMITS LIST
// ============================================================================

function CommitsList({ project }: { project: Project }) {
  const [commits, setCommits] = useState<Commit[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    loadCommits()
  }, [project.id, page])

  const loadCommits = async () => {
    try {
      setLoading(true)
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/commits?page=${page}&per_page=20`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setCommits(data.commits || [])
        setTotal(data.total || 0)
      }
    } catch (error) {
      console.error('Failed to load commits:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Commits ({total})</h2>
        {project.github_repo_url && (
          <a
            href={project.github_repo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300"
          >
            <Github className="w-4 h-4" />
            View on GitHub
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>

      <div className="space-y-2">
        {commits.map(commit => (
          <div
            key={commit.id}
            className="bg-gray-800 rounded-lg p-4 flex items-start gap-4"
          >
            <GitCommit className="w-5 h-5 text-green-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono text-sm text-blue-400">
                  {commit.short_sha}
                </span>
                {commit.branch && (
                  <span className="px-2 py-0.5 bg-gray-700 rounded text-xs">
                    {commit.branch}
                  </span>
                )}
                {commit.linked_tasks.length > 0 && (
                  <div className="flex gap-1">
                    {commit.linked_tasks.map(tag => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 bg-blue-900 text-blue-300 rounded text-xs"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-gray-200">{commit.message}</p>
              <div className="flex items-center gap-4 text-xs text-gray-500 mt-2">
                <span>{commit.author_name}</span>
                <span>{new Date(commit.committed_at).toLocaleString()}</span>
                {(commit.additions != null || commit.deletions != null) && (
                  <span>
                    <span className="text-green-400">+{commit.additions || 0}</span>
                    {' / '}
                    <span className="text-red-400">-{commit.deletions || 0}</span>
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
        {commits.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            No commits yet. Connect your GitHub repository to start tracking commits.
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > 20 && (
        <div className="flex justify-center gap-2 mt-6">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="px-4 py-2 text-gray-400">
            Page {page} of {Math.ceil(total / 20)}
          </span>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={page >= Math.ceil(total / 20)}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// PROJECT SETTINGS
// ============================================================================

function ProjectSettings({
  project,
  onUpdate
}: {
  project: Project
  onUpdate: (project: Project) => void
}) {
  const [name, setName] = useState(project.name)
  const [prefix, setPrefix] = useState(project.prefix)
  const [description, setDescription] = useState(project.description || '')
  const [techStack, setTechStack] = useState(project.tech_stack || '')
  const [businessContext, setBusinessContext] = useState(project.business_context || '')
  const [githubUrl, setGithubUrl] = useState(project.github_repo_url || '')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            name,
            prefix,
            description,
            tech_stack: techStack,
            business_context: businessContext,
            github_repo_url: githubUrl
          })
        }
      )
      if (response.ok) {
        const updated = await response.json()
        onUpdate(updated)
      }
    } catch (error) {
      console.error('Failed to save project:', error)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-lg font-semibold mb-6">Project Settings</h2>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Project Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Prefix (for task tags)</label>
            <input
              type="text"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value.toUpperCase())}
              maxLength={10}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white font-mono focus:outline-none focus:border-blue-500"
              placeholder="e.g., RN, SARA"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                       text-white focus:outline-none focus:border-blue-500 resize-none"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Tech Stack</label>
          <input
            type="text"
            value={techStack}
            onChange={(e) => setTechStack(e.target.value)}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                       text-white focus:outline-none focus:border-blue-500"
            placeholder="e.g., React, Node.js, PostgreSQL"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">Business Context</label>
          <input
            type="text"
            value={businessContext}
            onChange={(e) => setBusinessContext(e.target.value)}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                       text-white focus:outline-none focus:border-blue-500"
            placeholder="e.g., Commercial SaaS, Personal project"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">GitHub Repository URL</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={githubUrl}
              onChange={(e) => setGithubUrl(e.target.value)}
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500"
              placeholder="https://github.com/owner/repo"
            />
            {project.github_repo_url && (
              <a
                href={project.github_repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg
                           flex items-center gap-2"
              >
                <Github className="w-4 h-4" />
                Open
              </a>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Webhooks will automatically track commits and PRs when configured.
          </p>
        </div>

        <div className="pt-4">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg
                       transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>

        {/* QA Checklist Configuration */}
        <div className="pt-8 border-t border-gray-700 mt-8">
          <div className="flex items-center gap-2 mb-4">
            <ClipboardCheck className="w-5 h-5 text-gray-400" />
            <h3 className="text-lg font-semibold">QA Checklist</h3>
          </div>
          <p className="text-sm text-gray-400 mb-4">
            Configure the checklist items that appear when testing commits in the QA tab.
          </p>
          <QAChecklistConfig project={project} />
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// CREATE PROJECT MODAL
// ============================================================================

function CreateProjectModal({
  onClose,
  onCreate
}: {
  onClose: () => void
  onCreate: (project: Project) => void
}) {
  const [name, setName] = useState('')
  const [prefix, setPrefix] = useState('')
  const [description, setDescription] = useState('')
  const [techStack, setTechStack] = useState('')
  const [githubUrl, setGithubUrl] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const handleCreate = async () => {
    if (!name.trim() || !prefix.trim()) {
      setError('Name and prefix are required')
      return
    }

    setCreating(true)
    setError('')

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name,
          prefix: prefix.toUpperCase(),
          description,
          tech_stack: techStack,
          github_repo_url: githubUrl
        })
      })

      if (response.ok) {
        const project = await response.json()
        onCreate(project)
      } else {
        const data = await response.json()
        setError(data.detail || 'Failed to create project')
      }
    } catch (err) {
      setError('Failed to create project')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg">
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Create New Project</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-300 text-sm">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Project Name *</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                           text-white focus:outline-none focus:border-blue-500"
                placeholder="Risk Ninja"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Prefix *</label>
              <input
                type="text"
                value={prefix}
                onChange={(e) => setPrefix(e.target.value.toUpperCase())}
                maxLength={10}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                           text-white font-mono focus:outline-none focus:border-blue-500"
                placeholder="RN"
              />
              <p className="text-xs text-gray-500 mt-1">
                Used for task tags (e.g., RN-42)
              </p>
            </div>
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500 resize-none"
              placeholder="Insurance agency management platform..."
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Tech Stack</label>
            <input
              type="text"
              value={techStack}
              onChange={(e) => setTechStack(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500"
              placeholder="React, Node.js, PostgreSQL"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">GitHub Repository</label>
            <input
              type="text"
              value={githubUrl}
              onChange={(e) => setGithubUrl(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500"
              placeholder="https://github.com/owner/repo"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors
                       disabled:opacity-50"
          >
            {creating ? 'Creating...' : 'Create Project'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// QA TAB
// ============================================================================

interface QAResult {
  id: string
  commit_id: string
  checked_items: string[]
  notes: string | null
  status: string
  tested_at: string | null
}

function QATab({ project }: { project: Project }) {
  const [pendingTasks, setPendingTasks] = useState<QAPendingTask[]>([])
  const [checklist, setChecklist] = useState<QAChecklistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set())
  const [commitStates, setCommitStates] = useState<Record<string, {
    checked: string[]
    notes: string
    saving: boolean
  }>>({})

  useEffect(() => {
    loadData()
  }, [project.id])

  const loadData = async () => {
    try {
      setLoading(true)
      const [pendingRes, checklistRes] = await Promise.all([
        fetch(`${APP_CONFIG.apiUrl}/api/projects/${project.id}/qa/pending`, { credentials: 'include' }),
        fetch(`${APP_CONFIG.apiUrl}/api/projects/${project.id}/qa/checklist`, { credentials: 'include' })
      ])

      if (pendingRes.ok) {
        const data = await pendingRes.json()
        setPendingTasks(data.tasks || [])
        // Expand first task by default
        if (data.tasks?.length > 0) {
          setExpandedTasks(new Set([data.tasks[0].task_id]))
        }
      }

      if (checklistRes.ok) {
        const data = await checklistRes.json()
        setChecklist(data.items || [])
      }
    } catch (error) {
      console.error('Failed to load QA data:', error)
    } finally {
      setLoading(false)
    }
  }

  const toggleTask = (taskId: string) => {
    setExpandedTasks(prev => {
      const next = new Set(prev)
      if (next.has(taskId)) {
        next.delete(taskId)
      } else {
        next.add(taskId)
      }
      return next
    })
  }

  const getCommitState = (commitId: string) => {
    return commitStates[commitId] || { checked: [], notes: '', saving: false }
  }

  const updateCommitState = (commitId: string, updates: Partial<{ checked: string[], notes: string, saving: boolean }>) => {
    setCommitStates(prev => ({
      ...prev,
      [commitId]: { ...getCommitState(commitId), ...updates }
    }))
  }

  const toggleCheckItem = (commitId: string, itemId: string) => {
    const state = getCommitState(commitId)
    const newChecked = state.checked.includes(itemId)
      ? state.checked.filter(id => id !== itemId)
      : [...state.checked, itemId]
    updateCommitState(commitId, { checked: newChecked })
  }

  const saveQAResult = async (commitId: string, status: 'passed' | 'failed' | 'skipped') => {
    const state = getCommitState(commitId)
    updateCommitState(commitId, { saving: true })

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects/commits/${commitId}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          checked_items: state.checked,
          notes: state.notes || null,
          status
        })
      })

      if (response.ok) {
        // Remove from pending list
        setPendingTasks(prev => prev.map(task => ({
          ...task,
          commits: task.commits.filter(c => c.id !== commitId)
        })).filter(task => task.commits.length > 0))
      }
    } catch (error) {
      console.error('Failed to save QA result:', error)
    } finally {
      updateCommitState(commitId, { saving: false })
    }
  }

  const totalPending = pendingTasks.reduce((sum, t) => sum + t.commits.length, 0)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  if (checklist.length === 0) {
    return (
      <div className="p-6 max-w-3xl">
        <div className="text-center py-12 bg-gray-800 rounded-lg">
          <ClipboardCheck className="w-12 h-12 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-300 mb-2">No QA Checklist Configured</h3>
          <p className="text-gray-500 mb-4">
            Add checklist items in Project Settings to start QA testing.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">QA Testing</h2>
          {totalPending > 0 && (
            <span className="px-2 py-1 bg-yellow-900 text-yellow-300 rounded-full text-sm">
              {totalPending} pending
            </span>
          )}
        </div>
      </div>

      {/* Task Groups */}
      {pendingTasks.length === 0 ? (
        <div className="text-center py-12 bg-gray-800 rounded-lg">
          <Check className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-300">All Caught Up!</h3>
          <p className="text-gray-500">No commits pending QA review.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {pendingTasks.map(task => (
            <div key={task.task_id} className="bg-gray-800 rounded-lg overflow-hidden">
              {/* Task Header */}
              <button
                onClick={() => toggleTask(task.task_id)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-750 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-blue-400">{task.task_tag}</span>
                  <span className="text-gray-200">{task.task_title}</span>
                  <span className="text-sm text-gray-500">
                    ({task.commits.length} commit{task.commits.length !== 1 ? 's' : ''})
                  </span>
                </div>
                <ChevronDown className={`w-5 h-5 text-gray-400 transition-transform ${
                  expandedTasks.has(task.task_id) ? 'rotate-180' : ''
                }`} />
              </button>

              {/* Commits */}
              {expandedTasks.has(task.task_id) && (
                <div className="border-t border-gray-700">
                  {task.commits.map(commit => {
                    const state = getCommitState(commit.id)
                    const allChecked = checklist.every(item => state.checked.includes(item.id))

                    return (
                      <div key={commit.id} className="p-4 border-b border-gray-700 last:border-b-0">
                        {/* Commit Info */}
                        <div className="flex items-start gap-3 mb-4">
                          <GitCommit className="w-4 h-4 text-green-400 mt-1 flex-shrink-0" />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-sm text-blue-400">{commit.sha.slice(0, 7)}</span>
                              {commit.qa_status && (
                                <span className={`px-2 py-0.5 rounded text-xs ${
                                  commit.qa_status === 'passed' ? 'bg-green-900 text-green-300' :
                                  commit.qa_status === 'failed' ? 'bg-red-900 text-red-300' :
                                  'bg-gray-700 text-gray-300'
                                }`}>
                                  {commit.qa_status}
                                </span>
                              )}
                            </div>
                            <p className="text-sm text-gray-300 mt-1">{commit.message}</p>
                            <div className="text-xs text-gray-500 mt-1">
                              {commit.author_name} · {new Date(commit.committed_at).toLocaleString()}
                            </div>
                          </div>
                        </div>

                        {/* Checklist */}
                        <div className="ml-7 space-y-2 mb-4">
                          {checklist.map(item => (
                            <label
                              key={item.id}
                              className="flex items-center gap-3 cursor-pointer hover:bg-gray-700/50 p-2 rounded -ml-2"
                            >
                              <input
                                type="checkbox"
                                checked={state.checked.includes(item.id)}
                                onChange={() => toggleCheckItem(commit.id, item.id)}
                                className="w-4 h-4 rounded border-gray-500 bg-gray-700 text-blue-500
                                           focus:ring-blue-500 focus:ring-offset-gray-800"
                              />
                              <span className="text-gray-300">{item.label}</span>
                            </label>
                          ))}
                        </div>

                        {/* Notes */}
                        <div className="ml-7 mb-4">
                          <textarea
                            value={state.notes}
                            onChange={(e) => updateCommitState(commit.id, { notes: e.target.value })}
                            placeholder="Add notes (optional)..."
                            rows={2}
                            className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2
                                       text-sm text-white placeholder-gray-500 focus:outline-none
                                       focus:border-blue-500 resize-none"
                          />
                        </div>

                        {/* Actions */}
                        <div className="ml-7 flex gap-2">
                          <button
                            onClick={() => saveQAResult(commit.id, 'passed')}
                            disabled={state.saving || !allChecked}
                            className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg text-sm
                                       flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed
                                       transition-colors"
                          >
                            <Check className="w-4 h-4" />
                            {state.saving ? 'Saving...' : 'Pass QA'}
                          </button>
                          <button
                            onClick={() => saveQAResult(commit.id, 'failed')}
                            disabled={state.saving}
                            className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded-lg text-sm
                                       flex items-center gap-2 disabled:opacity-50 transition-colors"
                          >
                            Fail
                          </button>
                          <button
                            onClick={() => saveQAResult(commit.id, 'skipped')}
                            disabled={state.saving}
                            className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded-lg text-sm
                                       disabled:opacity-50 transition-colors"
                          >
                            Skip
                          </button>
                          {!allChecked && (
                            <span className="text-xs text-yellow-500 self-center ml-2">
                              Check all items to pass
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================================
// QA CHECKLIST CONFIG (for Settings)
// ============================================================================

function QAChecklistConfig({ project }: { project: Project }) {
  const [items, setItems] = useState<QAChecklistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [newLabel, setNewLabel] = useState('')
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editLabel, setEditLabel] = useState('')

  useEffect(() => {
    loadItems()
  }, [project.id])

  const loadItems = async () => {
    try {
      setLoading(true)
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/qa/checklist`,
        { credentials: 'include' }
      )
      if (response.ok) {
        const data = await response.json()
        setItems(data.items || [])
      }
    } catch (error) {
      console.error('Failed to load checklist:', error)
    } finally {
      setLoading(false)
    }
  }

  const addItem = async () => {
    if (!newLabel.trim()) return

    setAdding(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/qa/checklist`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ label: newLabel.trim() })
        }
      )
      if (response.ok) {
        const item = await response.json()
        setItems(prev => [...prev, item])
        setNewLabel('')
      }
    } catch (error) {
      console.error('Failed to add item:', error)
    } finally {
      setAdding(false)
    }
  }

  const updateItem = async (itemId: string) => {
    if (!editLabel.trim()) return

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/qa/checklist/${itemId}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ label: editLabel.trim() })
        }
      )
      if (response.ok) {
        const updated = await response.json()
        setItems(prev => prev.map(item => item.id === itemId ? updated : item))
        setEditingId(null)
        setEditLabel('')
      }
    } catch (error) {
      console.error('Failed to update item:', error)
    }
  }

  const deleteItem = async (itemId: string) => {
    if (!confirm('Delete this checklist item?')) return

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/qa/checklist/${itemId}`,
        {
          method: 'DELETE',
          credentials: 'include'
        }
      )
      if (response.ok) {
        setItems(prev => prev.filter(item => item.id !== itemId))
      }
    } catch (error) {
      console.error('Failed to delete item:', error)
    }
  }

  const startEditing = (item: QAChecklistItem) => {
    setEditingId(item.id)
    setEditLabel(item.label)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-24">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Existing Items */}
      {items.length > 0 && (
        <div className="space-y-2">
          {items.map(item => (
            <div
              key={item.id}
              className="flex items-center gap-2 bg-gray-700 rounded-lg p-3"
            >
              {editingId === item.id ? (
                <>
                  <input
                    type="text"
                    value={editLabel}
                    onChange={(e) => setEditLabel(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') updateItem(item.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    className="flex-1 bg-gray-600 border border-gray-500 rounded px-3 py-1
                               text-white focus:outline-none focus:border-blue-500"
                    autoFocus
                  />
                  <button
                    onClick={() => updateItem(item.id)}
                    className="p-1 text-green-400 hover:text-green-300"
                  >
                    <Save className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setEditingId(null)}
                    className="p-1 text-gray-400 hover:text-gray-300"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </>
              ) : (
                <>
                  <GripVertical className="w-4 h-4 text-gray-500 cursor-grab" />
                  <span className="flex-1 text-gray-200">{item.label}</span>
                  <button
                    onClick={() => startEditing(item)}
                    className="p-1 text-gray-400 hover:text-blue-400"
                  >
                    <Edit3 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => deleteItem(item.id)}
                    className="p-1 text-gray-400 hover:text-red-400"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Add New Item */}
      <div className="flex gap-2">
        <input
          type="text"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addItem()
          }}
          placeholder="Add checklist item (e.g., Login, Create Customer)"
          className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                     text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={addItem}
          disabled={adding || !newLabel.trim()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg
                     flex items-center gap-2 disabled:opacity-50 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add
        </button>
      </div>

      {items.length === 0 && (
        <p className="text-sm text-gray-500">
          Add checklist items that you want to verify for each commit during QA.
        </p>
      )}
    </div>
  )
}

// ============================================================================
// CREATE TASK MODAL
// ============================================================================

function CreateTaskModal({
  project,
  onClose,
  onCreate
}: {
  project: Project
  onClose: () => void
  onCreate: () => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [taskType, setTaskType] = useState('task')
  const [priority, setPriority] = useState('')
  const [creating, setCreating] = useState(false)

  const handleCreate = async () => {
    if (!title.trim()) return

    setCreating(true)
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/tasks`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            title,
            description,
            task_type: taskType,
            priority: priority || null
          })
        }
      )

      if (response.ok) {
        onCreate()
      }
    } catch (error) {
      console.error('Failed to create task:', error)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg w-full max-w-lg">
        <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            Create Task in [{project.prefix}]
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Title *</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500"
              placeholder="Implement user authentication"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-sm text-gray-400 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2
                         text-white focus:outline-none focus:border-blue-500 resize-none"
              placeholder="Add details..."
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Type</label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white"
              >
                <option value="task">Task</option>
                <option value="feature">Feature</option>
                <option value="bug">Bug</option>
                <option value="chore">Chore</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Priority</label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-white"
              >
                <option value="">None</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={creating || !title.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors
                       disabled:opacity-50"
          >
            {creating ? 'Creating...' : 'Create Task'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// FILES TAB
// ============================================================================

function FilesTab({ project }: { project: Project }) {
  const [files, setFiles] = useState<ProjectFile[]>([])
  const [folders, setFolders] = useState<ProjectFolder[]>([])
  const [breadcrumb, setBreadcrumb] = useState<ProjectFolder[]>([])
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [showCreateFolder, setShowCreateFolder] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const fileInputRef = React.useRef<HTMLInputElement>(null)

  const loadFiles = useCallback(async (folderId: string | null = null) => {
    try {
      setLoading(true)
      const url = folderId
        ? `${APP_CONFIG.apiUrl}/api/projects/${project.id}/files?folder_id=${folderId}`
        : `${APP_CONFIG.apiUrl}/api/projects/${project.id}/files`

      const response = await fetch(url, { credentials: 'include' })
      if (response.ok) {
        const data: FileListResponse = await response.json()
        setFiles(data.files)
        setFolders(data.folders)
        setBreadcrumb(data.breadcrumb)
        setCurrentFolderId(data.current_folder_id)
      }
    } catch (error) {
      console.error('Failed to load files:', error)
    } finally {
      setLoading(false)
    }
  }, [project.id])

  useEffect(() => {
    loadFiles()
  }, [loadFiles])

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadFiles = e.target.files
    if (!uploadFiles?.length) return

    setUploading(true)
    try {
      for (const file of Array.from(uploadFiles)) {
        const formData = new FormData()
        formData.append('file', file)
        if (currentFolderId) {
          formData.append('folder_id', currentFolderId)
        }

        const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects/${project.id}/files/upload`, {
          method: 'POST',
          credentials: 'include',
          body: formData
        })

        if (!response.ok) {
          console.error('Upload failed:', await response.text())
        }
      }
      // Await the refresh to ensure state updates properly
      await loadFiles(currentFolderId)
    } catch (error) {
      console.error('Failed to upload file:', error)
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects/${project.id}/files/folders`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newFolderName.trim(),
          parent_id: currentFolderId
        })
      })

      if (response.ok) {
        setNewFolderName('')
        setShowCreateFolder(false)
        loadFiles(currentFolderId)
      }
    } catch (error) {
      console.error('Failed to create folder:', error)
    }
  }

  const handleDeleteFile = async (fileId: string) => {
    if (!confirm('Are you sure you want to delete this file?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects/${project.id}/files/${fileId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        loadFiles(currentFolderId)
      }
    } catch (error) {
      console.error('Failed to delete file:', error)
    }
  }

  const handleDeleteFolder = async (folderId: string) => {
    if (!confirm('Are you sure you want to delete this folder and all its contents?')) return

    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/projects/${project.id}/files/folders/${folderId}`, {
        method: 'DELETE',
        credentials: 'include'
      })

      if (response.ok) {
        loadFiles(currentFolderId)
      }
    } catch (error) {
      console.error('Failed to delete folder:', error)
    }
  }

  const handleDownload = async (file: ProjectFile) => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/projects/${project.id}/files/${file.id}/download`,
        { credentials: 'include' }
      )

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = file.filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('Failed to download file:', error)
    }
  }

  const navigateToFolder = (folderId: string | null) => {
    loadFiles(folderId)
  }

  const getFileIcon = (mimeType: string | null) => {
    if (!mimeType) return <File className="w-5 h-5 text-gray-400" />
    if (mimeType.startsWith('text/')) return <FileText className="w-5 h-5 text-blue-400" />
    if (mimeType === 'application/pdf') return <FileText className="w-5 h-5 text-red-400" />
    return <File className="w-5 h-5 text-gray-400" />
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-white">Project Files</h2>
          <p className="text-sm text-gray-400">
            Upload and organize project documents
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowCreateFolder(true)}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg
                       flex items-center gap-2 transition-colors"
          >
            <FolderPlus className="w-4 h-4" />
            New Folder
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg
                       flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <Upload className="w-4 h-4" />
            {uploading ? 'Uploading...' : 'Upload Files'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileUpload}
            className="hidden"
          />
        </div>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-4 text-sm">
        <button
          onClick={() => navigateToFolder(null)}
          className="flex items-center gap-1 text-gray-400 hover:text-white transition-colors"
        >
          <Home className="w-4 h-4" />
          Root
        </button>
        {breadcrumb.map((folder, index) => (
          <React.Fragment key={folder.id}>
            <ChevronRight className="w-4 h-4 text-gray-600" />
            <button
              onClick={() => navigateToFolder(folder.id)}
              className={`hover:text-white transition-colors ${
                index === breadcrumb.length - 1 ? 'text-white' : 'text-gray-400'
              }`}
            >
              {folder.name}
            </button>
          </React.Fragment>
        ))}
      </div>

      {/* Create Folder Modal */}
      {showCreateFolder && (
        <div className="mb-4 p-4 bg-gray-800 rounded-lg border border-gray-700">
          <div className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-yellow-500" />
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="Folder name..."
              className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
            />
            <button
              onClick={handleCreateFolder}
              disabled={!newFolderName.trim()}
              className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg disabled:opacity-50"
            >
              Create
            </button>
            <button
              onClick={() => {
                setShowCreateFolder(false)
                setNewFolderName('')
              }}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* File/Folder List */}
      <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
        {folders.length === 0 && files.length === 0 ? (
          <div className="p-8 text-center text-gray-400">
            <FolderOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>This folder is empty</p>
            <p className="text-sm mt-1">Upload files or create folders to get started</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="bg-gray-900 text-left text-sm text-gray-400">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3 w-32">Size</th>
                <th className="px-4 py-3 w-48">Modified</th>
                <th className="px-4 py-3 w-24">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {/* Folders */}
              {folders.map((folder) => (
                <tr
                  key={folder.id}
                  className="hover:bg-gray-750 cursor-pointer"
                  onClick={() => navigateToFolder(folder.id)}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <FolderOpen className="w-5 h-5 text-yellow-500" />
                      <span className="font-medium text-white">{folder.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-400">—</td>
                  <td className="px-4 py-3 text-gray-400 text-sm">
                    {new Date(folder.updated_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => handleDeleteFolder(folder.id)}
                      className="p-1 text-gray-400 hover:text-red-400 transition-colors"
                      title="Delete folder"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}

              {/* Files */}
              {files.map((file) => (
                <tr key={file.id} className="hover:bg-gray-750">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      {getFileIcon(file.mime_type)}
                      <span className="text-white">{file.filename}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-sm">
                    {file.file_size_formatted}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-sm">
                    {new Date(file.updated_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleDownload(file)}
                        className="p-1 text-gray-400 hover:text-blue-400 transition-colors"
                        title="Download"
                      >
                        <Download className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDeleteFile(file.id)}
                        className="p-1 text-gray-400 hover:text-red-400 transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
