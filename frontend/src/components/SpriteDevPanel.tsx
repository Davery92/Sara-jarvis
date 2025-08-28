import React, { useEffect, useState } from 'react'
import { spriteBus } from '../state/spriteBus'

const isEnabled = () => {
  try {
    const flag = localStorage.getItem('sprite.devTunables') === 'true'
    const hash = typeof window !== 'undefined' && window.location.hash.includes('tunables')
    return flag || hash
  } catch { return false }
}

export default function SpriteDevPanel() {
  const [open, setOpen] = useState(false)
  const [energy, setEnergy] = useState(1.0)
  const [breathe, setBreathe] = useState(3.6)
  const [shimmer, setShimmer] = useState(11)
  const [tone, setTone] = useState<string>('')

  useEffect(() => {
    if (!open) return
    spriteBus.setVisuals({ energyScale: energy, tempoBreatheSec: breathe, tempoShimmerSec: shimmer }, 'dev:tunables')
    if (tone) spriteBus.setTone(tone as any, 'dev:tunables')
  }, [open, energy, breathe, shimmer, tone])

  if (!isEnabled()) return null
  return (
    <div className="fixed right-2 bottom-20 z-[1200]">
      <button className="px-2 py-1 text-xs bg-gray-800 border border-gray-700 rounded text-gray-200" onClick={() => setOpen(o => !o)}>
        Sprite Tunables
      </button>
      {open && (
        <div className="mt-2 w-64 p-3 rounded bg-gray-900/95 border border-white/10 text-gray-200">
          <div className="text-xs mb-2">Live adjustments (local only)</div>
          <label className="block text-xs">Energy {energy.toFixed(3)}
            <input type="range" min="0.95" max="1.05" step="0.005" value={energy} onChange={e => setEnergy(parseFloat(e.target.value))} className="w-full" />
          </label>
          <label className="block text-xs mt-2">Breathe {breathe.toFixed(1)}s
            <input type="range" min="3.0" max="6.0" step="0.1" value={breathe} onChange={e => setBreathe(parseFloat(e.target.value))} className="w-full" />
          </label>
          <label className="block text-xs mt-2">Shimmer {shimmer.toFixed(1)}s
            <input type="range" min="9" max="16" step="0.5" value={shimmer} onChange={e => setShimmer(parseFloat(e.target.value))} className="w-full" />
          </label>
          <label className="block text-xs mt-2">Tone
            <select value={tone} onChange={e => setTone(e.target.value)} className="w-full bg-gray-800 border border-gray-700 rounded p-1">
              <option value="">(none)</option>
              <option value="neutral">neutral</option>
              <option value="focused">focused</option>
              <option value="playful">playful</option>
              <option value="serious">serious</option>
            </select>
          </label>
        </div>
      )}
    </div>
  )
}

