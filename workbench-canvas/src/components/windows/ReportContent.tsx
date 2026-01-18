import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { FileText } from 'lucide-react'

export interface ReportWindowData {
  title?: string
  content: string
}

interface ReportContentProps {
  data: ReportWindowData
  windowId: string
}

export default function ReportContent({ data }: ReportContentProps) {
  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      {/* Header */}
      {data.title && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-canvas-border">
          <FileText size={16} className="text-purple-500" />
          <span className="text-sm text-white font-medium truncate">{data.title}</span>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
        <div className="markdown-content prose prose-invert prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.content || ''}</ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
