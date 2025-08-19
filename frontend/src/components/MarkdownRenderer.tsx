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
                <div className="my-4 p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-700">
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
              <pre className="bg-gray-100 rounded-lg p-4 overflow-x-auto my-2">
                <code className={className} {...props}>
                  {children}
                </code>
              </pre>
            )
          }
          
          // Inline code
          return (
            <code className="bg-gray-100 px-1 py-0.5 rounded text-sm" {...props}>
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
            <blockquote className="border-l-4 border-gray-300 pl-4 italic text-gray-700 mb-2">
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
              className="text-blue-600 hover:text-blue-800 underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          )
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto mb-2">
              <table className="min-w-full border border-gray-300 rounded-lg">
                {children}
              </table>
            </div>
          )
        },
        thead({ children }) {
          return <thead className="bg-gray-50">{children}</thead>
        },
        tbody({ children }) {
          return <tbody>{children}</tbody>
        },
        tr({ children }) {
          return <tr className="border-b border-gray-200">{children}</tr>
        },
        th({ children }) {
          return (
            <th className="px-4 py-2 text-left font-medium text-gray-900 border-r border-gray-300 last:border-r-0">
              {children}
            </th>
          )
        },
        td({ children }) {
          return (
            <td className="px-4 py-2 text-gray-700 border-r border-gray-300 last:border-r-0">
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