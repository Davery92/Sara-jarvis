/**
 * Document Artifact Component
 *
 * Rich text document viewer and editor
 * Supports Markdown and HTML content
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Copy, Check, FileText, Code } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Artifact, DocumentContent, ArtifactContent } from '../types';

interface DocumentArtifactProps {
  artifact: Artifact;
  isEditing?: boolean;
  onUpdate?: (content: ArtifactContent) => Promise<void>;
}

export const DocumentArtifact: React.FC<DocumentArtifactProps> = ({
  artifact,
  isEditing = false,
  onUpdate,
}) => {
  const content = artifact.content as DocumentContent;
  const [documentContent, setDocumentContent] = useState(content.content);
  const [viewMode, setViewMode] = useState<'preview' | 'source'>('preview');
  const [copied, setCopied] = useState(false);

  // Update local state when artifact changes
  useEffect(() => {
    const newContent = artifact.content as DocumentContent;
    setDocumentContent(newContent.content);
  }, [artifact]);

  // Save changes when editing stops
  useEffect(() => {
    if (!isEditing && documentContent !== content.content && onUpdate) {
      onUpdate({
        ...content,
        content: documentContent,
      });
    }
  }, [isEditing, documentContent, content, onUpdate]);

  // Copy content to clipboard
  const copyContent = useCallback(() => {
    navigator.clipboard.writeText(documentContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [documentContent]);

  // Markdown components for rendering
  const markdownComponents = {
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';

      if (!inline && language) {
        return (
          <pre className="my-4 rounded-lg bg-gray-950 border border-gray-800 p-4 overflow-x-auto">
            <code className={`${className} text-gray-100 text-sm`} {...props}>
              {String(children).replace(/\n$/, '')}
            </code>
          </pre>
        );
      }

      return (
        <code
          className="px-1.5 py-0.5 bg-gray-800 rounded text-pink-400 text-sm"
          {...props}
        >
          {children}
        </code>
      );
    },
    // Custom styling for other elements
    h1: ({ children }: any) => (
      <h1 className="text-2xl font-bold text-white mt-6 mb-4 pb-2 border-b border-gray-700">
        {children}
      </h1>
    ),
    h2: ({ children }: any) => (
      <h2 className="text-xl font-bold text-white mt-5 mb-3">
        {children}
      </h2>
    ),
    h3: ({ children }: any) => (
      <h3 className="text-lg font-semibold text-white mt-4 mb-2">
        {children}
      </h3>
    ),
    p: ({ children }: any) => (
      <p className="text-gray-300 leading-relaxed mb-4">
        {children}
      </p>
    ),
    ul: ({ children }: any) => (
      <ul className="list-disc list-inside text-gray-300 mb-4 space-y-1">
        {children}
      </ul>
    ),
    ol: ({ children }: any) => (
      <ol className="list-decimal list-inside text-gray-300 mb-4 space-y-1">
        {children}
      </ol>
    ),
    blockquote: ({ children }: any) => (
      <blockquote className="border-l-4 border-blue-500 pl-4 italic text-gray-400 my-4">
        {children}
      </blockquote>
    ),
    a: ({ href, children }: any) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-400 hover:text-blue-300 underline"
      >
        {children}
      </a>
    ),
    table: ({ children }: any) => (
      <div className="overflow-x-auto my-4">
        <table className="min-w-full border border-gray-700 rounded">
          {children}
        </table>
      </div>
    ),
    th: ({ children }: any) => (
      <th className="px-4 py-2 bg-gray-800 border-b border-gray-700 text-left text-white font-semibold">
        {children}
      </th>
    ),
    td: ({ children }: any) => (
      <td className="px-4 py-2 border-b border-gray-700 text-gray-300">
        {children}
      </td>
    ),
  };

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode('preview')}
            className={`p-2 rounded flex items-center gap-2 text-sm ${
              viewMode === 'preview'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            <FileText size={16} />
            Preview
          </button>
          <button
            onClick={() => setViewMode('source')}
            className={`p-2 rounded flex items-center gap-2 text-sm ${
              viewMode === 'source'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white hover:bg-gray-700'
            }`}
          >
            <Code size={16} />
            Source
          </button>
        </div>

        <button
          onClick={copyContent}
          className="p-2 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
          title="Copy content"
        >
          {copied ? <Check size={16} /> : <Copy size={16} />}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isEditing ? (
          // Editor
          <textarea
            value={documentContent}
            onChange={(e) => setDocumentContent(e.target.value)}
            className="w-full h-full p-6 bg-gray-950 text-gray-100 font-mono text-sm resize-none focus:outline-none"
            spellCheck={false}
            placeholder="Enter markdown content..."
          />
        ) : viewMode === 'source' ? (
          // Source view
          <pre className="p-6 bg-gray-950 text-gray-300 font-mono text-sm whitespace-pre-wrap">
            {documentContent}
          </pre>
        ) : (
          // Preview
          <div className="p-6 bg-gray-900 prose prose-invert max-w-none">
            {content.format === 'html' ? (
              <div dangerouslySetInnerHTML={{ __html: documentContent }} />
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {documentContent}
              </ReactMarkdown>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default DocumentArtifact;
