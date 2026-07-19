import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { X, Play, Pause, SkipForward, RotateCcw, Volume2, VolumeX, Check, PlusCircle } from 'lucide-react'
import { APP_CONFIG } from '../../config'

// --- shared interval types (mirrors the iOS cardio service) ---
export interface TabataConfig {
  id?: string
  name: string
  activity_type: string
  color?: string | null
  prepare_seconds: number
  work_seconds: number
  rest_seconds: number
  rounds: number
  sets: number
  rest_between_sets_seconds: number
}

type PhaseKind = 'prepare' | 'work' | 'rest' | 'rest_set' | 'done'
interface Phase { kind: PhaseKind; seconds: number; round: number; set: number }

const PHASE_COLOR: Record<PhaseKind, string> = {
  prepare: '#fbbf24', work: '#ef4444', rest: '#34d399', rest_set: '#38bdf8', done: '#5eead4',
}
const PHASE_TITLE: Record<PhaseKind, string> = {
  prepare: 'GET READY', work: 'WORK', rest: 'REST', rest_set: 'SET BREAK', done: 'DONE',
}

export function buildSequence(p: TabataConfig): Phase[] {
  const seq: Phase[] = []
  if (p.prepare_seconds > 0) seq.push({ kind: 'prepare', seconds: p.prepare_seconds, round: 1, set: 1 })
  for (let s = 1; s <= p.sets; s++) {
    for (let r = 1; r <= p.rounds; r++) {
      seq.push({ kind: 'work', seconds: p.work_seconds, round: r, set: s })
      if (r < p.rounds && p.rest_seconds > 0) seq.push({ kind: 'rest', seconds: p.rest_seconds, round: r, set: s })
    }
    if (s < p.sets && p.rest_between_sets_seconds > 0)
      seq.push({ kind: 'rest_set', seconds: p.rest_between_sets_seconds, round: p.rounds, set: s })
  }
  return seq
}

export function totalSeconds(p: TabataConfig): number {
  return buildSequence(p).reduce((a, b) => a + b.seconds, 0)
}

