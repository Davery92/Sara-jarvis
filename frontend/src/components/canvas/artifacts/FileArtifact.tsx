/**
 * File Artifact Component
 *
 * Viewer for generated downloadable files (Word/PDF). Shows a file card with a
 * download button. PDFs preview inline via the browser's object viewer; docx
 * shows metadata + the source markdown it was generated from.
 */
import React, { useState } from 'react';
import { FileText, Download, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Artifact, FileContent } from '../types';
import { APP_CONFIG } from '../../../config';

interface FileArtifactProps {
  artifact: Artifact;
}

function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export const FileArtifact: React.FC<FileArtifactProps> = ({ artifact }) => {
  const content = artifact.content as FileContent;
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // A saved file artifact has a real id (download streams from the backend);
  // an unsaved/pending one can't be downloaded.
  const canDownload =
    !!artifact.id && !artifact.id.startsWith('pending-') && !!content.storage_key;
  const isPdf = content.format === 'pdf' || content.mime === 'application/pdf';

  const fetchBlob = async (): Promise<Blob> => {
    const res = await fetch(`${APP_CONFIG.apiUrl}/api/artifacts/${artifact.id}/download`, {
      credentials: 'include',
    });
    if (!res.ok) throw new Error(`Download failed (${res.status})`);
    return res.blob();
  };

  const handleDownload = async () => {
    if (!canDownload) return;
    setDownloading(true);
    setError(null);
    try {
      const blob = await fetchBlob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = content.filename || 'document';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message || 'Download failed');
    } finally {
      setDownloading(false);
    }
  };

  const handlePreview = async () => {
    if (!canDownload || previewUrl) return;
    try {
      const blob = await fetchBlob();
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e: any) {
      setError(e.message || 'Preview failed');
    }
  };

  return (
    <div className="h-full flex flex-col p-6 gap-4 overflow-auto">
      {/* File card */}
      <div className="flex items-center gap-4 p-4 rounded-lg bg-gray-800/60 border border-gray-700">
        <div className="flex-shrink-0 w-12 h-12 rounded-lg bg-teal-500/15 flex items-center justify-center">
          <FileText className="text-teal-400" size={24} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-white font-medium truncate">{content.filename}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {(content.format || '').toUpperCase()} · {formatBytes(content.size_bytes)}
          </p>
        </div>
        <button
          onClick={handleDownload}
          disabled={!canDownload || downloading}
          className="flex items-center gap-2 px-4 py-2 rounded-md bg-teal-600 hover:bg-teal-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium"
        >
          {downloading ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
          Download
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {!canDownload && (
        <p className="text-sm text-gray-500">
          This file is still being saved. It'll be downloadable once it lands in the Studio.
        </p>
      )}

      {/* Preview */}
      {isPdf && canDownload ? (
        previewUrl ? (
          <object data={previewUrl} type="application/pdf" className="flex-1 w-full min-h-[400px] rounded-md border border-gray-700">
            <p className="text-sm text-gray-400 p-4">
              Inline preview unavailable — use Download.
            </p>
          </object>
        ) : (
          <button
            onClick={handlePreview}
            className="self-start text-sm text-teal-400 hover:text-teal-300 underline"
          >
            Load PDF preview
          </button>
        )
      ) : content.source_markdown ? (
        <div className="flex-1 min-h-0">
          <p className="text-xs uppercase tracking-wide text-gray-500 mb-2">Source</p>
          <div className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content.source_markdown}</ReactMarkdown>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default FileArtifact;
