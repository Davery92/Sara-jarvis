import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import MermaidDiagram from './MermaidDiagram'
import ErrorBoundary from './ErrorBoundary'
import { APP_CONFIG } from '../config'

interface MarkdownRendererProps {
  content: string
  className?: string
}

/**
 * Normalize LaTeX math delimiters to the $/$$ format that remark-math expects.
 * Handles: \[ \], \( \), and bare [ ... ] lines containing LaTeX commands.
 */
function normalizeMathDelimiters(text: string): string {
  // 1. Convert \[ ... \] (display math) to $$ ... $$  — may span multiple lines
  let result = text.replace(/\\\[([^]*?)\\\]/g, (_match, inner) => {
    return `$$${inner}$$`
  })

  // 2. Convert \( ... \) (inline math) to $ ... $
  result = result.replace(/\\\(([^]*?)\\\)/g, (_match, inner) => {
    return `$${inner}$`
  })

  // 3. Convert bare [ ... ] lines that contain LaTeX commands
  //    Match lines that are just [ <content> ] where content has LaTeX markers
  const latexPattern = /\\(?:frac|text|bar|alpha|beta|gamma|delta|sigma|mu|pi|theta|lambda|omega|sum|prod|int|lim|infty|partial|nabla|sqrt|vec|hat|dot|ddot|mathbf|mathrm|mathcal|left|right|begin|end|approx|equiv|neq|leq|geq|cdot|times|div|pm|mp|quad|qquad|hbar|ell|forall|exists|in|notin|subset|cup|cap)/
  result = result.replace(/^(\[ )(.*?)( \])$/gm, (_match, open, inner, close) => {
    if (latexPattern.test(inner)) {
      return `$$${inner}$$`
    }
    return _match
  })

  return result
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  const processedContent = normalizeMathDelimiters(content)

  return (
    <ReactMarkdown
      className={className}
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        code({ node, inline, className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || '')
          const language = match ? match[1] : ''
          
          // Handle Mermaid diagrams
          if (language === 'mermaid') {
            const chart = String(children).replace(/\n$/, '')
            const id = `mermaid-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
            return (
              <ErrorBoundary fallback={
                <div className="my-4 p-4 bg-yellow-900/20 border border-yellow-600 rounded-lg text-yellow-400">
                  <strong>Mermaid Diagram Error</strong>
                  <p className="text-sm mt-1">Unable to render the diagram. This might be due to syntax issues or browser compatibility.</p>
                </div>
              }>
                <MermaidDiagram chart={chart} id={id} />
              </ErrorBoundary>
            )
          }
          
          // Handle other code blocks
          if (!inline && match) {
            return (
              <pre className="bg-[#18181b] border border-[#3f3f46] rounded-lg p-4 overflow-x-auto my-2">
                <code className={`${className} text-[#f8fafc]`} {...props}>
                  {children}
                </code>
              </pre>
            )
          }
          
          // Inline code
          return (
            <code className="bg-[#3f3f46] text-[#f8fafc] px-1 py-0.5 rounded text-sm" {...props}>
              {children}
            </code>
          )
        },
        pre({ children }) {
          return <>{children}</>
        },
        p({ children }) {
          return <p className="mb-2 last:mb-0">{children}</p>
        },
        h1({ children }) {
          return <h1 className="text-xl font-bold mb-3">{children}</h1>
        },
        h2({ children }) {
          return <h2 className="text-lg font-semibold mb-2">{children}</h2>
        },
        h3({ children }) {
          return <h3 className="text-base font-medium mb-2">{children}</h3>
        },
        ul({ children }) {
          return <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>
        },
        ol({ children }) {
          return <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>
        },
        li({ children }) {
          return <li className="ml-2">{children}</li>
        },
        blockquote({ children }) {
          return (
            <blockquote className="border-l-4 border-[#0d7ff2] pl-4 italic text-[#a1a1aa] mb-2">
              {children}
            </blockquote>
          )
        },
        strong({ children }) {
          return <strong className="font-semibold">{children}</strong>
        },
        em({ children }) {
          return <em className="italic">{children}</em>
        },
        a({ href, children }) {
          // Internal API links (e.g. /email/.../download) — fetch with auth cookie
          if (href && (href.startsWith('/email/') || href.startsWith('/api/'))) {
            const handleApiDownload = async (e: React.MouseEvent) => {
              e.preventDefault()
              try {
                const apiBase = APP_CONFIG.apiUrl
                const res = await fetch(`${apiBase}${href}`, { credentials: 'include' })
                if (!res.ok) throw new Error(`Download failed: ${res.status}`)
                const blob = await res.blob()
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                const disposition = res.headers.get('Content-Disposition')
                const filenameMatch = disposition?.match(/filename="?([^"]+)"?/)
                a.download = filenameMatch?.[1] || href.split('/').pop() || 'download'
                document.body.appendChild(a)
                a.click()
                document.body.removeChild(a)
                URL.revokeObjectURL(url)
              } catch (err) {
                console.error('Download failed:', err)
              }
            }
            return (
              <a
                href={href}
                onClick={handleApiDownload}
                className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-blue-600/20 border border-blue-500/30 rounded text-blue-400 hover:bg-blue-600/30 cursor-pointer transition-colors no-underline"
                title="Click to download"
              >
                📎 {children}
              </a>
            )
          }
          return (
            <a
              href={href}
              className="text-[#0d7ff2] hover:text-[#0c6fd1] underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          )
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto my-4">
              <table className="w-full border-collapse border border-gray-600 bg-gray-800/50 rounded-lg">
                {children}
              </table>
            </div>
          )
        },
        thead({ children }) {
          return <thead className="bg-gray-700/50">{children}</thead>
        },
        tbody({ children }) {
          return <tbody>{children}</tbody>
        },
        tr({ children }) {
          return <tr className="border-b border-gray-600 hover:bg-gray-700/30">{children}</tr>
        },
        th({ children }) {
          return (
            <th className="border border-gray-600 px-3 py-2 text-left font-semibold text-teal-300">
              {children}
            </th>
          )
        },
        td({ children }) {
          return (
            <td className="border border-gray-600 px-3 py-2 text-gray-300">
              {children}
            </td>
          )
        }
      }}
    >
      {processedContent}
    </ReactMarkdown>
  )
}

export default MarkdownRenderer
