/**
 * Local command classifier for voice commands
 *
 * Two-tier classification:
 * 1. Local regex matching (fast, no network)
 * 2. Backend fallback for ambiguous input
 */

// Command patterns for local classification
// Note: patterns should handle trailing punctuation like ? or .
const COMMAND_PATTERNS = [
  // Note commands - open/display a specific note
  { pattern: /^(?:open|display|show|pull up) (?:my |the )?(?:note (?:called |named )?)?(.+?)(?:\s+note)?[?.!]?$/i, type: 'OPEN_NOTE', paramIndex: 1, skipTTS: true },
  { pattern: /^(?:find|get) (?:my |the )?(.+?)(?:\s+note)[?.!]?$/i, type: 'OPEN_NOTE', paramIndex: 1, skipTTS: true },  // "find my X note" opens it
  { pattern: /^(?:find|get) (?:my |the )?note (?:called |named |about )?(.+?)[?.!]?$/i, type: 'OPEN_NOTE', paramIndex: 1, skipTTS: true },
  // Note commands - search multiple notes
  { pattern: /^search (?:my )?notes? (?:for |about )?(.+?)[?.!]?$/i, type: 'SEARCH_NOTES', paramIndex: 1 },
  { pattern: /^find (?:all )?notes? (?:about |on |for |mentioning )?(.+?)[?.!]?$/i, type: 'SEARCH_NOTES', paramIndex: 1 },

  // Recording commands - "record this" followed by content opens as note
  { pattern: /^(?:record this|start recording|take a note)[:\s]+(.+)$/i, type: 'RECORD_NOTE', paramIndex: 1, skipTTS: true },
  { pattern: /^(?:record this|start recording|take a note)\.?$/i, type: 'START_TRANSCRIPTION', skipTTS: true },
  { pattern: /^(?:stop recording|save (?:that|it)|done recording|end recording)/i, type: 'STOP_TRANSCRIPTION' },

  // Calendar commands
  { pattern: /^show (?:my )?calendar/i, type: 'SHOW_CALENDAR' },
  { pattern: /^(?:what's on my |show )(?:today|schedule|agenda)/i, type: 'SHOW_CALENDAR' },
  { pattern: /^what (?:do i have|am i doing) (?:today|tomorrow)/i, type: 'SHOW_CALENDAR' },

  // Nudge commands
  { pattern: /^show (?:my )?nudges/i, type: 'SHOW_NUDGES' },
  { pattern: /^acknowledge/i, type: 'ACK_NUDGE' },
  { pattern: /^(?:dismiss|clear) (?:nudge|that)/i, type: 'ACK_NUDGE' },
  { pattern: /^(?:got it|okay|ok|thanks)/i, type: 'ACK_NUDGE' },

  // State commands
  { pattern: /^show (?:my )?(?:state|status|mental model)/i, type: 'SHOW_STATE' },
  { pattern: /^how am i doing/i, type: 'SHOW_STATE' },

  // Navigation
  { pattern: /^(?:go )?home/i, type: 'GO_HOME' },
  { pattern: /^(?:go )?back/i, type: 'GO_BACK' },

  // System commands
  { pattern: /^(?:what's the |show )(?:llm |backend )?status/i, type: 'SHOW_LLM_STATUS' },
  { pattern: /^refresh/i, type: 'REFRESH' },
];

// Conversation starters (route to Sara instead of command)
const CONVERSATION_PATTERNS = [
  /^(?:hey |hi |hello )?sara/i,
  /^can you/i,
  /^could you/i,
  /^please/i,
  /^i (?:want|need|would like)/i,
  /^what (?:is|are|do|does|should|would|can|could)/i,
  /^how (?:do|does|should|would|can|could)/i,
  /^why (?:is|are|do|does|should|would|can|could)/i,
  /^when (?:is|are|do|does|should|would|can|could)/i,
  /^where (?:is|are|do|does|should|would|can|could)/i,
  /^who (?:is|are)/i,
  /^tell me/i,
  /^help me/i,
  /^remind me/i,
];

/**
 * Classify a voice command locally
 * @param {string} text - The transcribed text
 * @returns {{ type: 'command' | 'conversation', command?: string, params?: any }}
 */
export function classifyCommand(text) {
  const trimmed = text.trim();

  // Strip common conversational prefixes to extract the actual command
  // "Can you open my note" -> "open my note"
  // "Could you please show calendar" -> "show calendar"
  const prefixPattern = /^(?:can you |could you |please |would you |hey sara |sara |hi sara )+/i;
  const stripped = trimmed.replace(prefixPattern, '').trim();

  // Try to match against command patterns FIRST (check both original and stripped)
  for (const cmd of COMMAND_PATTERNS) {
    // Try stripped version first (handles "can you open my note")
    let match = stripped.match(cmd.pattern);
    if (match) {
      const params = cmd.paramIndex !== undefined ? match[cmd.paramIndex] : undefined;
      return {
        type: 'command',
        command: cmd.type,
        params: params ? params.trim() : undefined,
        skipTTS: cmd.skipTTS || false,
      };
    }
    // Also try original in case pattern expects the prefix
    match = trimmed.match(cmd.pattern);
    if (match) {
      const params = cmd.paramIndex !== undefined ? match[cmd.paramIndex] : undefined;
      return {
        type: 'command',
        command: cmd.type,
        params: params ? params.trim() : undefined,
        skipTTS: cmd.skipTTS || false,
      };
    }
  }

  // Check if it looks like a conversation (only if no command matched)
  const lowerTrimmed = trimmed.toLowerCase();
  for (const pattern of CONVERSATION_PATTERNS) {
    if (pattern.test(lowerTrimmed)) {
      return { type: 'conversation', text };
    }
  }

  // If no pattern matches, treat as conversation
  return { type: 'conversation', text };
}

/**
 * Get all available commands for help display
 */
export function getAvailableCommands() {
  return [
    { command: 'open note [name]', description: 'Open a specific note' },
    { command: 'search notes [query]', description: 'Search through notes' },
    { command: 'record this', description: 'Start live transcription' },
    { command: 'stop recording', description: 'Stop and save transcription' },
    { command: 'show calendar', description: 'Show today\'s calendar' },
    { command: 'show nudges', description: 'Show pending nudges' },
    { command: 'acknowledge', description: 'Dismiss a nudge' },
    { command: 'show status', description: 'Show current state' },
    { command: 'refresh', description: 'Refresh data' },
  ];
}

/**
 * Command execution handlers
 * Each handler receives params and callbacks for App state updates
 */
export const COMMAND_HANDLERS = {
  SHOW_CALENDAR: (params, { setView }) => {
    setView?.('calendar');
    return { success: true, message: 'Showing calendar' };
  },

  OPEN_NOTE: async (params, { api, setSelectedNote }) => {
    console.log('[OPEN_NOTE] Called with params:', params);
    console.log('[OPEN_NOTE] setSelectedNote exists:', !!setSelectedNote);
    console.log('[OPEN_NOTE] api exists:', !!api);

    if (!params) {
      return { success: false, message: 'Which note should I open?' };
    }
    try {
      // Search for the note by name
      console.log('[OPEN_NOTE] Searching for:', params);
      const results = await api.searchNotes(params);
      console.log('[OPEN_NOTE] Search results:', results);

      if (results && results.length > 0) {
        console.log('[OPEN_NOTE] Found note, calling setSelectedNote with:', results[0].title);
        setSelectedNote(results[0]);
        console.log('[OPEN_NOTE] setSelectedNote called successfully');
        return { success: true, message: `Opening ${results[0].title}` };
      }
      console.log('[OPEN_NOTE] No results found');
      return { success: false, message: `Couldn't find a note called "${params}"` };
    } catch (e) {
      console.error('[OPEN_NOTE] Error:', e);
      return { success: false, message: 'Failed to search notes' };
    }
  },

  SEARCH_NOTES: async (params, { api, setSearchResults }) => {
    if (!params) {
      return { success: false, message: 'What should I search for?' };
    }
    try {
      const results = await api.searchNotes(params);
      setSearchResults?.(results);
      return { success: true, message: `Found ${results?.length || 0} notes` };
    } catch (e) {
      return { success: false, message: 'Search failed' };
    }
  },

  RECORD_NOTE: (params, { setSelectedNote }) => {
    console.log('[RECORD_NOTE] Called with params:', params);
    console.log('[RECORD_NOTE] setSelectedNote exists:', !!setSelectedNote);

    if (!params) {
      return { success: false, message: 'Nothing to record' };
    }

    // Create a new unsaved note with the transcription content
    // Generate a title from the first line or first few words
    const lines = params.split('\n');
    const firstLine = lines[0].trim();
    const title = firstLine.length > 50
      ? firstLine.substring(0, 50) + '...'
      : firstLine || 'Voice Recording';

    const newNote = {
      id: null,  // null ID indicates unsaved/new note
      title: title,
      content: params,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      isNew: true,  // Flag to indicate this is a new recording
    };

    console.log('[RECORD_NOTE] Opening note modal with:', newNote);
    setSelectedNote?.(newNote);
    return { success: true, message: 'Opening recording' };
  },

  SHOW_NUDGES: (params, { setShowNudges }) => {
    setShowNudges?.(true);
    return { success: true, message: 'Showing nudges' };
  },

  ACK_NUDGE: async (params, { nudges, onAcknowledge }) => {
    if (nudges && nudges.length > 0) {
      await onAcknowledge?.(nudges[0].id);
      return { success: true, message: 'Acknowledged' };
    }
    return { success: false, message: 'No nudges to acknowledge' };
  },

  SHOW_STATE: (params, { setView }) => {
    setView?.('state');
    return { success: true, message: 'Showing state' };
  },

  SHOW_LLM_STATUS: (params, { setView }) => {
    setView?.('llm');
    return { success: true, message: 'Showing LLM status' };
  },

  GO_HOME: (params, { setView, setSelectedNote }) => {
    setView?.('home');
    setSelectedNote?.(null);
    return { success: true, message: 'Going home' };
  },

  GO_BACK: (params, { setSelectedNote }) => {
    setSelectedNote?.(null);
    return { success: true, message: 'Going back' };
  },

  REFRESH: async (params, { fetchData }) => {
    await fetchData?.();
    return { success: true, message: 'Refreshed' };
  },

  START_TRANSCRIPTION: (params, { startContinuousRecording }) => {
    console.log('[START_TRANSCRIPTION] Triggering continuous recording overlay');
    startContinuousRecording?.();
    return { success: true, message: 'Recording, tap when done' };
  },

  STOP_TRANSCRIPTION: (params, { stopContinuousRecording }) => {
    console.log('[STOP_TRANSCRIPTION] Stopping continuous recording');
    stopContinuousRecording?.();
    return { success: true, message: 'Recording stopped' };
  },
};

/**
 * Execute a command with the given handlers
 * @param {string} command - The command type (e.g., 'SHOW_CALENDAR')
 * @param {any} params - Parameters extracted from the voice input
 * @param {object} context - App context with callbacks and state
 * @returns {Promise<{success: boolean, message: string}>}
 */
export async function executeCommand(command, params, context) {
  const handler = COMMAND_HANDLERS[command];
  if (!handler) {
    return { success: false, message: `Unknown command: ${command}` };
  }
  return await handler(params, context);
}
