import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Briefcase,
  Plus,
  Loader2,
  ChevronDown,
  Trash2,
  GitCommit,
  Folder,
  FileText,
  ChevronRight,
  Download,
  ExternalLink,
  LayoutGrid,
  FolderOpen,
  ArrowLeft,
  Github,
} from 'lucide-react'
import { projectsApi, type Project, type Task, type Commit, type ProjectFile, type ProjectFolder } from '../../services/api'
import type { ProjectsWindowData, FileViewerWindowData } from '../../types'
import { useCanvasStore } from '../../store/canvasStore'

interface ProjectsContentProps {
  data: ProjectsWindowData
  windowId: string
}

type Tab = 'board' | 'commits' | 'files'

const COLUMNS = [
  { id: 'backlog', label: 'Backlog', color: 'border-gray-500' },
  { id: 'in_progress', label: 'In Progress', color: 'border-blue-500' },
  { id: 'in_qa', label: 'In QA', color: 'border-yellow-500' },
  { id: 'done', label: 'Done', color: 'border-green-500' },
] as const

type TaskStatus = typeof COLUMNS[number]['id']

export default function ProjectsContent({ data }: ProjectsContentProps) {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(data.projectId || null)
  const [activeTab, setActiveTab] = useState<Tab>('board')

  const { data: projects = [], isLoading: loadingProjects } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  })

  const selectedProject = projects.find((p) => p.id === selectedProjectId)

  if (loadingProjects) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading projects...
      </div>
    )
  }

  const tabs: { id: Tab; label: string; icon: typeof LayoutGrid }[] = [
    { id: 'board', label: 'Board', icon: LayoutGrid },
    { id: 'commits', label: 'Commits', icon: GitCommit },
    { id: 'files', label: 'Files', icon: Folder },
  ]

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Header with project selector */}
      <div className="p-3 border-b border-canvas-border">
        <ProjectSelector
          projects={projects}
          selectedId={selectedProjectId}
          onSelect={setSelectedProjectId}
        />
      </div>

      {selectedProject ? (
        <>
          {/* Project Info Bar */}
          <div className="px-4 py-2 border-b border-canvas-border flex items-center gap-4 text-sm">
            <span className="text-white font-medium">{selectedProject.name}</span>
            {selectedProject.prefix && (
              <span className="text-canvas-muted">({selectedProject.prefix})</span>
            )}
            {selectedProject.tech_stack && (
              <span className="text-canvas-muted">{selectedProject.tech_stack}</span>
            )}
            {selectedProject.github_repo_owner && selectedProject.github_repo_name && (
              <a
                href={`https://github.com/${selectedProject.github_repo_owner}/${selectedProject.github_repo_name}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-blue-400 hover:text-blue-300"
              >
                <Github size={14} />
                {selectedProject.github_repo_owner}/{selectedProject.github_repo_name}
                <ExternalLink size={12} />
              </a>
            )}
          </div>

          {/* Tabs */}
          <div className="flex border-b border-canvas-border">
            {tabs.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2 flex items-center gap-2 text-sm font-medium transition-colors ${
                    activeTab === tab.id
                      ? 'text-white border-b-2 border-purple-500 bg-canvas-surface/50'
                      : 'text-canvas-muted hover:text-white hover:bg-canvas-surface/30'
                  }`}
                >
                  <Icon size={16} />
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-hidden">
            {activeTab === 'board' && <KanbanBoard project={selectedProject} />}
            {activeTab === 'commits' && <CommitsTab project={selectedProject} />}
            {activeTab === 'files' && <FilesTab project={selectedProject} />}
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-canvas-muted">
          <div className="text-center">
            <Briefcase size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg">Select a project</p>
            <p className="text-sm mt-1">or create a new one</p>
          </div>
        </div>
      )}
    </div>
  )
}

