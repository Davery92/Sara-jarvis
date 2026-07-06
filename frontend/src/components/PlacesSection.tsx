import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, KnownPlace, PlaceCreate, LocationTrigger } from '../api/client'

const PLACE_TYPES = ['home', 'work', 'gym', 'client_site', 'store', 'other']

function formatRelative(iso: string | null): string {
  if (!iso) return 'Never'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diff = Math.max(0, now - then)
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}

function AddPlaceForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [placeType, setPlaceType] = useState('other')
  const [address, setAddress] = useState('')
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null)
  const [geocodeError, setGeocodeError] = useState<string | null>(null)

  const geocodeMutation = useMutation({
    mutationFn: (addr: string) => apiClient.geocodeAddress(addr),
    onSuccess: (result) => {
      setCoords(result)
      setGeocodeError(null)
    },
    onError: () => {
      setCoords(null)
      setGeocodeError('Could not find that address.')
    },
  })

  const createMutation = useMutation({
    mutationFn: (data: PlaceCreate) => apiClient.createPlace(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['places'] })
      onClose()
    },
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!coords) return
    createMutation.mutate({
      name: name.trim(),
      place_type: placeType,
      latitude: coords.latitude,
      longitude: coords.longitude,
    })
  }

  return (
    <form
      onSubmit={submit}
      className="mb-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4 space-y-3"
    >
      <div>
        <label className="mb-1.5 block text-sm text-slate-300">Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Home, Jones' Office"
          required
          className="w-full bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-2 text-sm text-white placeholder:text-slate-600"
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm text-slate-300">Type</label>
        <select
          value={placeType}
          onChange={(e) => setPlaceType(e.target.value)}
          className="w-full bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-2 text-sm text-white"
        >
          {PLACE_TYPES.map((t) => (
            <option key={t} value={t}>{t.replace('_', ' ')}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1.5 block text-sm text-slate-300">Address</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={address}
            onChange={(e) => { setAddress(e.target.value); setCoords(null) }}
            placeholder="123 Main St, City, State"
            className="flex-1 bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-2 text-sm text-white placeholder:text-slate-600"
          />
          <button
            type="button"
            onClick={() => address.trim() && geocodeMutation.mutate(address.trim())}
            disabled={!address.trim() || geocodeMutation.isPending}
            className="rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 hover:bg-white/[0.06] hover:text-white disabled:opacity-40 whitespace-nowrap"
          >
            {geocodeMutation.isPending ? 'Looking up…' : 'Find'}
          </button>
        </div>
        {coords && (
          <p className="mt-1 text-xs text-teal-300/80">
            Found: {coords.latitude.toFixed(5)}, {coords.longitude.toFixed(5)}
          </p>
        )}
        {geocodeError && <p className="mt-1 text-xs text-rose-300">{geocodeError}</p>}
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onClose}
          className="rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 hover:bg-white/[0.06]"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!coords || !name.trim() || createMutation.isPending}
          className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 hover:bg-teal-300 disabled:opacity-50"
        >
          {createMutation.isPending ? 'Saving…' : 'Save place'}
        </button>
      </div>
    </form>
  )
}

