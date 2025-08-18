interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface ParsedLink {
  text: string
  noteTitle: string
  noteId: number | null
  startIndex: number
  endIndex: number
}

interface Connection {
  sourceId: number
  targetId: number
  type: 'reference' | 'semantic' | 'temporal'
  strength: number
}

/**
 * Parse [[Note Title]] style links from note content
 */
export function parseWikiLinks(content: string, allNotes: Note[]): ParsedLink[] {
  const linkRegex = /\[\[([^\]]+)\]\]/g
  const links: ParsedLink[] = []
  let match

  while ((match = linkRegex.exec(content)) !== null) {
    const noteTitle = match[1].trim()
    const linkedNote = allNotes.find(note => 
      note.title.toLowerCase() === noteTitle.toLowerCase()
    )

    links.push({
      text: match[0],
      noteTitle,
      noteId: linkedNote?.id || null,
      startIndex: match.index,
      endIndex: match.index + match[0].length
    })
  }

  return links
}

/**
 * Find all mentions of note titles in content (without [[]] syntax)
 */
export function findNoteMentions(content: string, allNotes: Note[]): ParsedLink[] {
  const mentions: ParsedLink[] = []
  
  allNotes.forEach(note => {
    if (!note.title || note.title.length < 3) return
    
    const titleLower = note.title.toLowerCase()
    const contentLower = content.toLowerCase()
    
    let index = contentLower.indexOf(titleLower)
    while (index !== -1) {
      // Make sure it's a whole word match
      const isWholeWord = (
        (index === 0 || /\s/.test(contentLower[index - 1])) &&
        (index + titleLower.length === contentLower.length || /\s/.test(contentLower[index + titleLower.length]))
      )
      
      if (isWholeWord) {
        mentions.push({
          text: content.substring(index, index + note.title.length),
          noteTitle: note.title,
          noteId: note.id,
          startIndex: index,
          endIndex: index + note.title.length
        })
      }
      
      index = contentLower.indexOf(titleLower, index + 1)
    }
  })

  return mentions
}

/**
 * Generate connections from a note based on its links and mentions
 */
export function generateNoteConnections(note: Note, allNotes: Note[]): Connection[] {
  const connections: Connection[] = []
  
  // Parse wiki-style links [[Note Title]]
  const wikiLinks = parseWikiLinks(note.content, allNotes)
  wikiLinks.forEach(link => {
    if (link.noteId) {
      connections.push({
        sourceId: note.id,
        targetId: link.noteId,
        type: 'reference',
        strength: 1.0
      })
    }
  })

  // Find natural mentions of other note titles
  const mentions = findNoteMentions(note.content, allNotes.filter(n => n.id !== note.id))
  mentions.forEach(mention => {
    if (mention.noteId) {
      // Check if we already have a reference connection to avoid duplicates
      const existingRef = connections.find(conn => 
        conn.targetId === mention.noteId && conn.type === 'reference'
      )
      
      if (!existingRef) {
        connections.push({
          sourceId: note.id,
          targetId: mention.noteId,
          type: 'semantic',
          strength: 0.5
        })
      }
    }
  })

  return connections
}

/**
 * Get parsed links data for content (for use in React components)
 */
export function getContentLinks(
  content: string, 
  allNotes: Note[]
): { text: string, links: ParsedLink[] } {
  const wikiLinks = parseWikiLinks(content, allNotes)
  const mentions = findNoteMentions(content, allNotes.filter(n => n.title))

  // Combine and sort all links by position
  const allLinks = [...wikiLinks, ...mentions].sort((a, b) => a.startIndex - b.startIndex)
  
  return {
    text: content,
    links: allLinks
  }
}

/**
 * Generate semantic similarity score between two texts
 */
export function calculateSemanticSimilarity(text1: string, text2: string): number {
  // Simple keyword-based similarity for now
  // In production, you'd use embeddings from the backend
  
  const words1 = text1.toLowerCase().split(/\s+/).filter(w => w.length > 3)
  const words2 = text2.toLowerCase().split(/\s+/).filter(w => w.length > 3)
  
  if (words1.length === 0 || words2.length === 0) return 0
  
  const commonWords = words1.filter(word => words2.includes(word))
  const totalWords = new Set([...words1, ...words2]).size
  
  return commonWords.length / totalWords
}

/**
 * Find backlinks - notes that reference the given note
 */
export function findBacklinks(targetNote: Note, allNotes: Note[]): Note[] {
  return allNotes.filter(note => {
    if (note.id === targetNote.id) return false
    
    const wikiLinks = parseWikiLinks(note.content, allNotes)
    const mentions = findNoteMentions(note.content, [targetNote])
    
    return wikiLinks.some(link => link.noteId === targetNote.id) ||
           mentions.some(mention => mention.noteId === targetNote.id)
  })
}

/**
 * Find related notes based on semantic similarity
 */
export function findRelatedNotes(targetNote: Note, allNotes: Note[], threshold: number = 0.1): Note[] {
  return allNotes
    .filter(note => note.id !== targetNote.id)
    .map(note => ({
      note,
      similarity: calculateSemanticSimilarity(targetNote.content, note.content)
    }))
    .filter(item => item.similarity > threshold)
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, 10) // Top 10 most similar
    .map(item => item.note)
}