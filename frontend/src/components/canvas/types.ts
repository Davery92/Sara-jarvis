/**
 * Canvas/Artifacts Type Definitions
 */

export type ArtifactType = 'code' | 'diagram' | 'document' | 'canvas' | 'table' | 'mindmap' | 'note' | 'file';

export interface Artifact {
  id: string;
  user_id: string;
  artifact_type: ArtifactType;
  title: string;
  content: ArtifactContent;
  metadata: ArtifactMetadata | null;
  conversation_id: string | null;
  episode_id: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

export type ArtifactContent =
  | CodeContent
  | DiagramContent
  | DocumentContent
  | CanvasContent
  | TableContent
  | MindmapContent
  | NoteContent
  | FileContent;

// Generated downloadable file (Word/PDF) — see document_generate tool.
export interface FileContent {
  storage_key?: string;
  filename: string;
  mime: string;
  size_bytes: number;
  format: 'docx' | 'pdf';
  source_markdown?: string;
  artifact_id?: string;
}

export interface CodeContent {
  code: string;
  language: string;
  output?: string;
  error?: string;
}

export interface DiagramContent {
  source: string;
  type: 'mermaid' | 'excalidraw' | 'svg';
}

export interface DocumentContent {
  content: string;
  format: 'markdown' | 'html';
}

export interface CanvasContent {
  elements: any[];
  viewport: {
    x: number;
    y: number;
    zoom: number;
  };
}

export interface TableContent {
  columns: TableColumn[];
  rows: Record<string, any>[];
}

export interface TableColumn {
  key: string;
  title: string;
  type: 'string' | 'number' | 'boolean' | 'date';
}

export interface ArtifactMetadata {
  version?: number;
  language?: string;
  lastExecuted?: string;
  [key: string]: any;
}

export type CanvasPanelMode = 'docked' | 'floating' | 'fullscreen';

export interface CanvasPanelState {
  isOpen: boolean;
  mode: CanvasPanelMode;
  activeArtifactId: string | null;
  width: number;
}

// Mindmap types for ReactFlow-based interactive mindmaps
export interface MindmapNode {
  id: string;
  type: 'topic' | 'idea' | 'task' | 'note';
  position: { x: number; y: number };
  data: {
    label: string;
    color?: string;
    notes?: string;
  };
}

export interface MindmapEdge {
  id: string;
  source: string;
  target: string;
  type?: 'default' | 'smoothstep';
}

export interface MindmapContent {
  nodes: MindmapNode[];
  edges: MindmapEdge[];
  viewport: {
    x: number;
    y: number;
    zoom: number;
  };
}

// Note content for editing existing notes in the canvas
export interface NoteContent {
  note_id: string;
  title: string;
  content: string;
  folder_id?: string;
}

// Canvas command from SSE for tool-driven canvas control
export interface CanvasCommand {
  canvas_command: 'open' | 'update' | 'close';
  artifact_type?: ArtifactType;
  title?: string;
  content?: ArtifactContent;
  note_id?: string;
  /** Set when the backend persisted the artifact row (canvas_open now does). */
  artifact_id?: string;
}
