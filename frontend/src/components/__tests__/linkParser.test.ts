import { describe, it, expect } from 'vitest'
import {
  parseWikiLinks,
  findNoteMentions,
  generateNoteConnections,
  calculateSemanticSimilarity,
  findBacklinks,
} from '../../utils/linkParser'

const sampleNotes = [
  { id: 1, title: 'React Hooks', content: 'useState and useEffect', created_at: '', updated_at: '' },
  { id: 2, title: 'TypeScript', content: 'Type safety for JS', created_at: '', updated_at: '' },
  { id: 3, title: 'Testing', content: 'Unit and integration tests', created_at: '', updated_at: '' },
]

describe('parseWikiLinks', () => {
  it('extracts [[Link]] syntax', () => {
    const links = parseWikiLinks('Check out [[React Hooks]] for details', sampleNotes)
    expect(links).toHaveLength(1)
    expect(links[0].noteTitle).toBe('React Hooks')
    expect(links[0].noteId).toBe(1)
  })

  it('returns null noteId for non-existent notes', () => {
    const links = parseWikiLinks('See [[Non Existent Note]]', sampleNotes)
    expect(links).toHaveLength(1)
    expect(links[0].noteId).toBeNull()
  })

  it('handles multiple links', () => {
    const links = parseWikiLinks('Use [[React Hooks]] with [[TypeScript]]', sampleNotes)
    expect(links).toHaveLength(2)
  })

  it('returns empty array for content with no links', () => {
    const links = parseWikiLinks('Just plain text here', sampleNotes)
    expect(links).toHaveLength(0)
  })

  it('is case-insensitive for note matching', () => {
    const links = parseWikiLinks('See [[react hooks]]', sampleNotes)
    expect(links).toHaveLength(1)
    expect(links[0].noteId).toBe(1)
  })
})

describe('findNoteMentions', () => {
  it('finds whole-word mentions of note titles', () => {
    const mentions = findNoteMentions('I love TypeScript for its safety', sampleNotes)
    expect(mentions).toHaveLength(1)
    expect(mentions[0].noteTitle).toBe('TypeScript')
  })

  it('skips titles shorter than 3 chars', () => {
    const notes = [{ id: 10, title: 'Go', content: '', created_at: '', updated_at: '' }]
    const mentions = findNoteMentions('I use Go for backends', notes)
    expect(mentions).toHaveLength(0)
  })
})

describe('generateNoteConnections', () => {
  it('creates reference connections from wiki links', () => {
    const note = {
      id: 10,
      title: 'My Note',
      content: 'References [[React Hooks]] and [[TypeScript]]',
      created_at: '',
      updated_at: '',
    }
    const connections = generateNoteConnections(note, sampleNotes)
    const refs = connections.filter((c) => c.type === 'reference')
    expect(refs).toHaveLength(2)
    expect(refs[0].sourceId).toBe(10)
    expect(refs[0].strength).toBe(1.0)
  })

  it('creates semantic connections from title mentions', () => {
    const note = {
      id: 10,
      title: 'My Note',
      content: 'Testing is important for quality',
      created_at: '',
      updated_at: '',
    }
    const connections = generateNoteConnections(note, sampleNotes)
    const semantic = connections.filter((c) => c.type === 'semantic')
    expect(semantic).toHaveLength(1)
    expect(semantic[0].targetId).toBe(3)
    expect(semantic[0].strength).toBe(0.5)
  })

  it('avoids duplicate connections when both wiki link and mention exist', () => {
    const note = {
      id: 10,
      title: 'My Note',
      content: '[[React Hooks]] — yes, React Hooks are great',
      created_at: '',
      updated_at: '',
    }
    const connections = generateNoteConnections(note, sampleNotes)
    const toReactHooks = connections.filter((c) => c.targetId === 1)
    // Should have reference but not a duplicate semantic
    expect(toReactHooks).toHaveLength(1)
    expect(toReactHooks[0].type).toBe('reference')
  })
})

describe('calculateSemanticSimilarity', () => {
  it('returns 0 for completely different texts', () => {
    const score = calculateSemanticSimilarity('alpha beta gamma', 'delta epsilon zeta')
    expect(score).toBe(0)
  })

  it('returns > 0 for texts sharing words', () => {
    const score = calculateSemanticSimilarity(
      'react hooks state management',
      'react state updates hooks'
    )
    expect(score).toBeGreaterThan(0)
  })

  it('returns 0 for empty text', () => {
    expect(calculateSemanticSimilarity('', 'some text')).toBe(0)
  })
})

describe('findBacklinks', () => {
  it('finds notes that link to the target', () => {
    const notes = [
      { id: 1, title: 'React Hooks', content: 'See [[Testing]] for test patterns', created_at: '', updated_at: '' },
      { id: 2, title: 'TypeScript', content: 'No links here', created_at: '', updated_at: '' },
      { id: 3, title: 'Testing', content: 'How to test React', created_at: '', updated_at: '' },
    ]
    const target = notes[2] // Testing
    const backlinks = findBacklinks(target, notes)
    expect(backlinks).toHaveLength(1)
    expect(backlinks[0].id).toBe(1)
  })
})