function SuggestionsList() {
  const queryClient = useQueryClient()
  const { data: suggestions } = useQuery({
    queryKey: ['places', 'suggestions'],
    queryFn: () => apiClient.listSuggestedPlaces(),
    refetchInterval: 60000,
  })
  const [namingId, setNamingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [placeType, setPlaceType] = useState('other')

  const confirmMutation = useMutation({
    mutationFn: ({ id, name, placeType }: { id: string; name: string; placeType: string }) =>
      apiClient.confirmSuggestedPlace(id, name, placeType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['places'] })
      setNamingId(null)
    },
  })

  const dismissMutation = useMutation({
    mutationFn: (id: string) => apiClient.dismissSuggestedPlace(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['places'] }),
  })

  if (!suggestions || suggestions.length === 0) return null

  return (
    <div className="mb-6">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-1.5">
        Suggested places
      </h3>
      <p className="text-xs text-slate-500 mb-2">
        Sara noticed you visit these spots regularly. Save the ones worth naming.
      </p>
      {suggestions.map((s) => (
        <div key={s.id} className="rounded-lg hover:bg-white/[0.04] transition-colors px-3 py-2">
          {namingId === s.id ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={s.name}
                autoFocus
                className="min-w-[140px] flex-1 bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-3 py-1.5 text-sm text-white placeholder:text-slate-600"
              />
              <select
                value={placeType}
                onChange={(e) => setPlaceType(e.target.value)}
                className="bg-white/[0.04] border border-white/10 rounded-xl focus:border-teal-300/30 outline-none px-2 py-1.5 text-sm text-white"
              >
                {PLACE_TYPES.map((t) => (
                  <option key={t} value={t}>{t.replace('_', ' ')}</option>
                ))}
              </select>
              <button
                onClick={() => confirmMutation.mutate({ id: s.id, name: name.trim() || s.name, placeType })}
                disabled={confirmMutation.isPending}
                className="rounded-xl bg-teal-400/90 px-3 py-1.5 text-xs font-medium text-slate-950 hover:bg-teal-300 disabled:opacity-50"
              >
                Save
              </button>
              <button
                onClick={() => setNamingId(null)}
                className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06]"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <span className="text-[15px] text-slate-200 truncate">{s.name}</span>
                <div className="text-xs text-slate-500">Visited {s.visit_count}× recently</div>
              </div>
              <div className="flex gap-1.5 shrink-0">
                <button
                  onClick={() => { setNamingId(s.id); setName(s.name); setPlaceType('other') }}
                  className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06] hover:text-white"
                >
                  Save as place
                </button>
                <button
                  onClick={() => dismissMutation.mutate(s.id)}
                  disabled={dismissMutation.isPending}
                  className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-500 hover:bg-white/[0.06] hover:text-white disabled:opacity-40"
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function PlacesList() {
  const queryClient = useQueryClient()
  const { data: places, isLoading } = useQuery({
    queryKey: ['places'],
    queryFn: () => apiClient.listPlaces(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deletePlace(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['places'] }),
  })

  if (isLoading) return <p className="text-sm text-slate-500">Loading places…</p>
  if (!places || places.length === 0) {
    return <p className="text-sm text-slate-500">No saved places yet — tell Sara "remember this place as home" while you're there, or add one below.</p>
  }

  return (
    <div className="mb-2">
      {places.map((p) => (
        <div key={p.id} className="flex items-center justify-between gap-3 rounded-lg hover:bg-white/[0.04] transition-colors px-3 py-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[15px] text-slate-200 truncate">{p.name}</span>
              <span className="text-[10px] px-1.5 py-0.5 border border-white/10 rounded text-slate-500 uppercase tracking-wide">
                {p.place_type.replace('_', ' ')}
              </span>
            </div>
            <div className="text-xs text-slate-500">
              {p.visit_count} visit{p.visit_count !== 1 ? 's' : ''} · last seen {formatRelative(p.last_seen_at)}
            </div>
          </div>
          <button
            onClick={() => deleteMutation.mutate(p.id)}
            disabled={deleteMutation.isPending}
            className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-500 hover:bg-white/[0.06] hover:text-white disabled:opacity-40 shrink-0"
          >
            Forget
          </button>
        </div>
      ))}
    </div>
  )
}

function TriggersList() {
  const queryClient = useQueryClient()
  const { data: triggers } = useQuery({
    queryKey: ['location-triggers'],
    queryFn: () => apiClient.listLocationTriggers(),
  })

  const cancelMutation = useMutation({
    mutationFn: (id: string) => apiClient.cancelLocationTrigger(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['location-triggers'] }),
  })

  if (!triggers || triggers.length === 0) return null

  return (
    <div className="mt-6">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-1.5">
        Active location reminders
      </h3>
      {triggers.map((t: LocationTrigger) => (
        <div key={t.id} className="flex items-center justify-between gap-3 rounded-lg hover:bg-white/[0.04] transition-colors px-3 py-2">
          <div className="min-w-0">
            <span className="text-[15px] text-slate-200 truncate">{t.reminder_title}</span>
            <div className="text-xs text-slate-500">
              When you {t.trigger_on === 'enter' ? 'arrive at' : 'leave'} {t.label}
              {t.recurring ? ' · every time' : ' · one-time'}
            </div>
          </div>
          <button
            onClick={() => cancelMutation.mutate(t.id)}
            disabled={cancelMutation.isPending}
            className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-500 hover:bg-white/[0.06] hover:text-white disabled:opacity-40 shrink-0"
          >
            Cancel
          </button>
        </div>
      ))}
    </div>
  )
}

export default function PlacesSection() {
  const [showAddForm, setShowAddForm] = useState(false)

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Places &amp; location reminders
        </h2>
        <button
          onClick={() => setShowAddForm((v) => !v)}
          className="text-xs text-slate-500 hover:text-teal-300 transition-colors"
        >
          {showAddForm ? 'Cancel' : '+ Add place'}
        </button>
      </div>

      {showAddForm && <AddPlaceForm onClose={() => setShowAddForm(false)} />}

      <SuggestionsList />
      <PlacesList />
      <TriggersList />
    </div>
  )
}
