# Sara - AI Personal Intelligence Hub

A sophisticated personal AI assistant with human-like memory, intelligent knowledge graphs, habit tracking, cross-device integration, voice interaction, and comprehensive life management capabilities.

## Overview

Sara is a comprehensive AI-powered personal hub that combines conversational AI, advanced episodic memory with user feedback, knowledge management, habit tracking, multi-device orchestration, and life automation into a unified platform. Unlike traditional chatbots, Sara maintains sophisticated memory of your interactions with rating-based prioritization, builds dynamic connections between your content, provides contextual assistance across all your devices, and helps you build better habits.

## Core Features

### Advanced Conversational AI
- **Natural Language Processing**: Sophisticated LLM integration with tool-calling capabilities
- **Selective RAG**: Intelligently retrieves context only when needed for optimal performance
- **Work Mode**: Lean, task-focused context when working in canvas or triggered by voice
- **Daily Brief Integration**: Contextual awareness of your schedule, tasks, and priorities
- **Body State Awareness**: Physiological context from wearables (sleep, energy, stress)
- **Multi-Modal Understanding**: Process text, documents, and visual content
- **Tool Integration**: Access to 20+ integrated tools for comprehensive assistance

### Rating-Aware Episodic Memory System
- **User Feedback Integration**: 5-star rating system for memory importance and quality
- **Wilson Score Confidence**: Advanced statistical scoring prevents manipulation by single ratings
- **Temporal Decay with Rating Boost**: High-rated memories persist longer in retrieval
- **Thompson Sampling**: Addresses cold-start problem with probabilistic exploration for new memories
- **Composite Retrieval Scoring**:
  - 40% Semantic similarity
  - 20% Recency (exponential decay)
  - 20% AI-scored importance
  - 15% User rating boost (Wilson Score + decay)
  - 5% Exploration bonus (Thompson Sampling)
- **Emotional Intelligence**: Real-time sentiment analysis and emotional context tracking
- **Dynamic Context Windows**: Smart memory retrieval based on query type and temporal patterns
- **Dream Processing**: Background analysis for pattern detection and insight generation
- **Multi-Source Integration**: Unified memory across chat, notes, documents, timers, habits, and calendar

### Advanced Knowledge Garden
- **Obsidian-Style Interface**: Three-panel layout with sidebar, editor, and context panel
- **Bidirectional Linking**: Auto-detects `[[Note Title]]` syntax and creates dynamic connections
- **Interactive Graph View**: D3.js-powered visualization of notes, connections, and knowledge clusters
- **Timeline View**: Chronological exploration of notes, memories, and insights
- **Multiple Connection Types**:
  - **Reference**: Explicit `[[links]]`
  - **Semantic**: AI-detected content similarity
  - **Temporal**: Time-based relationships
- **Auto-Connection Detection**: AI automatically discovers and suggests related content
- **Connection Strength Scoring**: Dynamic relationship weighting based on usage and relevance
- **Hierarchical Organization**: Nested folder structures with parent-child relationships

### Cross-Device Integration
- **Desktop Companion App**: Floating assistant for Windows/macOS with system tray integration
- **Voice Bridge**: Wake word detection ("Hey Sara") with Jetson-based voice processing
- **Activity Monitoring**: Keyboard, mouse, and active window tracking for context
- **Screenshot Capture**: On-demand and scheduled screenshots with AI analysis
- **System Metrics**: CPU, RAM, GPU monitoring across devices
- **Remote Commands**: Control devices, open URLs, show notifications from any interface
- **iOS Integration**: Mobile app with push notifications and voice input

### Canvas Workspace
- **Visual Workspace**: Interactive canvas for brainstorming and visual thinking
- **Map Visualizations**: Knowledge graphs, memory flowcharts, and architecture diagrams
- **Real-time Collaboration**: Live updates across devices
- **Work Mode**: Automatic lean context when working in canvas
- **Map Tools**: Create, expand, and explore visual representations of your knowledge

### Daily Brief System
- **Morning Briefings**: AI-generated summary of your day, priorities, and context
- **Moment Layer**: Real-time tracking of conversation context and emotional state
- **Schedule Integration**: Calendar events, reminders, and time-sensitive information
- **Adaptive Context**: Brief injection based on conversation relevance

