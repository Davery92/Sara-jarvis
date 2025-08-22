import React, { useState } from 'react';
import { X, ChevronLeft, ChevronRight, Target, Clock, CheckSquare, Hash, Calendar, Zap } from 'lucide-react';
import { apiRequest } from '../utils/api';

interface HabitData {
  title: string;
  type: 'binary' | 'quantitative' | 'checklist' | 'time';
  target_numeric?: number;
  unit?: string;
  rrule: string;
  weekly_minimum?: number;
  windows?: string;
  checklist_mode?: 'all' | 'percent';
  checklist_threshold?: number;
  grace_days: number;
  retro_hours: number;
  notes?: string;
}

interface HabitCreateProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const HABIT_TYPES = [
  {
    type: 'binary',
    icon: CheckSquare,
    title: 'Binary',
    description: 'Simple yes/no habits like "Read for 30 minutes" or "Take vitamins"'
  },
  {
    type: 'quantitative',
    icon: Hash,
    title: 'Quantitative',
    description: 'Measurable habits like "Drink 8 glasses of water" or "Walk 10,000 steps"'
  },
  {
    type: 'checklist',
    icon: Target,
    title: 'Checklist',
    description: 'Multiple items to complete like a morning routine or workout plan'
  },
  {
    type: 'time',
    icon: Clock,
    title: 'Time-based',
    description: 'Time duration habits like "Meditate for 20 minutes" or "Study for 2 hours"'
  }
];

