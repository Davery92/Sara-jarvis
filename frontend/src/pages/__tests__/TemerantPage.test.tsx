import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TemerantPage from '../TemerantPage'
import { apiClient } from '../../api/client'

vi.mock('../../api/client', () => ({
  apiClient: {
    getTemerantStarterProfiles: vi.fn(),
    getTemerantCharacter: vi.fn(),
    createTemerantCharacter: vi.fn(),
    getTemerantDashboard: vi.fn(),
    getTemerantCurrentTerm: vi.fn(),
    listTemerantTermHistory: vi.fn(),
    listTemerantOracleEvents: vi.fn(),
    listTemerantJournal: vi.fn(),
    listTemerantMappings: vi.fn(),
    listTemerantLedger: vi.fn(),
    createTemerantManualLog: vi.fn(),
    rollTemerantOracle: vi.fn(),
    resolveTemerantOracleEvent: vi.fn(),
    generateTemerantJournal: vi.fn(),
  },
}))

const mockedApi = apiClient as any

const sampleCharacter = {
  id: 'c1',
  user_id: 'u1',
  character_name: 'Avery',
  current_rank: 'elir',
  coin_balance: 3,
  alar_strength: 1,
  naming_affinity: 1,
}

const sampleDashboard = {
  date: '2026-02-20',
  character: sampleCharacter,
  attributes: {
    body: { attribute: 'body', xp_total: 10, xp_term: 10, level: 1, xp_today: 2 },
    mind: { attribute: 'mind', xp_total: 11, xp_term: 11, level: 1, xp_today: 2 },
    craft: { attribute: 'craft', xp_total: 12, xp_term: 12, level: 1, xp_today: 2 },
    coin: { attribute: 'coin', xp_total: 13, xp_term: 13, level: 1, xp_today: 2 },
    name: { attribute: 'name', xp_total: 14, xp_term: 14, level: 1, xp_today: 2 },
  },
  daily: {
    local_date: '2026-02-20',
    categories_completed: 2,
    body_xp: 2,
    mind_xp: 2,
    craft_xp: 0,
    coin_xp: 0,
    name_xp: 0,
    term_month: '2026-02-01',
  },
  rank_progress: {
    next_rank: 'relar',
    requirements: {
      attributes_over_50: 0,
      required_attributes_over_50: 3,
      streak_categories_over_30: 0,
      required_streak_categories_over_30: 2,
    },
  },
  oracle_event: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApi.getTemerantStarterProfiles.mockResolvedValue([])
  mockedApi.getTemerantCurrentTerm.mockResolvedValue({
    id: 't1',
    term_month: '2026-02-01',
    completion_pct: 66.7,
    admissions_result: 'good',
    tuition_talents: 10,
    xp_multiplier: 1,
    coin_delta: -10,
  })
  mockedApi.listTemerantTermHistory.mockResolvedValue([])
  mockedApi.listTemerantOracleEvents.mockResolvedValue([])
  mockedApi.listTemerantJournal.mockResolvedValue([])
  mockedApi.listTemerantMappings.mockResolvedValue([])
  mockedApi.listTemerantLedger.mockResolvedValue([])
  mockedApi.createTemerantManualLog.mockResolvedValue({
    ledger_entry_id: 'l1',
    local_date: '2026-02-20',
    attribute: 'body',
    xp_delta: 2,
    coin_delta: 0,
    rank_after: 'elir',
    duplicate: false,
  })
  mockedApi.rollTemerantOracle.mockResolvedValue(null)
  mockedApi.generateTemerantJournal.mockResolvedValue({})
  mockedApi.resolveTemerantOracleEvent.mockResolvedValue({})
})

describe('TemerantPage', () => {
  it('shows character onboarding when no character exists', async () => {
    mockedApi.getTemerantCharacter.mockRejectedValue({ response: { status: 404 } })
    mockedApi.createTemerantCharacter.mockResolvedValue(sampleCharacter)

    render(<TemerantPage />)

    expect(await screen.findByText('Create Your Character')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Name in the Arcanum'), {
      target: { value: 'Avery' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Begin Term' }))

    await waitFor(() => {
      expect(mockedApi.createTemerantCharacter).toHaveBeenCalledWith(
        expect.objectContaining({ character_name: 'Avery' })
      )
    })
  })

  it('renders dashboard and logs quick action', async () => {
    mockedApi.getTemerantCharacter.mockResolvedValue(sampleCharacter)
    mockedApi.getTemerantDashboard.mockResolvedValue(sampleDashboard)

    render(<TemerantPage />)

    expect(await screen.findByText('Solo RPG Habit System')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Workout/i }))

    await waitFor(() => {
      expect(mockedApi.createTemerantManualLog).toHaveBeenCalledWith(
        expect.objectContaining({ action_type: 'workout' })
      )
    })
  })
})