function ProjectSelector({
  projects,
  selectedId,
  onSelect,
}: {
  projects: Project[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: (newProject) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      onSelect(newProject.id)
      setShowCreateForm(false)
      setNewProjectName('')
    },
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newProjectName.trim()) return
    createMutation.mutate({ name: newProjectName.trim() })
  }

  const selected = projects.find((p) => p.id === selectedId)

  return (
    <div className="relative">
      <div className="flex gap-2">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex-1 flex items-center justify-between px-3 py-2 bg-canvas-surface rounded-lg border border-canvas-border text-left"
        >
          <span className="text-white font-medium">
            {selected?.name || 'Select project...'}
          </span>
          <ChevronDown
            size={18}
            className={`text-canvas-muted transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        </button>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="p-2 bg-purple-500 hover:bg-purple-600 rounded-lg transition-colors"
          title="New project"
        >
          <Plus size={20} className="text-white" />
        </button>
      </div>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute top-full left-0 right-12 mt-1 bg-canvas-surface border border-canvas-border rounded-lg shadow-lg z-10 max-h-60 overflow-y-auto">
          {projects.length === 0 ? (
            <div className="p-4 text-center text-canvas-muted">No projects yet</div>
          ) : (
            projects.map((project) => (
              <button
                key={project.id}
                onClick={() => {
                  onSelect(project.id)
                  setIsOpen(false)
                }}
                className={`w-full px-4 py-2 text-left hover:bg-canvas-elevated transition-colors ${
                  project.id === selectedId ? 'bg-canvas-elevated text-white' : 'text-canvas-muted'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-white">{project.name}</span>
                  {project.prefix && (
                    <span className="text-xs text-canvas-muted">{project.prefix}</span>
                  )}
                </div>
                {project.description && (
                  <div className="text-sm text-canvas-muted truncate">{project.description}</div>
                )}
              </button>
            ))
          )}
        </div>
      )}

      {/* Create form */}
      {showCreateForm && (
        <form onSubmit={handleCreate} className="mt-2 flex gap-2">
          <input
            type="text"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="Project name"
            className="flex-1 px-3 py-2 bg-canvas-elevated rounded border border-canvas-border text-white placeholder-canvas-muted focus:outline-none focus:border-purple-500"
            autoFocus
          />
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-50 rounded text-white font-medium transition-colors"
          >
            {createMutation.isPending ? 'Creating...' : 'Create'}
          </button>
        </form>
      )}
    </div>
  )
}

