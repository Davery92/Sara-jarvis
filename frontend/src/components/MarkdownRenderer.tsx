import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import MermaidDiagram from './MermaidDiagram'
import ErrorBoundary from './ErrorBoundary'

interface MarkdownRendererProps {
  content: string
  className?: string
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className = '' }) => {
  return (
    <ReactMarkdown
      className={className}
      remarkPlugins={[remarkGfm]}
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
      {content}
    </ReactMarkdown>
  )
}

export default MarkdownRenderer