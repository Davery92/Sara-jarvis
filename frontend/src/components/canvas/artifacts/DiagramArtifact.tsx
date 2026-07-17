/**
 * Diagram Artifact Component
 *
 * Renders and edits Mermaid diagrams
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Copy, Check, RefreshCw, AlertCircle } from 'lucide-react';
import type { MermaidConfig } from 'mermaid';
import { Artifact, DiagramContent, ArtifactContent } from '../types';
import { loadMermaid } from '../../../utils/mermaid';

const MERMAID_DARK_CONFIG: MermaidConfig = {
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    primaryColor: '#3b82f6',
    primaryTextColor: '#fff',
    primaryBorderColor: '#60a5fa',
    lineColor: '#60a5fa',
    secondaryColor: '#1e3a5f',
    tertiaryColor: '#1e293b',
    background: '#0f172a',
    mainBkg: '#1e293b',
    nodeBkg: '#1e3a5f',
    clusterBkg: '#1e293b',
    clusterBorder: '#3b82f6',
    titleColor: '#f1f5f9',
    edgeLabelBackground: '#1e293b',
  },
  flowchart: {
    curve: 'basis',
    padding: 20,
  },
};

interface DiagramArtifactProps {
  artifact: Artifact;
  isEditing?: boolean;
  onUpdate?: (content: ArtifactContent) => Promise<void>;
}

export const DiagramArtifact: React.FC<DiagramArtifactProps> = ({
  artifact,
  isEditing = false,
  onUpdate,
}) => {
  const content = artifact.content as DiagramContent;
  const [source, setSource] = useState(content.source);
  const [svgContent, setSvgContent] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const renderIdRef = useRef(0);

  // Render the diagram
  const renderDiagram = useCallback(async (diagramSource: string) => {
    const renderId = ++renderIdRef.current;

    try {
      const mermaid = await loadMermaid();

      mermaid.initialize(MERMAID_DARK_CONFIG);
      setError(null);

      // Validate syntax first
      const valid = await mermaid.parse(diagramSource, { suppressErrors: true });
      if (!valid) {
        throw new Error('Invalid diagram syntax');
      }

      // Render
      const { svg } = await mermaid.render(`mermaid-${artifact.id}-${renderId}`, diagramSource);

      // Only update if this is still the latest render
      if (renderId === renderIdRef.current) {
        setSvgContent(svg);
      }
    } catch (e: any) {
      if (renderId === renderIdRef.current) {
        setError(e.message || 'Failed to render diagram');
        setSvgContent('');
      }
    }
  }, [artifact.id]);

  // Re-render when source changes
  useEffect(() => {
    renderDiagram(source);
  }, [source, renderDiagram]);

  // Update local state when artifact changes
  useEffect(() => {
    const newContent = artifact.content as DiagramContent;
    setSource(newContent.source);
  }, [artifact]);

  // Save changes when editing stops
  useEffect(() => {
    if (!isEditing && source !== content.source && onUpdate) {
      onUpdate({
        ...content,
        source,
      });
    }
  }, [isEditing, source, content, onUpdate]);

  // Copy source to clipboard
  const copySource = useCallback(() => {
    navigator.clipboard.writeText(source);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [source]);

  return (
    <div className="flex flex-col h-full">
      {isEditing ? (
        // Editor mode - split view
        <div className="flex flex-col lg:flex-row h-full">
          {/* Source editor */}
          <div className="flex-1 border-b lg:border-b-0 lg:border-r border-gray-700">
            <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
              <span className="text-sm text-gray-400">Mermaid Source</span>
              <button
                onClick={copySource}
                className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
                title="Copy source"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
            <textarea
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="w-full h-[calc(100%-40px)] p-4 bg-gray-950 text-gray-100 font-mono text-sm resize-none focus:outline-none"
              spellCheck={false}
              placeholder="Enter Mermaid diagram code..."
            />
          </div>

          {/* Preview */}
          <div className="flex-1 flex flex-col">
            <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
              <span className="text-sm text-gray-400">Preview</span>
              <button
                onClick={() => renderDiagram(source)}
                className="p-1 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
                title="Refresh preview"
              >
                <RefreshCw size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-auto bg-gray-900 p-4">
              {error ? (
                <div className="flex items-start gap-2 text-red-400 p-4">
                  <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
                  <span className="text-sm">{error}</span>
                </div>
              ) : svgContent ? (
                <div
                  ref={containerRef}
                  className="flex items-center justify-center min-h-full"
                  dangerouslySetInnerHTML={{ __html: svgContent }}
                />
              ) : (
                <div className="flex items-center justify-center h-full text-gray-500">
                  Loading preview...
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        // View mode - full diagram
        <div className="h-full overflow-auto bg-gray-900 p-8">
          {error ? (
            <div className="flex flex-col items-center justify-center h-full gap-4">
              <AlertCircle size={48} className="text-red-400" />
              <p className="text-red-400">{error}</p>
              <pre className="mt-4 p-4 bg-gray-800 rounded text-xs text-gray-400 max-w-lg overflow-auto">
                {source}
              </pre>
            </div>
          ) : svgContent ? (
            <div
              ref={containerRef}
              className="flex items-center justify-center min-h-full"
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500">
              Loading diagram...
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default DiagramArtifact;
