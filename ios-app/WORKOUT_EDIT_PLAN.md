# Workout Time & Edit Feature Implementation Plan

## Overview
Add ability to:
1. Set custom date/time when logging workouts
2. Edit existing workouts (change date/time, weights, reps, RPE)

## Files to Modify

### 1. Frontend TypeScript Interface Updates

**File: `src/services/fitness.ts`**

Add to `CreateWorkoutSetParams`:
```typescript
export interface CreateWorkoutSetParams {
  exercise_name: string;
  set_index: number;
  weight: number;
  reps: number;
  rpe?: number;
  notes?: string;
  session_date?: string;  // NEW: ISO date string YYYY-MM-DD
  session_time?: string;   // NEW: ISO datetime string for full timestamp
}
```

Add new service methods:
```typescript
async updateWorkoutSet(id: string, params: Partial<CreateWorkoutSetParams>): Promise<WorkoutSet> {
  return await apiClient.patch<WorkoutSet>(`/api/fitness/workout-log/${id}`, params);
}

async getWorkoutDetails(workoutId: string): Promise<WorkoutSession> {
  return await apiClient.get(`/api/fitness/workouts/${workoutId}`);
}
```

### 2. WorkoutLogModal - Add Date/Time Picker

**File: `src/components/fitness/WorkoutLogModal.tsx`**

Add state:
```typescript
const [workoutDate, setWorkoutDate] = useState(new Date());
const [showDatePicker, setShowDatePicker] = useState(false);
const [showTimePicker, setShowTimePicker] = useState(false);
```

Add date/time picker UI (after exercise name input):
```typescript
<View style={styles.dateTimeSection}>
  <Text style={styles.label}>Workout Date & Time</Text>
  <TouchableOpacity onPress={() => setShowDatePicker(true)} style={styles.dateTimeButton}>
    <Text style={styles.dateTimeText}>
      {workoutDate.toLocaleDateString()} {workoutDate.toLocaleTimeString()}
    </Text>
  </TouchableOpacity>
</View>

{showDatePicker && (
  <DateTimePicker
    value={workoutDate}
    mode="date"
    display={Platform.OS === 'ios' ? 'spinner' : 'default'}
    onChange={(event, selectedDate) => {
      setShowDatePicker(Platform.OS === 'ios');
      if (selectedDate) {
        setWorkoutDate(selectedDate);
        if (Platform.OS !== 'ios') {
          setShowTimePicker(true);
        }
      }
    }}
  />
)}

{showTimePicker && (
  <DateTimePicker
    value={workoutDate}
    mode="time"
    display={Platform.OS === 'ios' ? 'spinner' : 'default'}
    onChange={(event, selectedTime) => {
      setShowTimePicker(false);
      if (selectedTime) {
        setWorkoutDate(selectedTime);
      }
    }}
  />
)}
```

Update `handleSubmitCustom` to include session_date:
```typescript
const sessionDate = workoutDate.toISOString().split('T')[0]; // YYYY-MM-DD
const sessionTime = workoutDate.toISOString(); // Full ISO timestamp

await fitnessService.createWorkoutSet({
  exercise_name: exerciseName,
  set_index: i + 1,
  weight: set.weight,
  reps: set.reps,
  rpe: set.rpe,
  notes: i === 0 ? notes : undefined,
  session_date: sessionDate,
  session_time: sessionTime,
});
```

### 3. Create WorkoutEditModal Component

**File: `src/components/fitness/WorkoutEditModal.tsx`** (NEW FILE)