function KanbanBoard({ project }: { project: Project }) {
  const queryClient = useQueryClient()
  const [showAddTask, setShowAddTask] = useState<TaskStatus | null>(null)
  const [newTaskTitle, setNewTaskTitle] = useState('')

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['projects', project.id, 'tasks'],
    queryFn: () => projectsApi.getTasks(project.id),
  })

  const createTaskMutation = useMutation({
    mutationFn: ({ title, status }: { title: string; status: TaskStatus }) =>
      projectsApi.createTask(project.id, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects', project.id, 'tasks'] })
      setShowAddTask(null)
      setNewTaskTitle('')
    },
  })

  const updateTaskMutation = useMutation({
    mutationFn: ({ taskId, data }: { taskId: string; data: Partial<Task> }) =>
      projectsApi.updateTask(taskId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects', project.id, 'tasks'] })
    },
  })

  const deleteTaskMutation = useMutation({
    mutationFn: projectsApi.deleteTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects', project.id, 'tasks'] })
    },
  })

  const handleAddTask = (status: TaskStatus) => {
    if (!newTaskTitle.trim()) return
    createTaskMutation.mutate({ title: newTaskTitle.trim(), status })
  }

  const handleMoveTask = (taskId: string, newStatus: TaskStatus) => {
    updateTaskMutation.mutate({ taskId, data: { status: newStatus } })
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading tasks...
      </div>
    )
  }

  return (
    <div className="flex-1 flex overflow-x-auto p-4 gap-4">
      {COLUMNS.map((column) => {
        const columnTasks = tasks.filter((t) => t.status === column.id)

        return (
          <div
            key={column.id}
            className={`flex-shrink-0 w-64 flex flex-col bg-canvas-surface/50 rounded-lg border-t-2 ${column.color}`}
          >
            {/* Column header */}
            <div className="px-3 py-2 flex items-center justify-between border-b border-canvas-border">
              <span className="font-medium text-white">{column.label}</span>
              <span className="text-sm text-canvas-muted">{columnTasks.length}</span>
            </div>

            {/* Tasks */}
            <div className="flex-1 overflow-y-auto p-2 space-y-2 custom-scrollbar">
              {columnTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onMove={(status) => handleMoveTask(task.id, status)}
                  onDelete={() => deleteTaskMutation.mutate(task.id)}
                />
              ))}

              {/* Add task form */}
              {showAddTask === column.id ? (
                <div className="p-2 bg-canvas-elevated rounded">
                  <input
                    type="text"
                    value={newTaskTitle}
                    onChange={(e) => setNewTaskTitle(e.target.value)}
                    placeholder="Task title"
                    className="w-full px-2 py-1 bg-canvas-surface rounded border border-canvas-border text-white text-sm placeholder-canvas-muted focus:outline-none focus:border-purple-500"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleAddTask(column.id)
                      if (e.key === 'Escape') setShowAddTask(null)
                    }}
                  />
                  <div className="flex gap-1 mt-2">
                    <button
                      onClick={() => handleAddTask(column.id)}
                      disabled={createTaskMutation.isPending}
                      className="flex-1 px-2 py-1 bg-purple-500 hover:bg-purple-600 rounded text-xs text-white"
                    >
                      Add
                    </button>
                    <button
                      onClick={() => setShowAddTask(null)}
                      className="px-2 py-1 bg-canvas-surface hover:bg-canvas-border rounded text-xs text-canvas-muted"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setShowAddTask(column.id)}
                  className="w-full p-2 text-sm text-canvas-muted hover:text-white hover:bg-canvas-elevated rounded transition-colors flex items-center justify-center gap-1"
                >
                  <Plus size={14} />
                  Add task
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function TaskCard({
  task,
  onMove,
  onDelete,
}: {
  task: Task
  onMove: (status: TaskStatus) => void
  onDelete: () => void
}) {
  const [showMenu, setShowMenu] = useState(false)

  const priorityColors: Record<string, string> = {
    high: 'bg-red-500',
    medium: 'bg-yellow-500',
    low: 'bg-green-500',
  }

  return (
    <div className="p-3 bg-canvas-elevated rounded-lg border border-canvas-border group">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="text-sm text-white">{task.title}</div>
          {task.description && (
            <div className="text-xs text-canvas-muted mt-1 line-clamp-2">{task.description}</div>
          )}
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-1 hover:bg-canvas-surface rounded"
            >
              <ChevronDown size={14} className="text-canvas-muted" />
            </button>
            {showMenu && (
              <div className="absolute right-0 top-full mt-1 bg-canvas-surface border border-canvas-border rounded shadow-lg z-10 py-1 min-w-[100px]">
                {COLUMNS.map((col) => (
                  <button
                    key={col.id}
                    onClick={() => {
                      onMove(col.id)
                      setShowMenu(false)
                    }}
                    className={`w-full px-3 py-1 text-left text-xs hover:bg-canvas-elevated ${
                      task.status === col.id ? 'text-white' : 'text-canvas-muted'
                    }`}
                  >
                    {col.label}
                  </button>
                ))}
                <div className="border-t border-canvas-border my-1" />
                <button
                  onClick={() => {
                    onDelete()
                    setShowMenu(false)
                  }}
                  className="w-full px-3 py-1 text-left text-xs text-red-400 hover:bg-canvas-elevated"
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Priority indicator */}
      <div className="flex items-center gap-2 mt-2">
        <div
          className={`w-2 h-2 rounded-full ${priorityColors[task.priority] || 'bg-gray-500'}`}
          title={`Priority: ${task.priority}`}
        />
        <span className="text-xs text-canvas-muted capitalize">{task.priority}</span>
      </div>
    </div>
  )
}

function CommitsTab({ project }: { project: Project }) {
  const { data: commits = [], isLoading, error } = useQuery({
    queryKey: ['projects', project.id, 'commits'],
    queryFn: () => projectsApi.getCommits(project.id, 50),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading commits...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load commits
      </div>
    )
  }

  if (commits.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <div className="text-center">
          <GitCommit size={48} className="mx-auto mb-4 opacity-30" />
          <p>No commits found</p>
          <p className="text-sm mt-1">Connect a GitHub repo to see commits</p>
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-y-auto h-full custom-scrollbar">
      <div className="p-4 space-y-3">
        {commits.map((commit) => (
          <div
            key={commit.id}
            className="p-4 bg-canvas-surface rounded-lg border border-canvas-border"
          >
            <div className="flex items-start gap-3">
              <GitCommit size={18} className="text-purple-400 mt-1 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <code className="text-xs bg-canvas-elevated px-2 py-0.5 rounded text-blue-400">
                    {commit.short_sha}
                  </code>
                  <span className="text-xs text-canvas-muted">
                    {commit.branch && `on ${commit.branch}`}
                  </span>
                </div>
                <p className="text-white text-sm whitespace-pre-wrap break-words">
                  {commit.message.split('\n')[0]}
                </p>
                {commit.message.includes('\n') && (
                  <p className="text-canvas-muted text-xs mt-2 whitespace-pre-wrap">
                    {commit.message.split('\n').slice(1).join('\n').trim()}
                  </p>
                )}
                <div className="flex items-center gap-4 mt-2 text-xs text-canvas-muted">
                  <span>{commit.author_name}</span>
                  <span>{new Date(commit.committed_at).toLocaleString()}</span>
                  {(commit.additions !== null || commit.deletions !== null) && (
                    <span>
                      <span className="text-green-400">+{commit.additions || 0}</span>
                      {' / '}
                      <span className="text-red-400">-{commit.deletions || 0}</span>
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FilesTab({ project }: { project: Project }) {
  const { openWindow } = useCanvasStore()
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<ProjectFile | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['projects', project.id, 'files', currentFolderId],
    queryFn: () => projectsApi.getFiles(project.id, currentFolderId),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading files...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        Failed to load files
      </div>
    )
  }

  const { files = [], folders = [], breadcrumb = [] } = data || {}

  const handleFolderClick = (folderId: string) => {
    setCurrentFolderId(folderId)
    setSelectedFile(null)
  }

  const handleBack = () => {
    if (breadcrumb.length > 1) {
      setCurrentFolderId(breadcrumb[breadcrumb.length - 2].id)
    } else {
      setCurrentFolderId(null)
    }
    setSelectedFile(null)
  }

  const handleFileClick = (file: ProjectFile) => {
    setSelectedFile(file)
  }

  const handleOpenFile = (file: ProjectFile) => {
    const fileData: FileViewerWindowData = {
      filename: file.filename,
      content: '', // Will be fetched by the component
      mimeType: file.mime_type || undefined,
      source: 'project',
      projectId: project.id,
      fileId: file.id,
    }
    openWindow('fileviewer', fileData, { title: file.filename })
  }

  const handleDownload = (file: ProjectFile) => {
    const url = projectsApi.downloadFile(project.id, file.id)
    window.open(url, '_blank')
  }

  return (
    <div className="flex h-full">
      {/* File list */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Breadcrumb */}
        <div className="px-4 py-2 border-b border-canvas-border flex items-center gap-2 text-sm">
          {currentFolderId && (
            <button
              onClick={handleBack}
              className="p-1 hover:bg-canvas-elevated rounded text-canvas-muted hover:text-white"
            >
              <ArrowLeft size={16} />
            </button>
          )}
          <button
            onClick={() => setCurrentFolderId(null)}
            className="text-canvas-muted hover:text-white"
          >
            Root
          </button>
          {breadcrumb.map((folder, index) => (
            <span key={folder.id} className="flex items-center gap-2">
              <ChevronRight size={14} className="text-canvas-muted" />
              <button
                onClick={() => setCurrentFolderId(folder.id)}
                className={index === breadcrumb.length - 1 ? 'text-white' : 'text-canvas-muted hover:text-white'}
              >
                {folder.name}
              </button>
            </span>
          ))}
        </div>

        {/* File/Folder list */}
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {folders.length === 0 && files.length === 0 ? (
            <div className="flex items-center justify-center h-full text-canvas-muted">
              <div className="text-center">
                <Folder size={48} className="mx-auto mb-4 opacity-30" />
                <p>No files or folders</p>
              </div>
            </div>
          ) : (
            <div className="p-2">
              {/* Folders */}
              {folders.map((folder) => (
                <button
                  key={folder.id}
                  onClick={() => handleFolderClick(folder.id)}
                  className="w-full flex items-center gap-3 p-3 hover:bg-canvas-elevated rounded-lg transition-colors"
                >
                  <FolderOpen size={20} className="text-yellow-500" />
                  <span className="text-white">{folder.name}</span>
                </button>
              ))}

              {/* Files */}
              {files.map((file) => (
                <button
                  key={file.id}
                  onClick={() => handleFileClick(file)}
                  onDoubleClick={() => handleOpenFile(file)}
                  className={`w-full flex items-center gap-3 p-3 rounded-lg transition-colors ${
                    selectedFile?.id === file.id
                      ? 'bg-purple-500/20 border border-purple-500/50'
                      : 'hover:bg-canvas-elevated'
                  }`}
                >
                  <FileText size={20} className="text-blue-400" />
                  <div className="flex-1 text-left">
                    <div className="text-white">{file.filename}</div>
                    <div className="text-xs text-canvas-muted">
                      {file.file_size_formatted} • {new Date(file.updated_at).toLocaleDateString()}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* File preview panel */}
      {selectedFile && (
        <div className="w-80 border-l border-canvas-border flex flex-col">
          <div className="p-4 border-b border-canvas-border">
            <h3 className="text-white font-medium truncate">{selectedFile.filename}</h3>
            <p className="text-sm text-canvas-muted mt-1">{selectedFile.file_size_formatted}</p>
          </div>

          <div className="flex-1 p-4 space-y-4">
            <div>
              <div className="text-xs text-canvas-muted mb-1">Type</div>
              <div className="text-white text-sm">{selectedFile.mime_type || 'Unknown'}</div>
            </div>

            {selectedFile.description && (
              <div>
                <div className="text-xs text-canvas-muted mb-1">Description</div>
                <div className="text-white text-sm">{selectedFile.description}</div>
              </div>
            )}

            <div>
              <div className="text-xs text-canvas-muted mb-1">Created</div>
              <div className="text-white text-sm">
                {new Date(selectedFile.created_at).toLocaleString()}
              </div>
            </div>

            <div>
              <div className="text-xs text-canvas-muted mb-1">Updated</div>
              <div className="text-white text-sm">
                {new Date(selectedFile.updated_at).toLocaleString()}
              </div>
            </div>
          </div>

          <div className="p-4 border-t border-canvas-border space-y-2">
            <button
              onClick={() => handleOpenFile(selectedFile)}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 rounded-lg text-white transition-colors"
            >
              <ExternalLink size={16} />
              Open
            </button>
            <button
              onClick={() => handleDownload(selectedFile)}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-canvas-surface hover:bg-canvas-elevated border border-canvas-border rounded-lg text-white transition-colors"
            >
              <Download size={16} />
              Download
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