function fmt(sec: number): string {
  const s = Math.max(0, Math.ceil(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}:${r.toString().padStart(2, '0')}` : `${r}`
}

export default function TabataTimer({ preset, onClose, onLogged }: {
  preset: TabataConfig; onClose: () => void; onLogged?: () => void;
}) {
  const sequence = useMemo(() => buildSequence(preset), [preset])
  const total = useMemo(() => totalSeconds(preset), [preset])

  const [phaseIndex, setPhaseIndex] = useState(0)
  const [secondsLeft, setSecondsLeft] = useState(sequence[0]?.seconds ?? 0)
  const [running, setRunning] = useState(false)
  const [finished, setFinished] = useState(false)
  const [muted, setMuted] = useState(false)
  const [logged, setLogged] = useState(false)

  const phaseIndexRef = useRef(0)
  const phaseEndRef = useRef(0)
  const remainingRef = useRef(sequence[0]?.seconds ?? 0)
  const lastTickRef = useRef(-1)
  const rafRef = useRef<number | null>(null)
  const audioRef = useRef<AudioContext | null>(null)
  const mutedRef = useRef(false)
  useEffect(() => { mutedRef.current = muted }, [muted])

  const phase = sequence[phaseIndex]
  const phaseKind: PhaseKind = finished ? 'done' : (phase?.kind ?? 'done')
  const accent = PHASE_COLOR[phaseKind]

  const beep = useCallback((freq: number, durMs: number) => {
    if (mutedRef.current) return
    try {
      if (!audioRef.current) audioRef.current = new (window.AudioContext || (window as any).webkitAudioContext)()
      const ctx = audioRef.current
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = freq
      osc.type = 'sine'
      osc.connect(gain); gain.connect(ctx.destination)
      const now = ctx.currentTime
      gain.gain.setValueAtTime(0.0001, now)
      gain.gain.exponentialRampToValueAtTime(0.5, now + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + durMs / 1000)
      osc.start(now); osc.stop(now + durMs / 1000 + 0.02)
    } catch { /* audio best-effort */ }
  }, [])

  const cue = useCallback((kind: PhaseKind) => {
    if (kind === 'work') beep(950, 240)
    else if (kind === 'rest' || kind === 'rest_set') beep(480, 240)
  }, [beep])

  const finish = useCallback(() => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    setRunning(false); setFinished(true); setSecondsLeft(0)
    beep(680, 140); setTimeout(() => beep(760, 140), 180); setTimeout(() => beep(880, 200), 360)
  }, [beep])

  const advance = useCallback(() => {
    const next = phaseIndexRef.current + 1
    if (next >= sequence.length) { finish(); return }
    phaseIndexRef.current = next
    const ph = sequence[next]
    remainingRef.current = ph.seconds
    phaseEndRef.current = performance.now() + ph.seconds * 1000
    lastTickRef.current = -1
    setPhaseIndex(next); setSecondsLeft(ph.seconds); cue(ph.kind)
  }, [sequence, finish, cue])

  const loop = useCallback(() => {
    const remaining = (phaseEndRef.current - performance.now()) / 1000
    remainingRef.current = remaining
    if (remaining <= 0.05) { advance() }
    else {
      setSecondsLeft(remaining)
      const whole = Math.ceil(remaining)
      if (whole <= 3 && whole !== lastTickRef.current) { lastTickRef.current = whole; beep(720, 90) }
    }
    rafRef.current = requestAnimationFrame(loop)
  }, [advance, beep])

  useEffect(() => {
    if (running) {
      rafRef.current = requestAnimationFrame(loop)
      return () => { if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null } }
    }
  }, [running, loop])

  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }, [])

  const startPause = () => {
    if (finished) return
    if (running) {
      setRunning(false)
      remainingRef.current = Math.max(0, (phaseEndRef.current - performance.now()) / 1000)
    } else {
      const cur = sequence[phaseIndexRef.current]
      if (!cur) return
      phaseEndRef.current = performance.now() + remainingRef.current * 1000
      if (remainingRef.current === cur.seconds && lastTickRef.current === -1) cue(cur.kind)
      setRunning(true)
    }
  }

  const skip = () => { if (!finished) advance() }
  const reset = () => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    phaseIndexRef.current = 0
    remainingRef.current = sequence[0]?.seconds ?? 0
    lastTickRef.current = -1
    setPhaseIndex(0); setSecondsLeft(sequence[0]?.seconds ?? 0); setRunning(false); setFinished(false); setLogged(false)
  }

  const logSession = async () => {
    if (logged) return
    try {
      const minutes = Math.round((total / 60) * 10) / 10
      const res = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/cardio/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          activity_type: preset.activity_type || 'tabata',
          title: preset.name,
          duration_minutes: minutes,
          source: 'tabata',
          tabata_detail: {
            work: preset.work_seconds, rest: preset.rest_seconds,
            rounds: preset.rounds, sets: preset.sets,
            completed_rounds: preset.rounds * preset.sets, preset_name: preset.name,
          },
        }),
      })
      if (res.ok) { setLogged(true); onLogged?.() }
    } catch { /* ignore */ }
  }

  const totalRounds = preset.rounds * preset.sets
  const workProgress = finished
    ? totalRounds
    : Math.min(sequence.slice(0, phaseIndex + 1).filter(p => p.kind === 'work').length, totalRounds)
  const phaseTotal = finished ? 1 : (phase?.seconds ?? 1)
  const progress = finished ? 1 : 1 - secondsLeft / phaseTotal
  const R = 130, C = 2 * Math.PI * R

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-between py-8"
      style={{ background: finished ? '#050b16' : `${accent}14`, backdropFilter: 'blur(2px)' }}>
      {/* top bar */}
      <div className="w-full max-w-md flex items-center justify-between px-6">
        <button onClick={onClose} className="p-2 text-slate-200 hover:text-white"><X className="w-6 h-6" /></button>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
          <span className="text-sm font-semibold text-white truncate max-w-[180px]">{preset.name}</span>
        </div>
        <button onClick={() => setMuted(m => !m)} className="p-2 text-slate-400 hover:text-slate-200">
          {muted ? <VolumeX className="w-5 h-5" /> : <Volume2 className="w-5 h-5" />}
        </button>
      </div>

      {/* stage */}
      {!finished ? (
        <div className="flex flex-col items-center gap-6">
          <div className="text-xl font-extrabold tracking-[0.25em]" style={{ color: accent }}>{PHASE_TITLE[phaseKind]}</div>
          <svg width={300} height={300} viewBox="0 0 300 300">
            <circle cx={150} cy={150} r={R} stroke={`${accent}33`} strokeWidth={16} fill="none" />
            <circle cx={150} cy={150} r={R} stroke={accent} strokeWidth={16} fill="none" strokeLinecap="round"
              strokeDasharray={C} strokeDashoffset={C * (1 - progress)} transform="rotate(-90 150 150)" />
            <text x={150} y={150} textAnchor="middle" dominantBaseline="central"
              fontSize={72} fontWeight={800} fill={accent} style={{ fontVariantNumeric: 'tabular-nums' }}>
              {fmt(secondsLeft)}
            </text>
          </svg>
          <div className="flex gap-8 text-center">
            <div><div className="text-xl font-bold text-white tabular-nums">{Math.max(1, workProgress)}/{totalRounds}</div><div className="text-xs uppercase tracking-wide text-slate-500">Round</div></div>
            {preset.sets > 1 && <div><div className="text-xl font-bold text-white tabular-nums">{phase?.set ?? 1}/{preset.sets}</div><div className="text-xs uppercase tracking-wide text-slate-500">Set</div></div>}
            <div><div className="text-xl font-bold text-white tabular-nums">{Math.round(total / 60)}</div><div className="text-xs uppercase tracking-wide text-slate-500">Total min</div></div>
          </div>
          <div className="text-sm text-slate-400">
            {phaseIndex + 1 < sequence.length
              ? `Up next · ${PHASE_TITLE[sequence[phaseIndex + 1].kind]} ${fmt(sequence[phaseIndex + 1].seconds)}s`
              : 'Last interval'}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-4">
          <div className="w-24 h-24 rounded-full border-[3px] flex items-center justify-center" style={{ borderColor: accent }}>
            <Check className="w-12 h-12" style={{ color: accent }} />
          </div>
          <div className="text-3xl font-extrabold text-white">Complete</div>
          <div className="text-slate-400">{preset.name} · {totalRounds} rounds · ~{Math.round(total / 60)} min</div>
          <button onClick={logSession} disabled={logged}
            className={`mt-2 flex items-center gap-2 px-6 py-3 rounded-full font-bold ${logged ? 'bg-white/5 border border-emerald-400 text-emerald-400' : 'bg-teal-300 text-slate-900'}`}>
            {logged ? <Check className="w-5 h-5" /> : <PlusCircle className="w-5 h-5" />}
            {logged ? 'Logged to cardio' : 'Log this session'}
          </button>
        </div>
      )}

      {/* controls */}
      <div className="flex items-center gap-8">
        <button onClick={reset} className="w-14 h-14 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-slate-400 hover:text-slate-200">
          <RotateCcw className="w-6 h-6" />
        </button>
        {!finished ? (
          <button onClick={startPause} className="w-20 h-20 rounded-full flex items-center justify-center text-slate-900" style={{ background: accent }}>
            {running ? <Pause className="w-9 h-9" /> : <Play className="w-9 h-9" />}
          </button>
        ) : (
          <button onClick={onClose} className="w-20 h-20 rounded-full bg-white/10 flex items-center justify-center text-white">
            <Check className="w-9 h-9" />
          </button>
        )}
        {!finished ? (
          <button onClick={skip} className="w-14 h-14 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-slate-400 hover:text-slate-200">
            <SkipForward className="w-6 h-6" />
          </button>
        ) : <div className="w-14 h-14" />}
      </div>
    </div>
  )
}
