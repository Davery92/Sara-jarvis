import { useState, useEffect } from 'react'
import { X, Type, Code, Image, Link } from 'lucide-react'
import { useCanvasStore } from '../../store/canvasStore'
import type { MapNodeContent } from '../../types'

interface MapNodeEditorProps {
  mapId: string
  nodeId: string
  initialContent: MapNodeContent
  onClose: () => void
}

type ContentType = 'text' | 'code' | 'image' | 'embed'

export default function MapNodeEditor({ mapId, nodeId, initialContent, onClose }: MapNodeEditorProps) {
  const { updateMapNode } = useCanvasStore()

  const [contentType, setContentType] = useState<ContentType>(initialContent.type)
  const [text, setText] = useState(initialContent.data.text || '')
  const [code, setCode] = useState(initialContent.data.code || '')
  const [language, setLanguage] = useState(initialContent.data.language || 'javascript')
  const [imageUrl, setImageUrl] = useState(initialContent.data.imageUrl || '')
  const [embedUrl, setEmbedUrl] = useState(initialContent.data.embedUrl || '')

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const handleSave = () => {
    let newContent: MapNodeContent

    switch (contentType) {
      case 'text':
        newContent = { type: 'text', data: { text } }
        break
      case 'code':
        newContent = { type: 'code', data: { code, language } }
        break
      case 'image':
        newContent = { type: 'image', data: { imageUrl } }
        break
      case 'embed':
        newContent = { type: 'embed', data: { embedUrl } }
        break
      default:
        newContent = { type: 'text', data: { text } }
    }

    updateMapNode(mapId, nodeId, { content: newContent })
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[100]" onClick={onClose}>
      <div
        className="bg-gray-800 border border-gray-600 rounded-xl shadow-2xl w-[500px] max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-white">Edit Node</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content Type Tabs */}
        <div className="flex border-b border-gray-700">
          <button
            onClick={() => setContentType('text')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
              contentType === 'text'
                ? 'text-teal-400 border-b-2 border-teal-400 bg-gray-700/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-700/30'
            }`}
          >
            <Type size={16} />
            Text
          </button>
          <button
            onClick={() => setContentType('code')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
              contentType === 'code'
                ? 'text-teal-400 border-b-2 border-teal-400 bg-gray-700/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-700/30'
            }`}
          >
            <Code size={16} />
            Code
          </button>
          <button
            onClick={() => setContentType('image')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
              contentType === 'image'
                ? 'text-teal-400 border-b-2 border-teal-400 bg-gray-700/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-700/30'
            }`}
          >
            <Image size={16} />
            Image
          </button>
          <button
            onClick={() => setContentType('embed')}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
              contentType === 'embed'
                ? 'text-teal-400 border-b-2 border-teal-400 bg-gray-700/50'
                : 'text-gray-400 hover:text-white hover:bg-gray-700/30'
            }`}
          >
            <Link size={16} />
            Embed
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-4">
          {contentType === 'text' && (
            <div>
              <label className="block text-sm text-gray-400 mb-2">Text Content</label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Enter text content..."
                className="w-full h-40 px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                autoFocus
              />
            </div>
          )}

          {contentType === 'code' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-2">Language</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                >
                  <option value="javascript">JavaScript</option>
                  <option value="typescript">TypeScript</option>
                  <option value="python">Python</option>
                  <option value="go">Go</option>
                  <option value="rust">Rust</option>
                  <option value="java">Java</option>
                  <option value="c">C</option>
                  <option value="cpp">C++</option>
                  <option value="csharp">C#</option>
                  <option value="ruby">Ruby</option>
                  <option value="php">PHP</option>
                  <option value="swift">Swift</option>
                  <option value="kotlin">Kotlin</option>
                  <option value="sql">SQL</option>
                  <option value="html">HTML</option>
                  <option value="css">CSS</option>
                  <option value="json">JSON</option>
                  <option value="yaml">YAML</option>
                  <option value="markdown">Markdown</option>
                  <option value="bash">Bash</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-2">Code</label>
                <textarea
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="Enter code..."
                  className="w-full h-40 px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white font-mono text-sm placeholder-gray-500 resize-none focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                  autoFocus
                />
              </div>
            </div>
          )}

          {contentType === 'image' && (
            <div>
              <label className="block text-sm text-gray-400 mb-2">Image URL</label>
              <input
                type="text"
                value={imageUrl}
                onChange={(e) => setImageUrl(e.target.value)}
                placeholder="https://example.com/image.png"
                className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                autoFocus
              />
              {imageUrl && (
                <div className="mt-4 border border-gray-600 rounded-lg overflow-hidden">
                  <img
                    src={imageUrl}
                    alt="Preview"
                    className="w-full h-40 object-contain bg-gray-900"
                    onError={(e) => {
                      ;(e.target as HTMLImageElement).style.display = 'none'
                    }}
                  />
                </div>
              )}
            </div>
          )}

          {contentType === 'embed' && (
            <div>
              <label className="block text-sm text-gray-400 mb-2">Embed URL</label>
              <input
                type="text"
                value={embedUrl}
                onChange={(e) => setEmbedUrl(e.target.value)}
                placeholder="https://example.com/embed"
                className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                autoFocus
              />
              <p className="mt-2 text-xs text-gray-500">
                Supported: YouTube, Vimeo, CodePen, and other embeddable content
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-4 border-t border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-500 transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
