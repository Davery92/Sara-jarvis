import React, { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'
import { getLocalDateString } from '../../utils/dateUtils'

interface RecoveryData {
  id?: string
  log_date: string
  hrv?: number | null
  heart_rate?: number | null
  sleep_hours?: number | null
  soreness_level?: number | null
  body_weight?: number | null
  weight_unit?: string
  notes?: string
}

interface RecoveryLogProps {
  onSave?: () => void
}

const RecoveryLog: React.FC<RecoveryLogProps> = ({ onSave }) => {
  const [selectedDate, setSelectedDate] = useState(getLocalDateString())
  const [hrv, setHrv] = useState<string>('')
  const [heartRate, setHeartRate] = useState<string>('')
  const [sleepHours, setSleepHours] = useState<string>('')
  const [sorenessLevel, setSorenessLevel] = useState<number>(5)
  const [bodyWeight, setBodyWeight] = useState<string>('')
  const [weightUnit, setWeightUnit] = useState<string>('lbs')
  const [notes, setNotes] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [saveStatus, setSaveStatus] = useState<{ type: 'success' | 'error', message: string } | null>(null)

  // Load data when date changes
  useEffect(() => {
    loadRecoveryData(selectedDate)
  }, [selectedDate])

  const loadRecoveryData = async (date: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/recovery/${date}`, {
        credentials: 'include'
      })

      if (response.ok) {
        const data: RecoveryData = await response.json()
        if (data) {
          setHrv(data.hrv?.toString() || '')
          setHeartRate(data.heart_rate?.toString() || '')
          setSleepHours(data.sleep_hours?.toString() || '')
          setSorenessLevel(data.soreness_level || 5)
          setBodyWeight(data.body_weight?.toString() || '')
          setWeightUnit(data.weight_unit || 'lbs')
          setNotes(data.notes || '')
        } else {
          // No data for this date, clear form
          setHrv('')
          setHeartRate('')
          setSleepHours('')
          setSorenessLevel(5)
          setBodyWeight('')
          setWeightUnit('lbs')
          setNotes('')
        }
      } else {
        // No data for this date
        setHrv('')
        setHeartRate('')
        setSleepHours('')
        setSorenessLevel(5)
        setBodyWeight('')
        setWeightUnit('lbs')
        setNotes('')
      }
    } catch (error) {
      console.error('Failed to load recovery data:', error)
    }
  }

  const handleSave = async () => {
    setLoading(true)
    setSaveStatus(null)

    try {
      const payload: RecoveryData = {
        log_date: selectedDate,
        hrv: hrv ? parseInt(hrv) : null,
        heart_rate: heartRate ? parseInt(heartRate) : null,
        sleep_hours: sleepHours ? parseFloat(sleepHours) : null,
        soreness_level: sorenessLevel,
        body_weight: bodyWeight ? parseFloat(bodyWeight) : null,
        weight_unit: weightUnit,
        notes: notes || ''
      }

      const response = await fetch(`${APP_CONFIG.apiUrl}/api/fitness/recovery`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        credentials: 'include',
        body: JSON.stringify(payload)
      })

      if (response.ok) {
        setSaveStatus({ type: 'success', message: 'Recovery data saved successfully!' })
        setTimeout(() => setSaveStatus(null), 3000)
        if (onSave) onSave()
      } else {
        const error = await response.json()
        setSaveStatus({ type: 'error', message: error.detail || 'Failed to save recovery data' })
      }
    } catch (error) {
      setSaveStatus({ type: 'error', message: 'Failed to save recovery data' })
    } finally {
      setLoading(false)
    }
  }

  const getSorenessLabel = (level: number) => {
    if (level <= 2) return 'Fresh'
    if (level <= 4) return 'Minimal'
    if (level <= 6) return 'Moderate'
    if (level <= 8) return 'High'
    return 'Very High'
  }

  const getSorenessColor = (level: number) => {
    if (level <= 2) return 'text-green-400'
    if (level <= 4) return 'text-blue-400'
    if (level <= 6) return 'text-yellow-400'
    if (level <= 8) return 'text-orange-400'
    return 'text-red-400'
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <h2 className="text-2xl font-bold text-white mb-6">Log Today's Recovery</h2>

      {/* Date Picker */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Date
        </label>
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          max={getLocalDateString()}
          className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {/* HRV Input */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            HRV (ms)
          </label>
          <input
            type="number"
            value={hrv}
            onChange={(e) => setHrv(e.target.value)}
            placeholder="e.g., 60"
            min="0"
            max="200"
            className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500"
          />
        </div>

        {/* Heart Rate Input */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Resting HR (bpm)
          </label>
          <input
            type="number"
            value={heartRate}
            onChange={(e) => setHeartRate(e.target.value)}
            placeholder="e.g., 55"
            min="30"
            max="120"
            className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500"
          />
        </div>

        {/* Sleep Hours Input */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Sleep (hours)
          </label>
          <input
            type="number"
            value={sleepHours}
            onChange={(e) => setSleepHours(e.target.value)}
            placeholder="e.g., 7.5"
            min="0"
            max="24"
            step="0.5"
            className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500"
          />
        </div>

        {/* Body Weight Input */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Body Weight
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              value={bodyWeight}
              onChange={(e) => setBodyWeight(e.target.value)}
              placeholder="185.5"
              min="0"
              max="999"
              step="0.1"
              className="flex-1 px-4 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500"
            />
            <select
              value={weightUnit}
              onChange={(e) => setWeightUnit(e.target.value)}
              className="px-3 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500"
            >
              <option value="lbs">lbs</option>
              <option value="kg">kg</option>
            </select>
          </div>
        </div>
      </div>

      {/* Soreness Slider */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Soreness Level: <span className={`font-bold ${getSorenessColor(sorenessLevel)}`}>
            {sorenessLevel} - {getSorenessLabel(sorenessLevel)}
          </span>
        </label>
        <div className="flex items-center gap-4">
          <span className="text-gray-400 text-sm">1</span>
          <input
            type="range"
            min="1"
            max="10"
            value={sorenessLevel}
            onChange={(e) => setSorenessLevel(parseInt(e.target.value))}
            className="flex-1 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer slider-thumb"
            style={{
              background: `linear-gradient(to right,
                #10b981 0%,
                #3b82f6 25%,
                #eab308 50%,
                #f97316 75%,
                #ef4444 100%)`
            }}
          />
          <span className="text-gray-400 text-sm">10</span>
        </div>
      </div>

      {/* Notes */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Notes (optional)
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="How are you feeling? Any issues or observations?"
          rows={3}
          className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded text-white focus:outline-none focus:border-teal-500 resize-none"
        />
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-between">
        <button
          onClick={handleSave}
          disabled={loading}
          className="px-6 py-2 bg-teal-600 hover:bg-teal-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded font-medium transition-colors"
        >
          {loading ? 'Saving...' : 'Save Recovery Data'}
        </button>

        {saveStatus && (
          <div className={`text-sm font-medium ${
            saveStatus.type === 'success' ? 'text-green-400' : 'text-red-400'
          }`}>
            {saveStatus.message}
          </div>
        )}
      </div>

      {/* Quick Info */}
      <div className="mt-6 p-4 bg-gray-900 rounded border border-gray-700">
        <p className="text-sm text-gray-400">
          <span className="font-medium text-gray-300">💡 Tip:</span> Track your recovery metrics daily to help Sara provide better workout recommendations based on your readiness.
        </p>
      </div>
    </div>
  )
}

export default RecoveryLog
