/**
 * Code Artifact Component
 *
 * Displays and edits code with syntax highlighting
 * Supports sandboxed execution for JavaScript
 */
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Play, Copy, Check, AlertCircle } from 'lucide-react';
import { Artifact, CodeContent, ArtifactContent } from '../types';

interface CodeArtifactProps {
  artifact: Artifact;
  isEditing?: boolean;
  onUpdate?: (content: ArtifactContent) => Promise<void>;
}

export const CodeArtifact: React.FC<CodeArtifactProps> = ({
  artifact,
  isEditing = false,
  onUpdate,
}) => {
  const content = artifact.content as CodeContent;
  const [code, setCode] = useState(content.code);
  const [output, setOutput] = useState(content.output || '');
  const [error, setError] = useState(content.error || '');
  const [isRunning, setIsRunning] = useState(false);
  const [copied, setCopied] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Update local state when artifact changes
  useEffect(() => {
    const newContent = artifact.content as CodeContent;
    setCode(newContent.code);
    setOutput(newContent.output || '');
    setError(newContent.error || '');
  }, [artifact]);

  // Save changes when editing stops
  useEffect(() => {
    if (!isEditing && code !== content.code && onUpdate) {
      onUpdate({
        ...content,
        code,
        output,
        error,
      });
    }
  }, [isEditing, code, content, output, error, onUpdate]);

  // Execute code in sandboxed iframe
  const executeCode = useCallback(() => {
    if (!['javascript', 'js', 'html'].includes(content.language.toLowerCase())) {
      setError(`Execution not supported for ${content.language}`);
      return;
    }

    setIsRunning(true);
    setOutput('');
    setError('');

    const isHTML = content.language.toLowerCase() === 'html';

    const html = isHTML
      ? code
      : `
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            body {
              background: #1a1a2e;
              color: #eee;
              font-family: monospace;
              padding: 16px;
              margin: 0;
            }
            .log { margin: 4px 0; }
            .error { color: #ef4444; }
          </style>
        </head>
        <body>
          <div id="output"></div>
          <script>
            const output = document.getElementById('output');
            const originalLog = console.log;
            const originalError = console.error;

            console.log = (...args) => {
              const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a, null, 2) : String(a)).join(' ');
              output.innerHTML += '<div class="log">' + msg + '</div>';
              window.parent.postMessage({ type: 'log', message: msg }, '*');
            };

            console.error = (...args) => {
              const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a, null, 2) : String(a)).join(' ');
              output.innerHTML += '<div class="log error">' + msg + '</div>';
              window.parent.postMessage({ type: 'error', message: msg }, '*');
            };

            try {
              ${code}
              window.parent.postMessage({ type: 'done' }, '*');
            } catch (e) {
              console.error(e.message);
              window.parent.postMessage({ type: 'error', message: e.message }, '*');
            }
          </script>
        </body>
        </html>
      `;

    // Listen for messages from iframe
    const handleMessage = (event: MessageEvent) => {
      if (event.data.type === 'log') {
        setOutput(prev => prev + event.data.message + '\n');
      } else if (event.data.type === 'error') {
        setError(prev => prev + event.data.message + '\n');
      } else if (event.data.type === 'done') {
        setIsRunning(false);
      }
    };

    window.addEventListener('message', handleMessage);

    // Create blob URL for iframe
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);

    if (iframeRef.current) {
      iframeRef.current.src = url;
    }

    // Timeout for execution
    setTimeout(() => {
      setIsRunning(false);
      window.removeEventListener('message', handleMessage);
      URL.revokeObjectURL(url);
    }, 10000);

    return () => {
      window.removeEventListener('message', handleMessage);
      URL.revokeObjectURL(url);
    };
  }, [code, content.language]);

  // Copy code to clipboard
  const copyCode = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  // Check if language supports execution
  const canExecute = ['javascript', 'js', 'html'].includes(content.language.toLowerCase());

  return (
    <div className="flex flex-col h-full">
      {/* Code editor/viewer */}
      <div className="flex-1 overflow-auto">
        {isEditing ? (
          <div className="h-full">
            <textarea
              ref={textareaRef}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full h-full p-4 bg-gray-950 text-gray-100 font-mono text-sm resize-none focus:outline-none"
              spellCheck={false}
              placeholder="Enter code here..."
            />
          </div>
        ) : (
          <div className="relative">
            {/* Action buttons */}
            <div className="absolute top-2 right-2 flex gap-2 z-10">
              <button
                onClick={copyCode}
                className="p-2 bg-gray-800 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
                title="Copy code"
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
              </button>

              {canExecute && (
                <button
                  onClick={executeCode}
                  disabled={isRunning}
                  className="p-2 bg-green-700 hover:bg-green-600 rounded text-white disabled:opacity-50"
                  title="Run code"
                >
                  <Play size={16} />
                </button>
              )}
            </div>

            {/* Syntax highlighted code */}
            <pre className="m-0 p-4 bg-[#0d1117] text-gray-100 text-sm min-h-[200px] overflow-auto font-mono whitespace-pre">
              <code>{code}</code>
            </pre>
          </div>
        )}
      </div>

      {/* Output section */}
      {(output || error || canExecute) && (
        <div className="border-t border-gray-700">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-800">
            <span className="text-sm text-gray-400">Output</span>
            {isRunning && (
              <span className="text-xs text-blue-400">Running...</span>
            )}
          </div>

          <div className="h-48 overflow-auto bg-gray-950 p-4 font-mono text-sm">
            {/* Hidden iframe for sandboxed execution */}
            <iframe
              ref={iframeRef}
              sandbox="allow-scripts"
              className="hidden"
              title="Code execution sandbox"
            />

            {output && (
              <pre className="text-green-400 whitespace-pre-wrap">{output}</pre>
            )}

            {error && (
              <div className="flex items-start gap-2 text-red-400">
                <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
                <pre className="whitespace-pre-wrap">{error}</pre>
              </div>
            )}

            {!output && !error && !isRunning && (
              <span className="text-gray-500">
                {canExecute ? 'Click Run to execute the code' : `Execution not available for ${content.language}`}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default CodeArtifact;
