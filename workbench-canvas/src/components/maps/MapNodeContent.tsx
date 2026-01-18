import type { MapNodeContent as MapNodeContentType } from '../../types'

interface MapNodeContentProps {
  content: MapNodeContentType
}

export default function MapNodeContent({ content }: MapNodeContentProps) {
  switch (content.type) {
    case 'text':
      return (
        <div className="p-3 text-sm text-gray-200 whitespace-pre-wrap break-words overflow-hidden h-full">
          {content.data.text || <span className="text-gray-500 italic">Empty node</span>}
        </div>
      )

    case 'code':
      return (
        <div className="p-2 h-full overflow-hidden">
          <pre className="text-xs text-green-400 font-mono bg-gray-900/50 rounded p-2 overflow-auto h-full">
            <code>{content.data.code || '// No code'}</code>
          </pre>
          {content.data.language && (
            <span className="absolute bottom-1 right-2 text-[10px] text-gray-500 uppercase">
              {content.data.language}
            </span>
          )}
        </div>
      )

    case 'image':
      return (
        <div className="p-1 h-full flex items-center justify-center">
          {content.data.imageUrl ? (
            <img
              src={content.data.imageUrl}
              alt=""
              className="max-w-full max-h-full object-contain rounded"
            />
          ) : (
            <span className="text-gray-500 text-sm">No image</span>
          )}
        </div>
      )

    case 'embed':
      return (
        <div className="p-2 h-full flex items-center justify-center text-gray-400 text-sm">
          Embed: {content.data.embedType || 'Unknown'}
        </div>
      )

    default:
      return (
        <div className="p-3 text-gray-500 text-sm">
          Unknown content type
        </div>
      )
  }
}