```typescript
import React, { useState, useEffect } from 'react';
import {
  View,
  Modal,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import DateTimePicker from '@react-native-community/datetimepicker';
import { fitnessService, WorkoutSession, WorkoutSet } from '../../services/fitness';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface Props {
  visible: boolean;
  workoutSession: WorkoutSession | null;
  onClose: () => void;
  onComplete: () => void;
}

export default function WorkoutEditModal({ visible, workoutSession, onClose, onComplete }: Props) {
  const [loading, setLoading] = useState(false);
  const [workoutDate, setWorkoutDate] = useState(new Date());
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);
  const [sets, setSets] = useState<WorkoutSet[]>([]);

  useEffect(() => {
    if (workoutSession) {
      setSets([...workoutSession.exercises]);
      const dateStr = workoutSession.session_date || workoutSession.created_at;
      setWorkoutDate(new Date(dateStr));
    }
  }, [workoutSession]);

  const updateSet = (index: number, field: 'weight' | 'reps' | 'rpe', value: number) => {
    const newSets = [...sets];
    newSets[index][field] = value;
    setSets(newSets);
  };

  const handleSave = async () => {
    setLoading(true);
    try {
      // Update each set
      for (const set of sets) {
        await fitnessService.updateWorkoutSet(set.id, {
          weight: set.weight,
          reps: set.reps,
          rpe: set.rpe,
          session_date: workoutDate.toISOString().split('T')[0],
          session_time: workoutDate.toISOString(),
        });
      }
      onComplete();
      onClose();
    } catch (error) {
      console.error('Failed to update workout:', error);
      Alert.alert('Error', 'Failed to update workout');
    } finally {
      setLoading(false);
    }
  };

  // Render date/time picker and set editing UI
  // (Similar to WorkoutLogModal but for editing)
}
```

### 4. Update FitnessScreen to Use Edit Modal

**File: `src/screens/fitness/FitnessScreen.tsx`**

Add state:
```typescript
const [showEditModal, setShowEditModal] = useState(false);
const [selectedWorkout, setSelectedWorkout] = useState<WorkoutSession | null>(null);
```

Update `handleViewWorkout`:
```typescript
const handleViewWorkout = (session: WorkoutSession) => {
  setSelectedWorkout(session);
  setShowEditModal(true);
};
```

Add modal to JSX:
```typescript
<WorkoutEditModal
  visible={showEditModal}
  workoutSession={selectedWorkout}
  onClose={() => {
    setShowEditModal(false);
    setSelectedWorkout(null);
  }}
  onComplete={() => {
    loadData();
  }}
/>
```

### 5. Backend Changes

**File: `backend/app/tools/fitness/workout_log.py`**

Update `execute` method to accept and use `session_date`:
```python
async def execute(self, user_id: str, **kwargs) -> ToolResult:
    exercise_id = kwargs.get("exercise_id")
    set_index = kwargs.get("set_index")
    weight = kwargs.get("weight")
    reps = kwargs.get("reps")
    rpe = kwargs.get("rpe")
    notes = kwargs.get("notes", "")
    session_date_str = kwargs.get("session_date")  # NEW
    session_time_str = kwargs.get("session_time")  # NEW

    # Use provided date or default to today
    if session_date_str:
        today = datetime.fromisoformat(session_date_str).date()
    else:
        today = datetime.now(timezone.utc).date()

    workout_title = f"Workout - {today.strftime('%Y-%m-%d')}"

    # Rest of the logic remains the same...
```

**File: `backend/app/routes/fitness.py`**

Add PATCH endpoint for updating workout sets:
```python
@router.patch("/workout-log/{set_id}")
async def update_workout_set(
    set_id: str,
    updates: WorkoutSetLog,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """Update an existing workout set"""
    from sqlalchemy import text

    try:
        update_sql = text("""
            UPDATE workout_log
            SET weight = :weight,
                reps = :reps,
                rpe = :rpe,
                session_date = :session_date,
                notes = :notes
            WHERE id = :set_id AND user_id = :user_id
        """)

        result = db.execute(update_sql, {
            "set_id": set_id,
            "user_id": user_id,
            "weight": updates.weight,
            "reps": updates.reps,
            "rpe": updates.rpe,
            "session_date": updates.session_date if hasattr(updates, 'session_date') else None,
            "notes": updates.notes
        })
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workout set not found")

        return {"success": True, "message": "Workout set updated"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update workout set: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

## Implementation Order

1. ✅ Add DateTimePicker import to WorkoutLogModal
2. Add session_date fields to TypeScript interfaces
3. Add date/time picker to WorkoutLogModal
4. Update backend tool to accept session_date
5. Create WorkoutEditModal component
6. Update FitnessScreen to use edit modal
7. Add backend PATCH endpoint
8. Test end-to-end workflow

## Testing Checklist

- [ ] Log workout with custom date (yesterday)
- [ ] Log workout with custom time
- [ ] Tap workout card to open edit modal
- [ ] Change workout date in edit modal
- [ ] Change workout time in edit modal
- [ ] Modify weights/reps/RPE in edit modal
- [ ] Save changes and verify they persist
- [ ] Verify workouts display with correct dates
