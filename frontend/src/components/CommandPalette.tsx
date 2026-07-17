import React, { useState, useEffect, useRef } from 'react';
import { PALETTE_NAV_VIEWS } from '../navigation/views';

interface Command {
  id: string;
  title: string;
  description?: string;
  icon?: string;
  keywords: string[];
  action: () => void;
  category: 'navigation' | 'create' | 'search' | 'ai' | 'system';
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (view: string) => void;
  onCreateNote?: () => void;
  onCreateEvent?: () => void;
  onCreateThread?: () => void;
  currentView?: string;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
  onCreateNote,
  onCreateEvent,
  onCreateThread,
  currentView = ''
}) => {
  const [search, setSearch] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigationDescriptions: Record<string, string> = {
    dashboard: 'Return to today, priorities, and the assistant overview.',
    chat: 'Jump into the main conversation with Sara.',
    inbox: 'Review captures, reports, and assistant follow-ups.',
    calendar: 'Open your schedule, reminders, and upcoming events.',
    email: 'Triage messages and pending email work.',
    notes: 'Open the notes workspace and knowledge capture.',
    documents: 'Review uploads, files, and parsed documents.',
    fitness: 'See training, recovery, and meal planning.',
    briefings: 'Open the full morning brief.',
    automations: 'Check active missions and background work.',
  };

  const navigationCommands: Command[] = PALETTE_NAV_VIEWS
    .filter((entry) => entry.view !== 'login' && entry.view !== currentView)
    .map((entry) => ({
      id: `nav-${entry.view}`,
      title: `Go to ${entry.title}`,
      icon: entry.icon,
      description: navigationDescriptions[entry.view],
      keywords: entry.keywords,
      action: () => onNavigate(entry.view),
      category: 'navigation' as const,
    }));

  const commands: Command[] = [
    ...navigationCommands,
    ...(onCreateNote ? [{
      id: 'create-note',
      title: 'Create New Note',
      description: 'Start a fresh note in the knowledge workspace.',
      icon: 'edit_note',
      keywords: ['new', 'create', 'note', 'write'],
      action: onCreateNote,
      category: 'create' as const,
    }] : []),
    ...(onCreateEvent ? [{
      id: 'create-event',
      title: 'Create New Event',
      description: 'Add a meeting, reminder, or time block.',
      icon: 'event',
      keywords: ['new', 'create', 'event', 'meeting', 'schedule'],
      action: onCreateEvent,
      category: 'create' as const,
    }] : []),
    ...(onCreateThread ? [{
      id: 'create-thread',
      title: 'New Conversation',
      description: 'Open a fresh assistant conversation thread.',
      icon: 'chat',
      keywords: ['new', 'conversation', 'thread', 'chat'],
      action: onCreateThread,
      category: 'create' as const,
    }] : []),
  ];

  const filteredCommands = search
    ? commands.filter(cmd =>
        cmd.title.toLowerCase().includes(search.toLowerCase()) ||
        cmd.keywords.some(kw => kw.toLowerCase().includes(search.toLowerCase())) ||
        (cmd.description && cmd.description.toLowerCase().includes(search.toLowerCase()))
      )
    : commands;

  const categoryGroups = filteredCommands.reduce((acc, cmd) => {
    if (!acc[cmd.category]) acc[cmd.category] = [];
    acc[cmd.category].push(cmd);
    return acc;
  }, {} as Record<string, Command[]>);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
      setSearch('');
      setSelectedIndex(0);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => Math.min(prev + 1, filteredCommands.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const selectedCommand = filteredCommands[selectedIndex];
      if (selectedCommand) {
        selectedCommand.action();
        onClose();
      }
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  const handleCommandClick = (command: Command) => {
    command.action();
    onClose();
  };

  if (!isOpen) return null;

  const categoryLabels = {
    navigation: 'Navigation',
    create: 'Create',
    search: 'Search',
    ai: 'AI Actions',
    system: 'System'
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-slate-950/78 px-4 pt-20 backdrop-blur-md md:pt-28" onClick={onClose}>
      <div
        className="assistant-panel w-full max-w-3xl overflow-hidden rounded-md shadow-[0_30px_90px_rgba(2,8,23,0.48)]"
        onClick={e => e.stopPropagation()}
      >
        <div className="border-b border-white/8 px-5 py-5 md:px-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="assistant-kicker mb-2">Command Palette</div>
              <p className="font-display text-2xl font-semibold text-white">Move through Sara quickly.</p>
            </div>
            <div className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-2 text-xs text-slate-400">
              Esc to close
            </div>
          </div>

          <div className="assistant-panel-soft flex items-center gap-3 rounded-md px-4 py-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-md border border-white/8 bg-slate-950/50 text-slate-300">
              <span className="material-icons text-[20px]">search</span>
            </div>
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a destination or action..."
              className="flex-1 bg-transparent text-base text-white outline-none placeholder:text-slate-500 md:text-lg"
            />
            <div className="hidden rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-xs text-slate-500 md:block">
              Cmd/Ctrl + K
            </div>
          </div>
        </div>

        <div className="max-h-[28rem] overflow-y-auto px-3 py-3 md:px-4">
          {filteredCommands.length === 0 ? (
            <div className="assistant-panel-soft m-2 rounded-md p-8 text-center">
              <div className="font-display text-xl text-white">No matching command</div>
              <p className="mt-2 text-sm text-slate-400">
                Try searching by workspace name, like chat, inbox, calendar, or automations.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(categoryGroups).map(([category, cmds]) => (
                <div key={category}>
                  <div className="px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    {categoryLabels[category as keyof typeof categoryLabels]}
                  </div>
                  <div className="mt-2 space-y-2">
                  {cmds.map((cmd) => {
                    const globalIndex = filteredCommands.indexOf(cmd);
                    const isSelected = globalIndex === selectedIndex;

                    return (
                      <button
                        key={cmd.id}
                        onClick={() => handleCommandClick(cmd)}
                        className={`w-full rounded-md border px-3 py-3 text-left transition ${
                          isSelected
                            ? 'border-teal-300/20 bg-teal-300/12 text-white shadow-[0_14px_30px_rgba(13,148,136,0.16)]'
                            : 'border-white/8 bg-white/[0.02] text-slate-300 hover:bg-white/[0.04] hover:text-white'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          {cmd.icon && (
                            <span
                              className={`flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-md border ${
                                isSelected
                                  ? 'border-teal-300/20 bg-teal-300/14 text-teal-100'
                                  : 'border-white/8 bg-slate-950/50 text-slate-400'
                              }`}
                            >
                              <span className="material-icons text-[20px]">{cmd.icon}</span>
                            </span>
                          )}
                        <div className="flex-1 min-w-0">
                          <div className="font-medium">{cmd.title}</div>
                          {cmd.description && (
                            <div className="mt-1 text-sm text-slate-500 truncate">{cmd.description}</div>
                          )}
                        </div>
                        {isSelected && (
                          <span className="rounded-full border border-white/8 bg-white/[0.03] px-2 py-1 text-[11px] text-slate-400">
                            Enter
                          </span>
                        )}
                        </div>
                      </button>
                    );
                  })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-white/8 px-5 py-3 text-xs text-slate-500 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <span>↑↓ Navigate</span>
            <span>Enter Select</span>
            <span>Esc Close</span>
          </div>
          <div className="text-slate-600">
            {filteredCommands.length} commands
          </div>
        </div>
      </div>
    </div>
  );
};