### Comprehensive Habit Tracking System
- **4 Habit Types**: Binary (yes/no), Quantitative (measurable), Checklist (multiple items), Time-based (duration)
- **RRULE Scheduling**: RFC 5545 standard for complex recurrence patterns (daily, weekly, custom)
- **Intelligent Progress Tracking**: Type-specific progress calculations with visual indicators
- **Streak Management**: Current and best streak tracking with grace days and vacation support
- **Time Windows**: Schedule habits for specific times (morning, afternoon, evening, custom)
- **Analytics Dashboard**: Comprehensive insights, trends, and performance metrics
- **NTFY Integration**: Smart notifications for habit reminders and streak milestones
- **Neo4j Integration**: Connect habits to notes, goals, and personal insights

### Dual-Database Knowledge Graph
- **Neo4j Primary**: High-performance graph database for complex relationship traversal
- **PostgreSQL Backup**: Relational database ensuring data consistency and backup
- **Intelligent Processing Pipeline**: Background workers analyze content for semantic connections
- **Entity Extraction**: Automatically identifies people, organizations, topics, and concepts
- **Semantic Clustering**: Groups related content using AI similarity analysis
- **Connection Suggestions**: AI-powered recommendations for linking related content
- **Graph Analytics**: Centrality analysis, community detection, and relationship scoring

### Advanced Document Processing
- **Multi-Format Support**: PDF, DOCX, PPTX, TXT, MD, CSV with intelligent text extraction
- **Semantic Analysis**: AI processes content for meaning, topics, and key insights
- **Vector Search**: Find documents by conceptual similarity, not just keyword matching
- **Automatic Tagging**: AI categorizes and tags uploaded content with relevant metadata
- **Citation Integration**: Automatic citation generation with document references
- **MinIO Storage**: Scalable S3-compatible object storage for enterprise-grade file management

### Smart Productivity Tools
- **Live Countdown Timers**: Real-time updates without page refresh, persistent across sessions
- **AI-Enhanced Reminders**: Context-aware reminder creation with intelligent scheduling
- **Pomodoro Integration**: Built-in focus session tracking with break management
- **Cross-Session Persistence**: Timers continue running across browser sessions and devices
- **Context-Aware Notifications**: AI generates personalized alerts based on your recent activities
- **Integration Ecosystem**: Connect timers to habits, notes, and productivity workflows

### Intelligent Notification System
- **Contextual AI Generation**: Personalized notifications referencing your recent conversations
- **Multi-Channel Delivery**: NTFY integration for mobile push notifications
- **Smart Consolidation**: Intelligent routing with duplicate detection
- **Adaptive Messaging**: Different notification styles for timers, reminders, habits, and alerts
- **Fallback System**: Graceful degradation ensures notifications always reach you
- **Priority Management**: Urgent alerts, normal habits, low-priority general notifications

### Integrated Calendar System
- **Event Management**: Create, edit, and manage calendar events with natural language input
- **Time-Based Connections**: Automatic linking of events to related notes, habits, and memories
- **Contextual Reminders**: AI-enhanced event notifications with relevant background context
- **Habit Integration**: Connect recurring habits to calendar events for comprehensive life tracking
- **Memory Integration**: Calendar events become part of Sara's episodic memory system

### Advanced Search & Discovery
- **Hybrid Search Architecture**: Combines full-text, semantic vector, and graph-based search
- **Multi-Content Search**: Unified search across notes, documents, memories, habits, and events
- **Relationship Discovery**: Find content through network connections and semantic relationships
- **Timeline Search**: Explore content chronologically with temporal filtering
- **Smart Filters**: Advanced filtering by content type, importance scores, rating, emotional tone, and date ranges
- **Context-Aware Results**: Search results include relationship context and connection strength

## Technical Architecture

### Frontend Stack
- **React 18**: Modern UI framework with hooks, context, and concurrent features
- **TypeScript**: Full type safety with strict mode and comprehensive type definitions
- **Vite**: Lightning-fast build tool with hot module replacement and optimized bundling
- **Tailwind CSS**: Utility-first styling with dark theme support and custom design system
- **D3.js**: Interactive graph visualizations with physics simulations and custom layouts
- **TanStack Query**: Intelligent server state management with caching and synchronization
- **Lucide React**: Comprehensive icon library with consistent styling

