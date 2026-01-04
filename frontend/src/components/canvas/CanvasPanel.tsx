/**
 * Canvas Panel Component
 *
 * Slide-out panel for displaying and editing artifacts
 * Supports docked, floating, and fullscreen modes
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Maximize2,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  Pin,
  Trash2,
  Copy,
  Download,
} from 'lucide-react';
import { Artifact, CanvasPanelMode } from './types';
import { ArtifactRenderer } from './ArtifactRenderer';
import { useArtifacts } from './hooks/useArtifacts';

interface CanvasPanelProps {
  isOpen: boolean;
  onClose: () => void;
  artifactId: string | null;
  mode?: CanvasPanelMode;
  onModeChange?: (mode: CanvasPanelMode) => void;
  conversationId?: string;
  /** Direct artifact content for notes/pending content (bypasses ID lookup) */
  directArtifact?: Artifact | null;
  /** Width percentage for docked mode (controlled by parent resize) */
  width?: number;
  /** Whether the panel is currently being resized */
  isResizing?: boolean;
}

export const CanvasPanel: React.FC<CanvasPanelProps> = ({
  isOpen,
  onClose,
  artifactId,
  mode = 'docked',
  onModeChange,
  conversationId,
  directArtifact,
  width = 50,
  isResizing = false,
}) => {
  const { artifacts, updateArtifact, deleteArtifact, getArtifact } = useArtifacts({
    conversationId,
  });

  const [currentMode, setCurrentMode] = useState<CanvasPanelMode>(mode);
  const [isEditing, setIsEditing] = useState(false);

  // Use directArtifact if provided, otherwise look up by ID
  const artifact = directArtifact || (artifactId ? getArtifact(artifactId) : null);

  // Sync mode with prop
  useEffect(() => {
    setCurrentMode(mode);
  }, [mode]);

  const handleModeChange = useCallback((newMode: CanvasPanelMode) => {
    setCurrentMode(newMode);
    onModeChange?.(newMode);
  }, [onModeChange]);

  const handlePin = useCallback(async () => {
    if (artifact) {
      await updateArtifact(artifact.id, { is_pinned: !artifact.is_pinned });
    }
  }, [artifact, updateArtifact]);

  const handleDelete = useCallback(async () => {
    if (artifact && confirm('Delete this artifact?')) {
      await deleteArtifact(artifact.id);
      onClose();
    }
  }, [artifact, deleteArtifact, onClose]);

  const handleCopy = useCallback(() => {
    if (artifact) {
      const content = artifact.artifact_type === 'code'
        ? (artifact.content as any).code
        : JSON.stringify(artifact.content, null, 2);
      navigator.clipboard.writeText(content);
    }
  }, [artifact]);

  const handleDownload = useCallback(() => {
    if (!artifact) return;

    let content: string;
    let filename: string;
    let mimeType: string;

    switch (artifact.artifact_type) {
      case 'code':
        content = (artifact.content as any).code;
        const ext = getFileExtension((artifact.content as any).language);
        filename = `${artifact.title}.${ext}`;
        mimeType = 'text/plain';
        break;
      case 'diagram':
        content = (artifact.content as any).source;
        filename = `${artifact.title}.md`;
        mimeType = 'text/markdown';
        break;
      case 'document':
        content = (artifact.content as any).content;
        filename = `${artifact.title}.md`;
        mimeType = 'text/markdown';
        break;
      default:
        content = JSON.stringify(artifact.content, null, 2);
        filename = `${artifact.title}.json`;
        mimeType = 'application/json';
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }, [artifact]);

  // Panel position/size classes based on mode
  // Note: 'docked' is now inline (not fixed) to allow side-by-side layout
  // Width is controlled via inline style for docked mode to support resizing
  const panelClasses = {
    docked: 'h-full border-l border-gray-700',
    floating: 'fixed top-20 right-8 w-2/3 max-w-3xl h-[70vh] rounded-lg shadow-2xl',
    fullscreen: 'fixed inset-0 z-50',
  };

  // Check if this is a note artifact (has its own toolbar)
  const isNoteArtifact = artifact?.artifact_type === 'note';

  if (!isOpen) return null;

  // Compute inline style for docked mode width
  const panelStyle = currentMode === 'docked'
    ? { width: `${width}%` }
    : undefined;

  // Disable transition during resize for smooth dragging
  const transitionClass = isResizing ? '' : 'transition-all duration-300';

  return (
    <div
      className={`${panelClasses[currentMode]} bg-gray-900 flex flex-col ${currentMode !== 'docked' ? 'z-40' : ''} ${transitionClass}`}
      style={panelStyle}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <div className="flex items-center gap-3">
          {artifact && (
            <>
              <span className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-400 uppercase">
                {artifact.artifact_type}
              </span>
              <h3 className="text-white font-medium truncate max-w-xs">
                {artifact.title}
              </h3>
              {artifact.is_pinned && (
                <Pin size={14} className="text-blue-400" />
              )}
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Mode toggles */}
          <button
            onClick={() => handleModeChange(currentMode === 'docked' ? 'floating' : 'docked')}
            className="p-2 hover:bg-gray-800 rounded text-gray-400 hover:text-white"
            title={currentMode === 'docked' ? 'Float panel' : 'Dock panel'}
          >
            {currentMode === 'docked' ? <PanelRightOpen size={18} /> : <PanelRightClose size={18} />}
          </button>

          <button
            onClick={() => handleModeChange(currentMode === 'fullscreen' ? 'docked' : 'fullscreen')}
            className="p-2 hover:bg-gray-800 rounded text-gray-400 hover:text-white"
            title={currentMode === 'fullscreen' ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {currentMode === 'fullscreen' ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
          </button>

          <div className="w-px h-6 bg-gray-700" />

          {/* Actions - hidden for notes since they have their own toolbar */}
          {artifact && !isNoteArtifact && (
            <>
              <button
                onClick={handlePin}
                className={`p-2 hover:bg-gray-800 rounded ${artifact.is_pinned ? 'text-blue-400' : 'text-gray-400 hover:text-white'}`}
                title={artifact.is_pinned ? 'Unpin' : 'Pin'}
              >
                <Pin size={18} />
              </button>

              <button
                onClick={handleCopy}
                className="p-2 hover:bg-gray-800 rounded text-gray-400 hover:text-white"
                title="Copy content"
              >
                <Copy size={18} />
              </button>

              <button
                onClick={handleDownload}
                className="p-2 hover:bg-gray-800 rounded text-gray-400 hover:text-white"
                title="Download"
              >
                <Download size={18} />
              </button>

              <button
                onClick={handleDelete}
                className="p-2 hover:bg-gray-800 rounded text-gray-400 hover:text-red-400"
                title="Delete"
              >
                <Trash2 size={18} />
              </button>

              <div className="w-px h-6 bg-gray-700" />
            </>
          )}

          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded text-gray-400 hover:text-white"
            title="Close"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {artifact ? (
          <ArtifactRenderer
            artifact={artifact}
            isEditing={isEditing}
            onUpdate={async (content) => {
              await updateArtifact(artifact.id, { content });
            }}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-500">
            No artifact selected
          </div>
        )}
      </div>

      {/* Footer with edit toggle - hidden for notes (they have their own controls) */}
      {artifact && !isNoteArtifact && (
        <div className="flex items-center justify-between p-3 border-t border-gray-700">
          <span className="text-xs text-gray-500">
            Updated {new Date(artifact.updated_at).toLocaleString()}
          </span>

          <button
            onClick={() => setIsEditing(!isEditing)}
            className={`px-3 py-1 rounded text-sm ${
              isEditing
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:text-white'
            }`}
          >
            {isEditing ? 'Done' : 'Edit'}
          </button>
        </div>
      )}
    </div>
  );
};

// Helper to get file extension from language
function getFileExtension(language: string): string {
  const extensions: Record<string, string> = {
    javascript: 'js',
    typescript: 'ts',
    python: 'py',
    java: 'java',
    cpp: 'cpp',
    c: 'c',
    csharp: 'cs',
    go: 'go',
    rust: 'rs',
    ruby: 'rb',
    php: 'php',
    swift: 'swift',
    kotlin: 'kt',
    html: 'html',
    css: 'css',
    json: 'json',
    yaml: 'yaml',
    markdown: 'md',
    sql: 'sql',
    bash: 'sh',
    shell: 'sh',
  };
  return extensions[language.toLowerCase()] || 'txt';
}

export default CanvasPanel;
