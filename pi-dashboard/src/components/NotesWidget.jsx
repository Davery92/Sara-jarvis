/**
 * NotesWidget - Shows recent notes and allows viewing
 */
import { useState } from 'preact/hooks';

export function NotesWidget({ notes, selectedNote, onSelectNote, loading }) {
  if (loading) {
    return (
      <div class="card notes-widget">
        <div class="card-header">
          <span class="card-title">Notes</span>
        </div>
        <div class="loading-state">Loading notes...</div>
      </div>
    );
  }

  // If a note is selected, show its content
  if (selectedNote) {
    return (
      <div class="card notes-widget note-viewer">
        <div class="card-header">
          <button class="back-btn" onClick={() => onSelectNote(null)}>← Back</button>
          <span class="card-title">{selectedNote.title}</span>
        </div>
        <div class="note-content">
          {selectedNote.content || 'No content'}
        </div>
      </div>
    );
  }

  if (!notes || notes.length === 0) {
    return (
      <div class="card notes-widget">
        <div class="card-header">
          <span class="card-title">Recent Notes</span>
        </div>
        <div class="empty-state">No notes found</div>
      </div>
    );
  }

  const formatDate = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diffDays = Math.floor((now - date) / 86400000);

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <div class="card notes-widget">
      <div class="card-header">
        <span class="card-title">Recent Notes</span>
      </div>
      <div class="notes-list">
        {notes.slice(0, 5).map((note, idx) => (
          <div
            key={note.id || idx}
            class="note-item"
            onClick={() => onSelectNote(note)}
          >
            <span class="note-title">{note.title || 'Untitled'}</span>
            <span class="note-date">{formatDate(note.updated_at || note.created_at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
