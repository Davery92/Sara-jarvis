# Habit Tracker System - Complete Guide

## Overview

The Sara AI Hub includes a comprehensive habit tracking system that supports multiple habit types, flexible scheduling, streak tracking, and detailed analytics. This document explains how the system works from both a user and technical perspective.

## Table of Contents

1. [User Features](#user-features)
2. [Habit Types](#habit-types)
3. [Scheduling System](#scheduling-system)
4. [Technical Architecture](#technical-architecture)
5. [Database Schema](#database-schema)
6. [API Endpoints](#api-endpoints)
7. [Frontend Components](#frontend-components)
8. [Background Workers](#background-workers)
9. [Development Setup](#development-setup)

## User Features

### 🎯 Core Functionality

- **Multiple Habit Types**: Binary, quantitative, checklist, and time-based habits
- **Flexible Scheduling**: Uses RFC 5545 RRULE for complex recurrence patterns
- **Streak Tracking**: Current and best streaks with vacation/pause support
- **Progress Analytics**: Detailed insights, trends, and performance metrics
- **Dark Theme UI**: Fully integrated with Sara's dark theme interface
- **Real-time Updates**: Instant progress updates and streak calculations

### 📱 User Interface

- **Today View**: Daily habit tracking with quick logging
- **Insights Page**: Analytics dashboard with performance metrics
- **Create Wizard**: Step-by-step habit creation with all options
- **Edit Functionality**: Modify existing habits with inline editing
- **Progress Visualization**: Circular progress rings and trend charts

## Habit Types

### 1. Binary Habits
**Simple yes/no completion**
- Examples: "Read for 30 minutes", "Take vitamins", "Exercise"
- Progress: 0% (not done) or 100% (completed)
- Logging: Single click to mark complete

### 2. Quantitative Habits
**Measurable with target amounts**
- Examples: "Drink 8 glasses of water", "Walk 10,000 steps"
- Progress: Accumulated amount toward target (e.g., 40/64 oz = 62%)
- Logging: Enter amounts with quick-add buttons (+8oz, +16oz, etc.)

### 3. Checklist Habits
**Multiple items to complete**
- Examples: Morning routine, workout plan, cleaning tasks
- Progress: Percentage of completed items or all-items completion
- Logging: Check off individual items

### 4. Time-based Habits
**Duration tracking**
- Examples: "Meditate for 20 minutes", "Study for 2 hours"
- Progress: Accumulated time toward target duration
- Logging: Time tracking with start/stop functionality

## Scheduling System

### RRULE (RFC 5545) Support
The system uses industry-standard RRULE for flexible recurrence:

```
FREQ=DAILY                    # Every day
FREQ=WEEKLY;BYDAY=MO,WE,FR   # Monday, Wednesday, Friday
FREQ=WEEKLY;INTERVAL=2        # Every 2 weeks
FREQ=MONTHLY;BYMONTHDAY=1     # First of every month
```

### Time Windows
Habits can have specific time windows:
- **Morning**: 6:00 AM - 12:00 PM
- **Afternoon**: 12:00 PM - 6:00 PM  
- **Evening**: 6:00 PM - 12:00 AM
- **Custom**: Any specified time range

### Grace Days & Retro Logging
- **Grace Days**: Allow completion X days after due date
- **Retro Hours**: How far back you can log (e.g., 24 hours)
- **Pause/Vacation**: Temporarily suspend habits without breaking streaks

## Technical Architecture

### Backend (FastAPI + Python)

```
backend/
├── app/
│   ├── main_simple.py              # Main API server
│   ├── services/
│   │   ├── habit_scheduler.py      # RRULE processing & instance generation
│   │   ├── habit_progress.py       # Progress calculation algorithms
│   │   ├── habit_streaks.py        # Streak tracking & maintenance
│   │   └── habit_instances.py      # Daily instance management
│   └── workers/
│       ├── habit_scheduler_worker.py    # Nightly instance generation
│       ├── habit_streak_worker.py       # Daily streak maintenance
│       ├── habit_ntfy_worker.py         # Push notifications
│       ├── habit_neo4j_worker.py        # Graph database sync
│       └── habit_worker_coordinator.py  # Worker orchestration
```

### Frontend (React + TypeScript)

```
frontend/src/components/
├── HabitToday.tsx          # Daily habit tracking interface
├── HabitCreate.tsx         # 4-step habit creation wizard
├── HabitInsights.tsx       # Analytics dashboard
├── HabitProgress.tsx       # Progress visualization components
└── HabitStreak.tsx         # Streak display and motivation
```

## Database Schema

### Core Tables

#### `habits`
```sql
- id (UUID, Primary Key)
- user_id (UUID, Foreign Key)
- title (VARCHAR)
- type (ENUM: binary, quantitative, checklist, time)
- target_numeric (FLOAT)     # For quantitative/time habits
- unit (VARCHAR)             # oz, steps, minutes, etc.
- rrule (TEXT)              # RFC 5545 recurrence rule
- grace_days (INTEGER)       # Days after due for completion
- retro_hours (INTEGER)      # Hours back for retroactive logging
- windows (JSON)            # Time windows for completion
- paused (BOOLEAN)          # Temporary pause state
- current_streak (INTEGER)   # Current consecutive days
- best_streak (INTEGER)      # Best streak ever achieved
- last_completed (DATE)      # Most recent completion
- created_at (TIMESTAMP)
```

#### `habit_instances`
```sql
- id (UUID, Primary Key)
- habit_id (UUID, Foreign Key)
- date (DATE)               # Due date
- window (VARCHAR)          # morning, afternoon, evening
- expected (BOOLEAN)        # Should this instance exist?
- status (ENUM)             # pending, in_progress, complete, skipped
- progress (FLOAT)          # 0.0 to 1.0
- total_amount (FLOAT)      # Accumulated amount
- target (FLOAT)            # Target for this instance
```

#### `habit_logs`
```sql
- id (UUID, Primary Key)
- habit_id (UUID, Foreign Key)
- instance_id (UUID, Foreign Key)
- ts (TIMESTAMP)            # When logged
- amount (FLOAT)            # Amount logged
- source (VARCHAR)          # manual, automatic, imported
- payload (JSON)            # Additional data
```

#### `habit_streaks`
```sql
- habit_id (UUID, Primary Key)
- current_streak (INTEGER)
- best_streak (INTEGER)
- last_completed (DATE)
- last_broken (DATE)
- vacation_from (DATE)      # Pause start
- vacation_to (DATE)        # Pause end
```

## API Endpoints

### Core CRUD Operations
```http
POST   /habits                    # Create new habit
GET    /habits                    # List user's habits
PATCH  /habits/{id}               # Update habit
DELETE /habits/{id}               # Delete habit
POST   /habits/{id}/pause         # Pause habit
POST   /habits/{id}/resume        # Resume habit
```

### Daily Operations
```http
GET    /habits/today              # Get today's habit instances
POST   /habits/{id}/log           # Log habit completion/progress
GET    /habits/{id}/streak        # Get streak information
```

### Analytics & Insights
```http
GET    /insights/habits           # Analytics dashboard data
GET    /habits/{id}/history       # Historical data for habit
```

### Advanced Features
```http
POST   /habits/{id}/items         # Add checklist items
GET    /habits/{id}/items         # Get checklist items
POST   /habits/{id}/link          # Link to notes/documents
GET    /workers/status            # Background worker status
```

## Frontend Components

### HabitToday Component
**Daily habit tracking interface**

Features:
- Real-time progress display
- Quick logging buttons
- Edit habit functionality
- Progress visualization
- Streak indicators

Usage:
```tsx
<HabitToday />
```

### HabitCreate Component
**4-step habit creation wizard**

Steps:
1. **Type Selection**: Choose habit type with examples
2. **Details**: Title, target, unit configuration
3. **Schedule**: RRULE configuration with presets
4. **Advanced**: Grace days, retro hours, notes

### HabitInsights Component
**Analytics dashboard**

Sections:
- **Overview Cards**: Total habits, completion rate, streaks
- **Performance Chart**: Per-habit completion rates
- **Patterns**: Best days, times, consistency analysis
- **Weekly Comparison**: This week vs last week trends

### HabitProgress Component
**Progress visualization**

Components:
- `HabitProgressRing`: Circular progress indicator
- `ProgressBar`: Linear progress display
- `WeeklyGrid`: 7-day completion grid

## Background Workers

### Scheduler Worker
**Runs daily at 23:30**
- Generates habit instances for next day based on RRULE
- Cleans up old instances (90+ days)
- Handles timezone considerations

### Streak Worker  
**Runs daily at 23:55**
- Calculates current streaks for all habits
- Updates best streak records
- Handles grace days and vacation periods
- Sends streak milestone notifications

### NTFY Worker
**Runs throughout day**
- Morning nudges (8:00 AM): Remind about pending habits
- Evening reviews (8:00 PM): Summary of day's progress  
- Milestone alerts: Streak achievements, goal completions

### Neo4j Worker
**Continuous sync**
- Syncs habit data to knowledge graph
- Creates relationships between habits and notes/documents
- Enables semantic search and connections

## Development Setup

### Prerequisites
```bash
# Backend dependencies
pip install fastapi uvicorn sqlalchemy psycopg2 python-dateutil

# Frontend dependencies  
npm install react typescript tailwindcss lucide-react
```

### Environment Variables
```bash
# Database
DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"

# Neo4j (optional)
NEO4J_URI="bolt://10.185.1.180:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="sara-graph-secret"

# Notifications (optional)
NTFY_BASE_URL="http://10.185.1.8:8889"
NTFY_HABIT_TOPIC="habits"
```

### Database Setup
```bash
# Run migrations
cd backend
alembic upgrade head

# Setup Neo4j constraints (optional)
python setup_habit_neo4j_constraints.py
```

### Running the System
```bash
# Backend
cd backend
python app/main_simple.py

# Frontend  
cd frontend
npm run dev
```

### Testing
```bash
# Test habit creation and logging
python test_habit_system.py

# Test frontend integration
python frontend_habit_test.py

# Test insights API
python test_insights_api.py
```

## Progress Calculation Algorithms

### Binary Habits
```python
progress = 1.0 if any_log_exists else 0.0
```

### Quantitative Habits
```python
total_logged = sum(log.amount for log in logs)
progress = min(total_logged / target, 1.0)
```

### Checklist Habits
```python
# Percentage mode
completed_items = count_completed_items()
progress = completed_items / total_items

# All-items mode  
progress = 1.0 if all_items_completed else 0.0
```

### Time-based Habits
```python
total_minutes = sum(log.duration for log in logs)
progress = min(total_minutes / target_minutes, 1.0)
```

## Streak Calculation Logic

```python
def calculate_streak(habit, today):
    streak = 0
    current_date = today
    
    while current_date >= habit.start_date:
        instance = get_instance(habit, current_date)
        
        if instance and instance.status == "complete":
            streak += 1
        elif instance and instance.expected:
            # Expected but not completed - streak broken
            break
        # If no instance expected, continue (non-scheduled day)
        
        current_date -= timedelta(days=1)
    
    return streak
```

## Integration Features

### Notes Integration
- Link habits to specific notes for context
- Automatic backlink creation in knowledge graph
- Search habits by related note content

### Timer Integration  
- Start timers directly from time-based habits
- Automatic logging when timer completes
- Integration with existing timer system

### NTFY Notifications
- Configurable notification preferences
- Habit-specific reminder times
- Streak milestone celebrations
- Weekly/monthly progress summaries

## Future Enhancements

### Planned Features
- **AI Coaching**: Personalized habit suggestions and tips
- **Social Features**: Share streaks and compete with friends
- **Advanced Analytics**: Correlation analysis, habit stacking insights
- **Mobile App**: React Native companion app
- **Habit Templates**: Pre-built habit configurations for common goals

### Technical Improvements
- **Caching**: Redis for improved performance
- **Real-time Updates**: WebSocket connections for live progress
- **Offline Support**: Service worker for offline habit logging
- **Data Export**: CSV/JSON export of habit data
- **API Rate Limiting**: Protect against abuse

---

## Conclusion

The Sara AI Hub habit tracking system provides a comprehensive, flexible, and user-friendly way to build and maintain habits. With support for multiple habit types, sophisticated scheduling, detailed analytics, and seamless integration with the broader Sara ecosystem, it's designed to help users achieve their goals through consistent, trackable progress.

The system is built with modern web technologies, follows best practices for scalability and maintainability, and provides extensive customization options to fit diverse user needs and preferences.