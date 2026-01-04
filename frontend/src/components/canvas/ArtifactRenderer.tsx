/**
 * Artifact Renderer Component
 *
 * Routes to the correct artifact viewer based on type
 */
import React from 'react';
import { Artifact, ArtifactContent } from './types';
import { CodeArtifact } from './artifacts/CodeArtifact';
import { DiagramArtifact } from './artifacts/DiagramArtifact';
import { DocumentArtifact } from './artifacts/DocumentArtifact';
import { MindmapArtifact } from './artifacts/MindmapArtifact';
import { NoteArtifact } from './artifacts/NoteArtifact';

interface ArtifactRendererProps {
  artifact: Artifact;
  isEditing?: boolean;
  onUpdate?: (content: ArtifactContent) => Promise<void>;
}

export const ArtifactRenderer: React.FC<ArtifactRendererProps> = ({
  artifact,
  isEditing = false,
  onUpdate,
}) => {
  switch (artifact.artifact_type) {
    case 'code':
      return (
        <CodeArtifact
          artifact={artifact}
          isEditing={isEditing}
          onUpdate={onUpdate}
        />
      );

    case 'diagram':
      return (
        <DiagramArtifact
          artifact={artifact}
          isEditing={isEditing}
          onUpdate={onUpdate}
        />
      );

    case 'document':
      return (
        <DocumentArtifact
          artifact={artifact}
          isEditing={isEditing}
          onUpdate={onUpdate}
        />
      );

    case 'mindmap':
      return (
        <MindmapArtifact
          artifact={artifact}
          isEditing={isEditing}
          onUpdate={onUpdate}
        />
      );

    case 'note':
      return (
        <NoteArtifact
          artifact={artifact}
          isEditing={isEditing}
          onUpdate={onUpdate}
        />
      );

    case 'canvas':
      // Canvas artifact (freeform drawing) - placeholder
      return (
        <div className="flex items-center justify-center h-full text-gray-500 p-8">
          <div className="text-center">
            <p className="text-lg mb-2">Canvas Artifact</p>
            <p className="text-sm">Freeform drawing support coming soon</p>
          </div>
        </div>
      );

    case 'table':
      // Table artifact - placeholder
      return (
        <div className="flex items-center justify-center h-full text-gray-500 p-8">
          <div className="text-center">
            <p className="text-lg mb-2">Table Artifact</p>
            <p className="text-sm">Table editing support coming soon</p>
          </div>
        </div>
      );

    default:
      return (
        <div className="flex items-center justify-center h-full text-gray-500 p-8">
          <p>Unknown artifact type: {artifact.artifact_type}</p>
        </div>
      );
  }
};

export default ArtifactRenderer;