### Backend Stack
- **FastAPI**: Modern Python web framework with automatic API documentation and validation
- **SQLAlchemy**: Advanced ORM with PostgreSQL and Neo4j integration
- **Pydantic**: Data validation and serialization with automatic schema generation
- **Neo4j**: High-performance graph database for knowledge relationships and traversal
- **PostgreSQL 16**: Primary relational database with advanced JSON and vector support
- **pgvector**: Vector similarity search extension for semantic embeddings
- **Redis**: High-performance caching, real-time rating storage, and work mode state
- **httpx**: High-performance async HTTP client for LLM and service integration

### Desktop App Stack (Electron)
- **Electron**: Cross-platform desktop app with system tray integration
- **Python Sidecar**: Background service for activity monitoring and device commands
- **Voice Bridge**: WebSocket client connecting to Jetson voice agent
- **sounddevice**: Audio playback for TTS responses

### Voice Processing (Jetson)
- **OpenWakeWord**: Custom wake word detection ("Hey Sara")
- **Whisper STT**: Speech-to-text transcription
- **Kokoro TTS**: Text-to-speech synthesis
- **WebSocket Server**: Streams audio to connected desktop clients

### Storage & Infrastructure
- **MinIO**: Enterprise-grade S3-compatible object storage with bucket policies
- **Docker Compose**: Multi-container orchestration with service dependencies
- **nginx**: High-performance reverse proxy with SSL termination and load balancing
- **JWT Authentication**: Secure token-based authentication with refresh token support
- **CORS**: Comprehensive cross-origin resource sharing with secure defaults

### AI & Machine Learning Stack
- **OpenAI-Compatible API**: Flexible LLM provider support with fallback strategies
- **Large Language Models**: Primary and fast models for different processing needs
- **BGE-M3 Embeddings**: Multilingual embedding model (1024 dimensions) for semantic similarity
- **Custom Intelligence Pipeline**: Multi-stage background processing for content analysis
- **Emotional Analysis Engine**: Real-time sentiment and emotional state detection
- **Pattern Recognition**: Advanced algorithms for habit patterns and behavior analysis
- **Wilson Score Algorithm**: Statistical confidence intervals for rating-based ranking
- **Thompson Sampling**: Bayesian exploration strategy for cold-start problem

## Tool Ecosystem

Sara integrates 20+ specialized tools for comprehensive assistance:

### Core Tools
1. **search_memory** - Advanced episodic memory search with rating-aware ranking
2. **rate_memory** - Submit 1-5 star ratings for memory quality and importance
3. **search_notes** - Full-text and semantic note search with relationship discovery
4. **create_note** - Rich note creation with auto-linking and metadata extraction
5. **edit_note** - Update existing notes with change tracking
6. **search_documents** - Multi-format document search with citation support

### Productivity Tools
7. **start_timer** - Smart timer creation with context-aware notifications
8. **check_timer** - Check status of running timers
9. **cancel_timer** - Stop active timers
10. **create_reminder** - Intelligent reminder scheduling with natural language
11. **list_reminders** - Active reminder management with priority sorting
12. **cancel_reminder** - Remove pending reminders
13. **list_calendar_events** - Calendar integration with event context
14. **create_calendar_event** - Event creation with automatic note linking

### Habit & Wellness Tools
15. **create_habit** - Comprehensive habit creation with RRULE scheduling
16. **log_habit_progress** - Progress tracking with streak management
17. **get_habit_insights** - Analytics and performance optimization suggestions

### Workspace & Device Tools
18. **workspace_control** - Canvas manipulation (create windows, arrange layout)
19. **map_create** - Generate knowledge graph visualizations
20. **map_explode** - Expand map nodes into detailed sub-graphs
21. **send_device_command** - Cross-device control (screenshots, URLs, notifications)

### System Tools
22. **get_system_status** - Health monitoring and performance metrics
23. **analyze_patterns** - Cross-system pattern recognition and insights

## Desktop Companion App

The Sara Desktop Companion provides always-available AI assistance:

### Features
- **System Tray**: Floating smoke ring interface, click to chat
- **Voice Integration**: Wake word detection via Jetson bridge
- **Activity Tracking**: Window focus, keyboard/mouse activity for context
- **Screenshot Capture**: On-demand or scheduled with AI analysis
- **System Metrics**: CPU, RAM, GPU monitoring
- **Timer Displays**: Floating timer windows
- **Notifications**: System notifications from Sara

