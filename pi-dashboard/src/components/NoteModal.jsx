import { useState } from 'preact/hooks';
import { marked } from 'marked';
import { api } from '../services/api';

/**
 * Modal overlay to display a note with rendered markdown
 * Supports both viewing existing notes and saving new recordings
 */
export function NoteModal({ note, onClose, onSaved }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  if (!note) return null;

  // Configure marked for safe rendering
  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  const renderedContent = marked.parse(note.content || '');
  const isNewNote = note.isNew || note.id === null;

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const savedNote = await api.saveNote(note.content, note.title);
      console.log('[NoteModal] Note saved:', savedNote);
      onSaved?.(savedNote);
      onClose();
    } catch (err) {
      console.error('[NoteModal] Failed to save note:', err);
      setError('Failed to save note');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div class="note-modal-overlay" onClick={onClose}>
      <div class="note-modal" onClick={(e) => e.stopPropagation()}>
        <div class="note-modal-header">
          <h2 class="note-modal-title">{note.title || 'Untitled Note'}</h2>
          <div class="note-modal-actions">
            {isNewNote && (
              <button
                class="note-modal-save"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? 'Saving...' : 'Save Note'}
              </button>
            )}
            <button class="note-modal-close" onClick={onClose}>×</button>
          </div>
        </div>
        {error && <div class="note-modal-error">{error}</div>}
        <div
          class="note-modal-content markdown-body"
          dangerouslySetInnerHTML={{ __html: renderedContent }}
        />
      </div>
    </div>
  );
}
