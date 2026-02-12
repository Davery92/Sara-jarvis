import { useState, useEffect, useMemo } from 'react'
import { FileText, Download, Copy, Check, Loader2, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { FileViewerWindowData } from '../../types'
import { projectsApi } from '../../services/api'

interface FileViewerContentProps {
  data: FileViewerWindowData
  windowId: string
}

// Get language from filename for syntax highlighting
function getLanguageFromFilename(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const languageMap: Record<string, string> = {
    js: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    py: 'python',
    rb: 'ruby',
    go: 'go',
    rs: 'rust',
    java: 'java',
    kt: 'kotlin',
    swift: 'swift',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    cs: 'csharp',
    php: 'php',
    sql: 'sql',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    yml: 'yaml',
    yaml: 'yaml',
    json: 'json',
    xml: 'xml',
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'scss',
    sass: 'sass',
    less: 'less',
    md: 'markdown',
    markdown: 'markdown',
    txt: 'text',
    env: 'bash',
    gitignore: 'text',
    dockerfile: 'dockerfile',
    toml: 'toml',
    ini: 'ini',
    conf: 'text',
    cfg: 'text',
  }
  return languageMap[ext] || 'text'
}

// Check if file is a PDF
function isPdfFile(filename: string, mimeType?: string): boolean {
  if (mimeType === 'application/pdf') return true
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  return ext === 'pdf'
}

// Check if file is an image
function isImageFile(filename: string, mimeType?: string): boolean {
  if (mimeType?.startsWith('image/')) return true
  const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico']
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  return imageExtensions.includes(ext)
}

// Check if file is a Word document
function isWordFile(filename: string, mimeType?: string): boolean {
  if (mimeType?.includes('wordprocessingml') || mimeType?.includes('msword')) return true
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  return ext === 'docx' || ext === 'doc'
}

// Check if file is likely text-based
function isTextFile(filename: string, mimeType?: string): boolean {
  if (mimeType?.startsWith('text/')) return true
  if (mimeType?.includes('json') || mimeType?.includes('xml') || mimeType?.includes('javascript')) return true

  const textExtensions = [
    'txt', 'md', 'markdown', 'json', 'xml', 'html', 'htm', 'css', 'scss', 'sass', 'less',
    'js', 'jsx', 'ts', 'tsx', 'py', 'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'cpp',
    'h', 'hpp', 'cs', 'php', 'sql', 'sh', 'bash', 'zsh', 'yml', 'yaml', 'toml', 'ini',
    'conf', 'cfg', 'env', 'gitignore', 'dockerfile', 'makefile', 'cmake', 'gradle',
    'properties', 'log', 'csv', 'tsv',
  ]
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  return textExtensions.includes(ext) || filename.toLowerCase().includes('readme')
}

export default function FileViewerContent({ data }: FileViewerContentProps) {
  const [content, setContent] = useState<string | null>(data.content || null)
  const [loading, setLoading] = useState(!data.content && data.projectId && data.fileId)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const { filename, mimeType, source, projectId, fileId } = data
  const language = getLanguageFromFilename(filename)
  const isMarkdown = language === 'markdown'
  const isPdf = isPdfFile(filename, mimeType)
  const isImage = isImageFile(filename, mimeType)
  const isWord = isWordFile(filename, mimeType)
  const isText = isTextFile(filename, mimeType)

  // Fetch content if not provided
  useEffect(() => {
    if (content || !projectId || !fileId) return

    const fetchContent = async () => {
      try {
        setLoading(true)
        setError(null)
        const result = await projectsApi.getFileContent(projectId, fileId)
        setContent(result.content)
      } catch (err) {
        console.error('Failed to fetch file content:', err)
        setError('Failed to load file content')
      } finally {
        setLoading(false)
      }
    }

    fetchContent()
  }, [projectId, fileId, content])

  const handleCopy = async () => {
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  const handleDownload = () => {
    if (projectId && fileId) {
      window.open(projectsApi.downloadFile(projectId, fileId), '_blank')
    } else if (content) {
      const blob = new Blob([content], { type: mimeType || 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    }
  }

  // Line numbers for code view
  const lineCount = useMemo(() => {
    if (!content) return 0
    return content.split('\n').length
  }, [content])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-canvas-muted">
        <Loader2 className="animate-spin mr-2" size={20} />
        Loading file...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-red-400">
        <AlertCircle size={48} className="mb-4 opacity-50" />
        <p>{error}</p>
        {projectId && fileId && (
          <button
            onClick={handleDownload}
            className="mt-4 px-4 py-2 bg-canvas-surface hover:bg-canvas-elevated rounded-lg text-white transition-colors flex items-center gap-2"
          >
            <Download size={16} />
            Download Instead
          </button>
        )}
      </div>
    )
  }

  // PDF viewer
  if (isPdf && content) {
    // For blob URLs, use object tag; for regular URLs, can use iframe
    const isBlobUrl = content.startsWith('blob:')

    return (
      <div className="flex flex-col h-full bg-canvas-bg">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-canvas-border bg-canvas-surface/50">
          <div className="flex items-center gap-3">
            <FileText size={18} className="text-red-400" />
            <span className="text-white font-medium">{filename}</span>
            <span className="text-xs text-canvas-muted px-2 py-0.5 bg-canvas-elevated rounded">
              PDF
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={content}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 hover:bg-canvas-elevated rounded-lg text-canvas-muted hover:text-white transition-colors"
              title="Open in new tab"
            >
              <FileText size={18} />
            </a>
            <a
              href={content}
              download={filename}
              className="p-2 hover:bg-canvas-elevated rounded-lg text-canvas-muted hover:text-white transition-colors"
              title="Download file"
            >
              <Download size={18} />
            </a>
          </div>
        </div>
        {/* PDF Embed */}
        <div className="flex-1 overflow-hidden bg-gray-800">
          <object
            data={content}
            type="application/pdf"
            className="w-full h-full"
          >
            <div className="flex flex-col items-center justify-center h-full text-canvas-muted p-8">
              <FileText size={64} className="mb-4 opacity-30" />
              <p className="text-lg mb-2">PDF Preview not available</p>
              <p className="text-sm text-center mb-4">Your browser may not support inline PDF viewing</p>
              <a
                href={content}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2 bg-purple-500 hover:bg-purple-600 rounded-lg text-white transition-colors"
              >
                Open PDF in New Tab
              </a>
            </div>
          </object>
        </div>
      </div>
    )
  }

  // Image viewer
  if (isImage && content) {
    return (
      <div className="flex flex-col h-full bg-canvas-bg">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-canvas-border bg-canvas-surface/50">
          <div className="flex items-center gap-3">
            <FileText size={18} className="text-green-400" />
            <span className="text-white font-medium">{filename}</span>
            <span className="text-xs text-canvas-muted px-2 py-0.5 bg-canvas-elevated rounded">
              Image
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={content}
              download={filename}
              className="p-2 hover:bg-canvas-elevated rounded-lg text-canvas-muted hover:text-white transition-colors"
              title="Download file"
            >
              <Download size={18} />
            </a>
          </div>
        </div>
        {/* Image Display */}
        <div className="flex-1 overflow-auto flex items-center justify-center p-4 bg-gray-900">
          <img
            src={content}
            alt={filename}
            className="max-w-full max-h-full object-contain"
          />
        </div>
      </div>
    )
  }

  // Word document - show download prompt
  if (isWord) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-canvas-muted">
        <FileText size={64} className="mb-4 opacity-30 text-blue-400" />
        <p className="text-lg">Word Document</p>
        <p className="text-sm mt-1">{filename}</p>
        <p className="text-sm text-canvas-muted mt-2 text-center max-w-md">
          Word documents cannot be previewed in the browser.
          Download to view in Microsoft Word or another compatible app.
        </p>
        <a
          href={content || '#'}
          download={filename}
          className="mt-6 px-4 py-2 bg-blue-500 hover:bg-blue-600 rounded-lg text-white transition-colors flex items-center gap-2"
        >
          <Download size={16} />
          Download Document
        </a>
      </div>
    )
  }

  if (!isText) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-canvas-muted">
        <FileText size={64} className="mb-4 opacity-30" />
        <p className="text-lg">Binary file</p>
        <p className="text-sm mt-1">{filename}</p>
        <p className="text-sm text-canvas-muted mt-1">{mimeType || 'Unknown type'}</p>
        <a
          href={content || '#'}
          download={filename}
          className="mt-6 px-4 py-2 bg-purple-500 hover:bg-purple-600 rounded-lg text-white transition-colors flex items-center gap-2"
        >
          <Download size={16} />
          Download File
        </a>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-canvas-border bg-canvas-surface/50">
        <div className="flex items-center gap-3">
          <FileText size={18} className="text-blue-400" />
          <span className="text-white font-medium">{filename}</span>
          <span className="text-xs text-canvas-muted px-2 py-0.5 bg-canvas-elevated rounded">
            {language}
          </span>
          {source === 'project' && (
            <span className="text-xs text-purple-400">from project</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="p-2 hover:bg-canvas-elevated rounded-lg text-canvas-muted hover:text-white transition-colors"
            title="Copy to clipboard"
          >
            {copied ? <Check size={18} className="text-green-400" /> : <Copy size={18} />}
          </button>
          <button
            onClick={handleDownload}
            className="p-2 hover:bg-canvas-elevated rounded-lg text-canvas-muted hover:text-white transition-colors"
            title="Download file"
          >
            <Download size={18} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto custom-scrollbar" data-scrollable="true">
        {isMarkdown ? (
          <div className="p-6 prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content || ''}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="flex text-sm font-mono">
            {/* Line numbers */}
            <div className="flex-shrink-0 px-3 py-4 bg-canvas-surface/30 text-canvas-muted text-right select-none border-r border-canvas-border">
              {Array.from({ length: lineCount }, (_, i) => (
                <div key={i + 1} className="leading-6">
                  {i + 1}
                </div>
              ))}
            </div>
            {/* Code content */}
            <pre className="flex-1 p-4 overflow-x-auto">
              <code className="text-white/90 leading-6 whitespace-pre">
                {content}
              </code>
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
