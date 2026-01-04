# Sara Learning System

A Socratic tutoring system integrated into Sara for structured, topic-based learning with research capabilities.

## Overview

The Learning System provides:
- **Topic-based organization** - Hierarchical topics with mastery tracking
- **Source management** - Collect and organize learning materials (URLs, PDFs, notes)
- **Scratchpad notes** - Per-topic working notes and summaries
- **Socratic chat** - AI-guided learning conversations with probing questions
- **Visual canvas** - React Flow-based concept mapping and diagrams
- **Research tools** - Quick feasibility checks and deep research jobs

---

## Sprint 1: Core Infrastructure (COMPLETED)

### Database Layer
- **Migration**: `backend/alembic/versions/016_add_learning_system_tables.py`
- **Tables created**:
  - `learning_topic` - Topics with hierarchy, mastery level, priority, status
  - `topic_source` - Learning sources (web, pdf, document, note, video)
  - `source_chunk` - Chunked/embedded source content for RAG
  - `learning_session` - Study session tracking
  - `learning_progress` - Spaced repetition progress per concept
  - `topic_scratchpad` - Per-topic working notes
  - `research_report` - Generated research reports
  - `research_job` - Async research job tracking
  - `learning_artifact` - Visual artifacts (concept maps, flowcharts)

### Backend Models
- **File**: `backend/app/models/learning.py`
- SQLAlchemy models for all learning tables with relationships and helper methods

