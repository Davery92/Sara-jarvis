import { APP_CONFIG } from '../config'
import { generateNoteConnections } from './linkParser'

interface Note {
  id: number
  title: string
  content: string
  created_at: string
  updated_at: string
  folder_id?: number
}

interface Connection {
  sourceId: number
  targetId: number
  type: 'reference' | 'semantic' | 'temporal'
  strength: number
}

interface ApiConnection {
  target_note_id: string
  connection_type: string
  strength: number
  auto_generated: boolean
}

/**
 * Automatically detect and create connections for a note
 */
export async function detectAndCreateConnections(noteId: number, allNotes: Note[]): Promise<boolean> {
  try {
    const note = allNotes.find(n => n.id === noteId)
    if (!note) return false

    // Generate potential connections using our link parser
    const connections = generateNoteConnections(note, allNotes)
    
    if (connections.length === 0) return true

    // Get existing connections to avoid duplicates
    const existingResponse = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}/connections`, {
      credentials: 'include'
    })
    
    let existingConnections: any[] = []
    if (existingResponse.ok) {
      existingConnections = await existingResponse.json()
    }

    const existingTargets = new Set(existingConnections.map(conn => 
      conn.source_note_id === noteId.toString() ? conn.target_note_id : conn.source_note_id
    ))

    // Create new connections that don't exist yet
    let createdCount = 0
    for (const connection of connections) {
      const targetId = connection.targetId.toString()
      
      if (!existingTargets.has(targetId)) {
        const connectionData: ApiConnection = {
          target_note_id: targetId,
          connection_type: connection.type,
          strength: Math.round(connection.strength * 100), // Convert to 0-100
          auto_generated: true
        }

        const createResponse = await fetch(`${APP_CONFIG.apiUrl}/notes/${noteId}/connections`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(connectionData)
        })

        if (createResponse.ok) {
          createdCount++
          console.log(`✅ Created connection: ${note.title} -> ${allNotes.find(n => n.id === connection.targetId)?.title}`)
        } else if (createResponse.status !== 409) { // 409 = conflict (connection exists)
          console.warn(`Failed to create connection for note ${noteId}:`, await createResponse.text())
        }
      }
    }

    console.log(`🔗 Auto-detected ${createdCount} new connections for note: ${note.title}`)
    return true

  } catch (error) {
    console.error('Error in auto-connection detection:', error)
    return false
  }
}

/**
 * Scan all notes and update their connections
 */
export async function updateAllConnections(allNotes: Note[]): Promise<void> {
  console.log('🔄 Updating connections for all notes...')
  
  let totalCreated = 0
  for (const note of allNotes) {
    const success = await detectAndCreateConnections(note.id, allNotes)
    if (success) {
      // Small delay to avoid overwhelming the API
      await new Promise(resolve => setTimeout(resolve, 100))
    }
  }
  
  console.log(`✅ Connection update complete!`)
}

/**
 * Get semantic similarity suggestions for a note
 */
export async function getSimilarityBasedSuggestions(noteId: number, allNotes: Note[], threshold: number = 0.1): Promise<Note[]> {
  const note = allNotes.find(n => n.id === noteId)
  if (!note) return []

  // Simple content-based similarity (in production, you'd use embeddings from backend)
  const suggestions = allNotes
    .filter(n => n.id !== noteId)
    .map(otherNote => {
      const similarity = calculateContentSimilarity(note.content, otherNote.content)
      return { note: otherNote, similarity }
    })
    .filter(item => item.similarity > threshold)
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, 5)
    .map(item => item.note)

  return suggestions
}

/**
 * Calculate simple content similarity between two texts
 */
function calculateContentSimilarity(text1: string, text2: string): number {
  // Simple keyword-based similarity
  const words1 = text1.toLowerCase().split(/\s+/).filter(w => w.length > 3)
  const words2 = text2.toLowerCase().split(/\s+/).filter(w => w.length > 3)
  
  if (words1.length === 0 || words2.length === 0) return 0
  
  const set1 = new Set(words1)
  const set2 = new Set(words2)
  const intersection = new Set([...set1].filter(x => set2.has(x)))
  const union = new Set([...set1, ...set2])
  
  return intersection.size / union.size // Jaccard similarity
}

/**
 * Suggest connections based on semantic similarity
 */
export async function suggestSemanticConnections(noteId: number, allNotes: Note[]): Promise<{ note: Note, similarity: number }[]> {
  const suggestions = await getSimilarityBasedSuggestions(noteId, allNotes, 0.05)
  
  return suggestions.map(note => ({
    note,
    similarity: calculateContentSimilarity(
      allNotes.find(n => n.id === noteId)?.content || '',
      note.content
    )
  }))
}

/**
 * Create a manual connection between two notes
 */
export async function createManualConnection(
  sourceNoteId: number, 
  targetNoteId: number, 
  connectionType: 'reference' | 'semantic' | 'temporal' = 'reference',
  strength: number = 75
): Promise<boolean> {
  try {
    const connectionData: ApiConnection = {
      target_note_id: targetNoteId.toString(),
      connection_type: connectionType,
      strength,
      auto_generated: false
    }

    const response = await fetch(`${APP_CONFIG.apiUrl}/notes/${sourceNoteId}/connections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(connectionData)
    })

    if (response.ok) {
      console.log(`✅ Created manual connection: ${sourceNoteId} -> ${targetNoteId}`)
      return true
    } else {
      console.warn('Failed to create manual connection:', await response.text())
      return false
    }
  } catch (error) {
    console.error('Error creating manual connection:', error)
    return false
  }
}