### Installation
1. Download from webapp Settings page
2. Extract and run `Sara.exe`
3. Configure API URL and authenticate
4. Optional: Install Python dependencies for sidecar features

### Voice Setup (Requires Jetson)
1. Run `sara_voice_agent.py` on Jetson with wake word model
2. Desktop app auto-connects to voice bridge
3. Say "Hey Sara" followed by your command
4. Audio response plays through desktop speakers

## Installation & Setup

### Quick Start (Docker)
```bash
# 1. Clone repository
git clone <repository-url>
cd sara-hub

# 2. Environment setup
cp .env.example .env
# Edit .env with your configuration

# 3. Start all services
docker-compose up -d

# 4. Access Sara
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000/docs
```

### Development Mode
```bash
# Start data services
docker compose up -d db neo4j minio redis

# Backend (use Docker)
docker compose -f docker-compose.dev.yml up -d backend

# Frontend
cd frontend
npm install
npm run dev
```

### Essential Environment Configuration
```env
# AI Configuration
OPENAI_BASE_URL=<your-llm-endpoint>
OPENAI_MODEL=<your-primary-model>
OPENAI_NOTIFICATION_MODEL=<your-fast-model>
OPENAI_API_KEY=<your-api-key>

# Embeddings & Vector Search
EMBEDDING_BASE_URL=<your-embedding-endpoint>
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Database Configuration
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/sara_hub
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-password>
REDIS_URL=redis://localhost:6379/0

# Notifications
NTFY_SERVER_URL=<your-ntfy-server>
NTFY_ENABLED=true

# Sara Configuration
ASSISTANT_NAME=Sara
DOMAIN=<your-domain>

# Security
JWT_SECRET=<your-secure-secret-key>
COOKIE_DOMAIN=<your-domain>
```

## API Reference

### Authentication
```
POST   /auth/login                    # User authentication with JWT
POST   /auth/register                 # New user registration
POST   /auth/logout                   # Session termination
GET    /auth/me                       # Current user information
```

### Chat & Memory
```
POST   /chat/stream                   # Streaming chat with Sara
POST   /memory/search                 # Search episodic memory
GET    /memory/episodes               # List memory episodes
POST   /api/episodes/{id}/rate        # Rate episode (1-5 stars)
```

### Notes & Knowledge
```
GET    /notes                         # List notes with folders
POST   /notes                         # Create note with auto-linking
GET    /notes/{id}                    # Get note with connections
PUT    /notes/{id}                    # Update note
GET    /notes/graph-data              # Graph visualization data
```

### Habits
```
POST   /habits                        # Create habit
GET    /habits                        # List habits
GET    /habits/today                  # Today's habit instances
POST   /habits/{id}/log               # Log progress
GET    /insights/habits               # Habit analytics
```

### Productivity
```
POST   /timers                        # Create timer
GET    /timers                        # List active timers
POST   /reminders                     # Create reminder
GET    /reminders                     # List reminders
GET    /events                        # List calendar events
POST   /events                        # Create event
```

### Documents
```
POST   /documents                     # Upload with AI processing
GET    /documents                     # List documents
POST   /documents/search              # Semantic search
```

### Devices
```
GET    /api/devices                   # List connected devices
POST   /api/devices/{id}/command      # Send command to device
GET    /api/downloads                 # List desktop app downloads
GET    /api/downloads/{filename}      # Download desktop app
```

### Daily Brief
```
GET    /api/daily-brief/compiled      # Get today's brief
POST   /api/daily-brief/generate      # Force regenerate brief
```

## System Requirements

### Minimum
- **RAM**: 4GB (8GB recommended)
- **CPU**: 2 cores @ 2.0GHz
- **Storage**: 10GB
- **Network**: Stable internet for LLM API calls

### Production
- **RAM**: 16GB+
- **CPU**: 8 cores @ 3.0GHz+
- **Storage**: 100GB+ SSD
- **GPU**: Optional for local voice processing (Jetson Nano/Orin)

## License

MIT License - See LICENSE file for details

---

**Sara AI Personal Hub** - Your intelligent companion for life, work, and productivity. Built for deep, contextual, and continuously evolving AI interaction with human-guided memory prioritization.
