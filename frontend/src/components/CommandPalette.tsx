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

  const navigationCommands: Command[] = PALETTE_NAV_VIEWS
    .filter((entry) => entry.view !== 'login' && entry.view !== currentView)
    .map((entry) => ({
      id: `nav-${entry.view}`,
      title: `Go to ${entry.title}`,
      icon: entry.icon,
      keywords: entry.keywords,
      action: () => onNavigate(entry.view),
      category: 'navigation' as const,
    }));

  const commands: Command[] = [
    ...navigationCommands,
    ...(onCreateNote ? [{ id: 'create-note', title: 'Create New Note', icon: '✍️', keywords: ['new', 'create', 'note', 'write'], action: onCreateNote, category: 'create' as const }] : []),
    ...(onCreateEvent ? [{ id: 'create-event', title: 'Create New Event', icon: '📅', keywords: ['new', 'create', 'event', 'meeting', 'schedule'], action: onCreateEvent, category: 'create' as const }] : []),
    ...(onCreateThread ? [{ id: 'create-thread', title: 'New Conversation', icon: '💬', keywords: ['new', 'conversation', 'thread', 'chat'], action: onCreateThread, category: 'create' as const }] : []),
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
    <div className="fixed inset-0 bg-black bg-opacity-60 z-[100] flex items-start justify-center pt-32" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-700 rounded-lg shadow-2xl w-full max-w-2xl mx-4"
        onClick={e => e.stopPropagation()}
      >
        {/* Search Input */}
        <div className="p-4 border-b border-gray-700">
          <div className="flex items-center space-x-3">
            <span className="text-gray-400 text-xl">⌘</span>
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a command or search..."
              className="flex-1 bg-transparent text-white text-lg outline-none placeholder-gray-500"
            />
          </div>
        </div>

        {/* Commands List */}
        <div className="max-h-96 overflow-y-auto">
          {filteredCommands.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No commands found
            </div>
          ) : (
            <div className="p-2">
              {Object.entries(categoryGroups).map(([category, cmds]) => (
                <div key={category} className="mb-4">
                  <div className="px-3 py-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    {categoryLabels[category as keyof typeof categoryLabels]}
                  </div>
                  {cmds.map((cmd, idx) => {
                    const globalIndex = filteredCommands.indexOf(cmd);
                    const isSelected = globalIndex === selectedIndex;

                    return (
                      <button
                        key={cmd.id}
                        onClick={() => handleCommandClick(cmd)}
                        className={`w-full text-left px-3 py-2.5 rounded-lg flex items-center space-x-3 transition-colors ${
                          isSelected
                            ? 'bg-teal-500 bg-opacity-20 text-teal-400'
                            : 'text-gray-300 hover:bg-gray-800'
                        }`}
                      >
                        {cmd.icon && <span className="text-xl">{cmd.icon}</span>}
                        <div className="flex-1 min-w-0">
                          <div className="font-medium">{cmd.title}</div>
                          {cmd.description && (
                            <div className="text-sm text-gray-500 truncate">{cmd.description}</div>
                          )}
                        </div>
                        {isSelected && (
                          <span className="text-xs text-gray-500">↵</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-500 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <span>↑↓ Navigate</span>
            <span>↵ Select</span>
            <span>Esc Close</span>
          </div>
          <div className="text-gray-600">
            {filteredCommands.length} commands
          </div>
        </div>
      </div>
    </div>
  );
};