const FREQUENCY_OPTIONS = [
  { value: 'FREQ=DAILY', label: 'Every day', description: 'Daily habit' },
  { value: 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', label: 'Weekdays', description: 'Monday through Friday' },
  { value: 'FREQ=WEEKLY;BYDAY=SA,SU', label: 'Weekends', description: 'Saturday and Sunday' },
  { value: 'FREQ=WEEKLY;INTERVAL=1', label: 'Weekly', description: 'Once per week' },
  { value: 'FREQ=WEEKLY;BYDAY=MO,WE,FR', label: '3x per week', description: 'Monday, Wednesday, Friday' },
  { value: 'custom', label: 'Custom', description: 'Set your own schedule' }
];

export default function HabitCreate({ isOpen, onClose, onCreated }: HabitCreateProps) {
  const [step, setStep] = useState(1);
  const [habitData, setHabitData] = useState<HabitData>({
    title: '',
    type: 'binary',
    rrule: 'FREQ=DAILY',
    grace_days: 0,
    retro_hours: 24
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleNext = () => {
    if (step < 4) setStep(step + 1);
  };

  const handleBack = () => {
    if (step > 1) setStep(step - 1);
  };

  const handleSubmit = async () => {
    if (!habitData.title.trim()) {
      setError('Habit title is required');
      return;
    }

    setLoading(true);
    setError('');

    try {
      await apiRequest('/habits', {
        method: 'POST',
        body: JSON.stringify(habitData)
      });

      onCreated();
      onClose();
      resetForm();
    } catch (err) {
      setError('Failed to create habit. Please try again.');
      console.error('Error creating habit:', err);
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setStep(1);
    setHabitData({
      title: '',
      type: 'binary',
      rrule: 'FREQ=DAILY',
      grace_days: 0,
      retro_hours: 24
    });
    setError('');
  };

  const updateHabitData = (updates: Partial<HabitData>) => {
    setHabitData(prev => ({ ...prev, ...updates }));
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-hidden border border-gray-700">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b">
          <div>
            <h2 className="text-xl font-semibold text-white">Create New Habit</h2>
            <p className="text-sm text-gray-400">Step {step} of 4</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-gray-300 rounded-lg hover:bg-gray-700"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Progress Bar */}
        <div className="px-6 py-3 bg-gray-700 border-t border-gray-600">
          <div className="flex space-x-2">
            {[1, 2, 3, 4].map((stepNum) => (
              <div
                key={stepNum}
                className={`flex-1 h-2 rounded ${
                  stepNum <= step ? 'bg-blue-600' : 'bg-gray-600'
                }`}
              />
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
          {error && (
            <div className="mb-4 p-3 bg-red-900/30 border border-red-700 rounded-lg">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}

          {/* Step 1: Basic Info */}
          {step === 1 && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Habit Title *
                </label>
                <input
                  type="text"
                  value={habitData.title}
                  onChange={(e) => updateHabitData({ title: e.target.value })}
                  placeholder="e.g., Daily Meditation, Drink Water, Morning Workout"
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-3">
                  Habit Type *
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  {HABIT_TYPES.map((type) => (
                    <button
                      key={type.type}
                      onClick={() => updateHabitData({ type: type.type as any })}
                      className={`p-4 rounded-lg border-2 text-left transition-colors ${
                        habitData.type === type.type
                          ? 'border-blue-500 bg-blue-900/30 text-white'
                          : 'border-gray-600 hover:border-gray-500 bg-gray-700 text-gray-300'
                      }`}
                    >
                      <div className="flex items-center mb-2">
                        <type.icon className={`w-5 h-5 mr-2 ${
                          habitData.type === type.type ? 'text-blue-400' : 'text-gray-400'
                        }`} />
                        <span className={`font-medium ${
                          habitData.type === type.type ? 'text-white' : 'text-gray-300'
                        }`}>{type.title}</span>
                      </div>
                      <p className={`text-sm ${
                        habitData.type === type.type ? 'text-blue-200' : 'text-gray-400'
                      }`}>{type.description}</p>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Notes (Optional)
                </label>
                <textarea
                  value={habitData.notes || ''}
                  onChange={(e) => updateHabitData({ notes: e.target.value })}
                  placeholder="Add any notes or motivation for this habit..."
                  rows={3}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
            </div>
          )}

          {/* Step 2: Target & Measurement */}
          {step === 2 && (
            <div className="space-y-6">
              <h3 className="text-lg font-medium text-white mb-4">
                {habitData.type === 'binary' && 'Completion Criteria'}
                {habitData.type === 'quantitative' && 'Target Amount'}
                {habitData.type === 'checklist' && 'Checklist Configuration'}
                {habitData.type === 'time' && 'Time Target'}
              </h3>

              {habitData.type === 'binary' && (
                <div className="bg-blue-900/30 p-4 rounded-lg border border-blue-700">
                  <p className="text-blue-300">
                    Binary habits are simple yes/no completions. Just mark them as done when you complete them!
                  </p>
                </div>
              )}

              {(habitData.type === 'quantitative' || habitData.type === 'time') && (
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Target Amount *
                    </label>
                    <input
                      type="number"
                      value={habitData.target_numeric || ''}
                      onChange={(e) => updateHabitData({ target_numeric: parseFloat(e.target.value) || undefined })}
                      placeholder="e.g., 8, 10000, 30"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Unit *
                    </label>
                    <input
                      type="text"
                      value={habitData.unit || ''}
                      onChange={(e) => updateHabitData({ unit: e.target.value })}
                      placeholder={habitData.type === 'time' ? 'minutes' : 'glasses, steps, pages'}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                  </div>
                </div>
              )}

              {habitData.type === 'checklist' && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Completion Mode
                    </label>
                    <div className="space-y-2">
                      <label className="flex items-center">
                        <input
                          type="radio"
                          name="checklist_mode"
                          value="all"
                          checked={habitData.checklist_mode === 'all'}
                          onChange={(e) => updateHabitData({ checklist_mode: e.target.value as 'all' })}
                          className="mr-2"
                        />
                        <span className="text-gray-300">Complete all items</span>
                      </label>
                      <label className="flex items-center">
                        <input
                          type="radio"
                          name="checklist_mode"
                          value="percent"
                          checked={habitData.checklist_mode === 'percent'}
                          onChange={(e) => updateHabitData({ checklist_mode: e.target.value as 'percent' })}
                          className="mr-2"
                        />
                        <span className="text-gray-300">Complete a percentage of items</span>
                      </label>
                    </div>
                  </div>

                  {habitData.checklist_mode === 'percent' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-2">
                        Minimum Percentage
                      </label>
                      <input
                        type="number"
                        min="0"
                        max="100"
                        value={(habitData.checklist_threshold || 0) * 100}
                        onChange={(e) => updateHabitData({ checklist_threshold: parseFloat(e.target.value) / 100 })}
                        className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      />
                      <p className="text-sm text-gray-400 mt-1">Percentage of checklist items that must be completed</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Step 3: Schedule */}
          {step === 3 && (
            <div className="space-y-6">
              <h3 className="text-lg font-medium text-white mb-4">Schedule</h3>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-3">
                  Frequency *
                </label>
                <div className="space-y-2">
                  {FREQUENCY_OPTIONS.map((option) => (
                    <label key={option.value} className="flex items-center p-3 border border-gray-600 rounded-lg hover:bg-gray-700 bg-gray-800">
                      <input
                        type="radio"
                        name="frequency"
                        value={option.value}
                        checked={habitData.rrule === option.value}
                        onChange={(e) => updateHabitData({ rrule: e.target.value })}
                        className="mr-3"
                      />
                      <div>
                        <div className="font-medium text-gray-300">{option.label}</div>
                        <div className="text-sm text-gray-400">{option.description}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              {habitData.rrule === 'custom' && (
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Custom RRULE
                  </label>
                  <input
                    type="text"
                    value={habitData.rrule}
                    onChange={(e) => updateHabitData({ rrule: e.target.value })}
                    placeholder="FREQ=WEEKLY;BYDAY=MO,WE,FR"
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <p className="text-sm text-gray-400 mt-1">
                    Use RFC 5545 RRULE format. <a href="#" className="text-blue-400 hover:underline">Learn more</a>
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Step 4: Advanced Settings */}
          {step === 4 && (
            <div className="space-y-6">
              <h3 className="text-lg font-medium text-white mb-4">Advanced Settings</h3>

              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Grace Days
                  </label>
                  <input
                    type="number"
                    min="0"
                    max="7"
                    value={habitData.grace_days}
                    onChange={(e) => updateHabitData({ grace_days: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <p className="text-sm text-gray-400 mt-1">
                    Days you can miss before breaking your streak
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Retro Hours
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="168"
                    value={habitData.retro_hours}
                    onChange={(e) => updateHabitData({ retro_hours: parseInt(e.target.value) || 24 })}
                    className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  <p className="text-sm text-gray-400 mt-1">
                    Hours you can log past completions
                  </p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Time Windows (Optional)
                </label>
                <input
                  type="text"
                  value={habitData.windows || ''}
                  onChange={(e) => updateHabitData({ windows: e.target.value })}
                  placeholder='[{"name":"Morning","start":"06:00","end":"10:00"}]'
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <p className="text-sm text-gray-400 mt-1">
                  JSON format for specific time windows (optional)
                </p>
              </div>

              {/* Summary */}
              <div className="bg-gray-700 p-4 rounded-lg border border-gray-600">
                <h4 className="font-medium text-white mb-2">Habit Summary</h4>
                <ul className="text-sm text-gray-300 space-y-1">
                  <li><strong>Title:</strong> {habitData.title || 'Unnamed Habit'}</li>
                  <li><strong>Type:</strong> {habitData.type}</li>
                  <li><strong>Schedule:</strong> {FREQUENCY_OPTIONS.find(f => f.value === habitData.rrule)?.label || 'Custom'}</li>
                  {habitData.target_numeric && (
                    <li><strong>Target:</strong> {habitData.target_numeric} {habitData.unit}</li>
                  )}
                  <li><strong>Grace Days:</strong> {habitData.grace_days}</li>
                </ul>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-6 border-t border-gray-600 bg-gray-700">
          <button
            onClick={step === 1 ? onClose : handleBack}
            className="flex items-center px-4 py-2 text-gray-400 hover:text-gray-200 transition-colors"
          >
            {step === 1 ? (
              <>
                <X className="w-4 h-4 mr-2" />
                Cancel
              </>
            ) : (
              <>
                <ChevronLeft className="w-4 h-4 mr-2" />
                Back
              </>
            )}
          </button>

          <button
            onClick={step === 4 ? handleSubmit : handleNext}
            disabled={loading || !habitData.title.trim()}
            className="flex items-center px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                Creating...
              </>
            ) : step === 4 ? (
              <>
                <Zap className="w-4 h-4 mr-2" />
                Create Habit
              </>
            ) : (
              <>
                Next
                <ChevronRight className="w-4 h-4 ml-2" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}