### Backend Routes
- **File**: `backend/app/routes/learning.py`
- **Prefix**: `/api/learn`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/topics` | GET | List topics (filter by status, parent) |
| `/topics` | POST | Create new topic |
| `/topics/{id}` | GET | Get topic details |
| `/topics/{id}` | PUT | Update topic |
| `/topics/{id}` | DELETE | Delete topic |
| `/topics/{id}/children` | GET | Get child topics |
| `/topics/{id}/sources` | GET | List topic sources |
| `/sources` | POST | Add source to topic |
| `/sources/{id}/fetch` | POST | Fetch/process source content |
| `/sources/{id}` | DELETE | Delete source |
| `/topics/{id}/scratchpad` | GET | Get topic scratchpad |
| `/topics/{id}/scratchpad` | PUT | Update scratchpad |
| `/artifacts` | GET | List artifacts |
| `/artifacts` | POST | Create artifact |
| `/artifacts/{id}` | GET/PUT/DELETE | Artifact CRUD |
| `/chat/stream` | POST | Streaming Socratic chat |
| `/research/quick` | POST | Quick feasibility check |
| `/research/deep` | POST | Start deep research job |
| `/research/{job_id}` | GET | Get research job status |
| `/review-queue` | GET | Get spaced repetition items due |
| `/sessions/start` | POST | Start learning session |
| `/sessions/{id}/end` | POST | End learning session |

### AI Tools
- **File**: `backend/app/tools/learning.py`
- **Category**: `learning` in tool registry

| Tool | Description |
|------|-------------|
| `learning_topic_create` | Create new learning topic |
| `learning_topic_list` | List topics with filters |
| `learning_topic_update` | Update topic properties |
| `learning_source_add` | Add source to topic |
| `learning_source_list` | List sources for topic |
| `learning_scratchpad_read` | Read topic scratchpad |
| `learning_scratchpad_update` | Update/append to scratchpad |

### System Prompt
- **File**: `backend/app/prompts/learning_system_prompt.py`
- Socratic teaching approach with probing questions
- Context-aware based on topic and scratchpad content

### Frontend Components
- **Main Section**: `frontend/src/components/learning/LearningSection.tsx`
  - Three-panel layout: sidebar, chat, canvas
  - Topic selection and navigation

- **Chat Interface**: `frontend/src/components/learning/LearningChat.tsx`
  - SSE streaming for real-time responses
  - Markdown rendering with syntax highlighting
  - Message history per topic

- **Topic Sidebar**: `frontend/src/components/learning/TopicSidebar.tsx`
  - Topic list with create/delete
  - Mastery level indicators
  - Source count badges

- **Visual Canvas**: `frontend/src/components/learning/TopicCanvas.tsx`
  - React Flow integration
  - Concept mapping nodes
  - Drag-and-drop interface

- **Scratchpad**: `frontend/src/components/learning/Scratchpad.tsx`
  - Per-topic working notes
  - Auto-save functionality

### App Integration
- Added "Learn" navigation item in `App-interactive.tsx`
- Learning view accessible from main app sidebar

---

## Sprint 2: Enhanced Features (COMPLETED)

### Source Processing Pipeline
- [x] Implement `LearningSourceService` for fetching URLs
- [ ] PDF text extraction with PyPDF2/pdfplumber (web URLs only for now)
- [x] Content chunking with overlap (500 chars, 50 char overlap)
- [x] Embedding generation for source chunks (using BGE-M3)
- [x] Store chunks in `source_chunk` table

### RAG Integration
- [x] Query source chunks during chat (vector similarity search)
- [x] Inject relevant context into Socratic prompts
- [ ] Citation tracking in responses (partial - source names shown)

### Research System
- [x] Implement quick research with web search (Tavily/SearXNG)
- [ ] Deep research with multi-step planning (queued, not implemented)
- [x] Source discovery and ranking (via search reranking)
- [x] Report generation with LLM summary

### Spaced Repetition
- [ ] Extract key concepts from conversations
- [ ] SM-2 algorithm implementation
- [ ] Review queue UI component
- [ ] Progress tracking and analytics

---

## Sprint 3: Advanced Features (TODO)

### Knowledge Synthesis
- [ ] Cross-topic connections
- [ ] Concept relationship mapping
- [ ] Knowledge gap detection
- [ ] Learning path suggestions

### Artifact Generation
- [ ] AI-generated concept maps
- [ ] Flowchart creation from explanations
- [ ] Mind map generation
- [ ] Export to image/PDF

### Progress Analytics
- [ ] Study time tracking
- [ ] Mastery progression charts
- [ ] Topic coverage heatmap
- [ ] Learning streak tracking

### Collaborative Features
- [ ] Share topics with others
- [ ] Import/export topic packages
- [ ] Community source recommendations

---

## File Structure

```
backend/
├── alembic/versions/
│   └── 016_add_learning_system_tables.py
├── app/
│   ├── models/
│   │   └── learning.py
│   ├── routes/
│   │   └── learning.py
│   ├── services/
│   │   └── learning_source_service.py  # Sprint 2: URL fetching, chunking, RAG
│   ├── prompts/
│   │   └── learning_system_prompt.py
│   └── tools/
│       └── learning.py

frontend/
└── src/
    └── components/
        └── learning/
            ├── LearningSection.tsx
            ├── LearningChat.tsx
            ├── TopicSidebar.tsx
            ├── TopicCanvas.tsx
            └── Scratchpad.tsx
```

---

## Usage

### Creating a Topic
```bash
curl -X POST http://localhost:8000/api/learn/topics \
  -H "Content-Type: application/json" \
  -d '{"title": "Machine Learning", "description": "ML fundamentals", "priority": 8}'
```

### Adding a Source
```bash
curl -X POST http://localhost:8000/api/learn/sources \
  -H "Content-Type: application/json" \
  -d '{"topic_id": "uuid", "source_type": "web", "url": "https://example.com/ml-guide", "title": "ML Guide"}'
```

### Starting a Learning Chat
The frontend connects to `/api/learn/chat/stream` with SSE for real-time Socratic tutoring responses.

---

## Configuration

No additional environment variables required. Uses existing:
- `DATABASE_URL` - PostgreSQL connection
- `OPENAI_*` - LLM configuration for chat
- `EMBEDDING_*` - Embedding model for future RAG

---

## Dependencies Added

### Backend
- No new dependencies (uses existing SQLAlchemy, FastAPI)

### Frontend
- `reactflow` - Visual canvas component
- `@reactflow/core`, `@reactflow/controls`, `@reactflow/background`
