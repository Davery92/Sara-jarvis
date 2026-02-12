import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import StarRating from '../StarRating'

// Mock config so we don't hit real API
vi.mock('../../config', () => ({
  APP_CONFIG: { apiUrl: 'http://localhost:8000' },
}))

// Mock fetch globally
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  mockFetch.mockReset()
  // Default: no existing rating
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => ({ rated: false }),
  })
})

describe('StarRating', () => {
  it('renders 5 star buttons', () => {
    render(<StarRating episodeId="ep-1" />)
    const stars = screen.getAllByRole('button', { name: /Rate \d stars/ })
    expect(stars).toHaveLength(5)
  })

  it('calls onRatingChange when a star is clicked', async () => {
    mockFetch
      .mockResolvedValueOnce({ ok: true, json: async () => ({ rated: false }) }) // load
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) }) // rate

    const onChange = vi.fn()
    render(<StarRating episodeId="ep-1" onRatingChange={onChange} />)

    const star3 = screen.getByRole('button', { name: 'Rate 3 stars' })
    fireEvent.click(star3)

    // Wait for async fetch
    await vi.waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(3)
    })
  })

  it('disables interaction in readonly mode', () => {
    render(<StarRating episodeId="ep-1" readonly />)
    const stars = screen.getAllByRole('button', { name: /Rate \d stars/ })
    stars.forEach((star) => {
      expect(star).toBeDisabled()
    })
  })

  it('shows loading state while submitting', async () => {
    // Never resolve the rate request so loading stays true
    mockFetch
      .mockResolvedValueOnce({ ok: true, json: async () => ({ rated: false }) }) // load
      .mockImplementationOnce(() => new Promise(() => {})) // rate — hangs

    render(<StarRating episodeId="ep-1" />)

    const star4 = screen.getByRole('button', { name: 'Rate 4 stars' })
    fireEvent.click(star4)

    // Buttons should become disabled during loading
    await vi.waitFor(() => {
      const stars = screen.getAllByRole('button', { name: /Rate \d stars/ })
      expect(stars[0]).toBeDisabled()
    })
  })
})
