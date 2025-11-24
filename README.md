# Sara - AI Personal Intelligence Hub

A sophisticated personal AI assistant with human-like memory, intelligent knowledge graphs, habit tracking, vulnerability monitoring, rating-aware memory retrieval, and comprehensive life management capabilities.

## 🎯 Overview

Sara is a comprehensive AI-powered personal hub that combines conversational AI, advanced episodic memory with user feedback, knowledge management, habit tracking, cybersecurity monitoring, and life automation into a unified platform. Unlike traditional chatbots, Sara maintains sophisticated memory of your interactions with rating-based prioritization, builds dynamic connections between your content, provides contextual assistance, and helps you build better habits while staying secure.

## ✨ Core Features

### 🤖 **Advanced Conversational AI**
- **Natural Language Processing**: Sophisticated LLM integration with tool-calling capabilities
- **Selective RAG**: Intelligently retrieves context only when needed for optimal performance
- **Contextual Responses**: AI considers your personality, preferences, and conversation history
- **Multi-Modal Understanding**: Process text, documents, and visual content
- **Tool Integration**: Access to 15+ integrated tools for comprehensive assistance

### 🧠 **Rating-Aware Episodic Memory System**
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
- **Redis-PostgreSQL-Neo4j Sync**: Real-time rating storage with nightly consolidation
- **Rating Analytics**: Track which memories you value most, identify knowledge gaps
- **Emotional Intelligence**: Real-time sentiment analysis and emotional context tracking
- **Dynamic Context Windows**: Smart memory retrieval based on query type and temporal patterns
- **Dream Processing**: Background analysis for pattern detection and insight generation
- **Multi-Source Integration**: Unified memory across chat, notes, documents, timers, habits, and calendar
- **Access Analytics**: Track memory usage patterns and optimize retrieval performance

### 📚 **Advanced Knowledge Garden**
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

### ⭐ **Rating System Features**
- **Episode Rating**: Rate any message with 1-5 stars for memory prioritization
- **Optimistic UI**: Instant feedback with error rollback on failure
- **Real-Time Sync**: Immediate rating storage in Redis with WebSocket event broadcasting
- **Nightly Consolidation**:
  - Runs daily at 2:30 AM after memory compaction
  - Calculates Wilson Score confidence intervals
  - Applies temporal decay (30-day half-life)
  - Generates Thompson Sampling exploration bonuses
  - Syncs Redis → PostgreSQL → Neo4j
- **Rating Boost Formula**: `rating_boost = wilson_score * age_decay * 0.25`
- **Exploration Bonus**: Beta distribution sampling for first 7 days of new memories
- **Rating Fatigue Prevention**: Smart filtering of low-value messages (greetings, short responses)
- **Rating Analytics**: View rating distribution, most-valued memories, and quality trends
- **Clear Rating**: Easy removal of ratings with clean UI feedback

### 🎯 **Comprehensive Habit Tracking System**
- **4 Habit Types**: Binary (yes/no), Quantitative (measurable), Checklist (multiple items), Time-based (duration)
- **RRULE Scheduling**: RFC 5545 standard for complex recurrence patterns (daily, weekly, custom)
- **Intelligent Progress Tracking**: Type-specific progress calculations with visual indicators
- **Streak Management**: Current and best streak tracking with grace days and vacation support
- **Time Windows**: Schedule habits for specific times (morning, afternoon, evening, custom)
- **Analytics Dashboard**: Comprehensive insights, trends, and performance metrics
- **NTFY Integration**: Smart notifications for habit reminders and streak milestones
- **Neo4j Integration**: Connect habits to notes, goals, and personal insights

### 🛡️ **Vulnerability Intelligence & Monitoring**
- **Daily Vulnerability Reports**: Automated generation of comprehensive security intelligence
- **Multi-Source Intelligence**: MSRC, CISA KEV, NVD, Project Zero, Exploit-DB integration
- **Priority Scoring**: Known exploited vulnerabilities and critical threats highlighted
- **Knowledge Graph Integration**: Vulnerability reports processed into Sara's memory system
- **Mobile Notifications**: Critical vulnerability alerts via NTFY
- **Clean Mobile UI**: Responsive interface with sidebar navigation and markdown rendering
- **Historical Tracking**: Archive of daily reports for trend analysis and research

### 🔗 **Dual-Database Knowledge Graph**
- **Neo4j Primary**: High-performance graph database for complex relationship traversal
- **PostgreSQL Backup**: Relational database ensuring data consistency and backup
- **Intelligent Processing Pipeline**: Background workers analyze content for semantic connections
- **Entity Extraction**: Automatically identifies people, organizations, topics, and concepts
- **Semantic Clustering**: Groups related content using AI similarity analysis
- **Connection Suggestions**: AI-powered recommendations for linking related content
- **Graph Analytics**: Centrality analysis, community detection, and relationship scoring

### 📄 **Advanced Document Processing**
- **Multi-Format Support**: PDF, DOCX, PPTX, TXT, MD, CSV with intelligent text extraction
- **Semantic Analysis**: AI processes content for meaning, topics, and key insights
- **Vector Search**: Find documents by conceptual similarity, not just keyword matching
- **Automatic Tagging**: AI categorizes and tags uploaded content with relevant metadata
- **Citation Integration**: Automatic citation generation with document references
- **MinIO Storage**: Scalable S3-compatible object storage for enterprise-grade file management

### ⏰ **Smart Productivity Tools**
- **Live Countdown Timers**: Real-time updates without page refresh, persistent across sessions
- **AI-Enhanced Reminders**: Context-aware reminder creation with intelligent scheduling
- **Pomodoro Integration**: Built-in focus session tracking with break management
- **Cross-Session Persistence**: Timers continue running across browser sessions and devices
- **Context-Aware Notifications**: AI generates personalized alerts based on your recent activities
- **Integration Ecosystem**: Connect timers to habits, notes, and productivity workflows

### 📱 **Intelligent Notification System**
- **Contextual AI Generation**: Personalized notifications referencing your recent conversations
- **Multi-Channel Delivery**: NTFY integration for mobile push notifications
- **Smart Consolidation**: Intelligent routing with duplicate detection
- **Adaptive Messaging**: Different notification styles for timers, reminders, habits, and security alerts
- **Fallback System**: Graceful degradation ensures notifications always reach you
- **Priority Management**: Critical security alerts, normal habits, low-priority general notifications

### 📅 **Integrated Calendar System**
- **Event Management**: Create, edit, and manage calendar events with natural language input
- **Time-Based Connections**: Automatic linking of events to related notes, habits, and memories
- **Contextual Reminders**: AI-enhanced event notifications with relevant background context
- **Habit Integration**: Connect recurring habits to calendar events for comprehensive life tracking
- **Memory Integration**: Calendar events become part of Sara's episodic memory system

### 🔍 **Advanced Search & Discovery**
- **Hybrid Search Architecture**: Combines full-text, semantic vector, and graph-based search
- **Multi-Content Search**: Unified search across notes, documents, memories, habits, events, and vulnerabilities
- **Relationship Discovery**: Find content through network connections and semantic relationships
- **Timeline Search**: Explore content chronologically with temporal filtering
- **Smart Filters**: Advanced filtering by content type, importance scores, rating, emotional tone, and date ranges
- **Context-Aware Results**: Search results include relationship context and connection strength

## 🏗 Technical Architecture

### **Frontend Stack**
- **React 18**: Modern UI framework with hooks, context, and concurrent features
- **TypeScript**: Full type safety with strict mode and comprehensive type definitions
- **Vite**: Lightning-fast build tool with hot module replacement and optimized bundling
- **Tailwind CSS**: Utility-first styling with dark theme support and custom design system
- **D3.js**: Interactive graph visualizations with physics simulations and custom layouts
- **TanStack Query**: Intelligent server state management with caching and synchronization
- **Lucide React**: Comprehensive icon library with consistent styling
- **Date-fns**: Robust date manipulation and formatting utilities

### **Backend Stack**
- **FastAPI**: Modern Python web framework with automatic API documentation and validation
- **SQLAlchemy**: Advanced ORM with PostgreSQL and Neo4j integration
- **Pydantic**: Data validation and serialization with automatic schema generation
- **Neo4j**: High-performance graph database for knowledge relationships and traversal
- **PostgreSQL 16**: Primary relational database with advanced JSON and vector support
- **pgvector**: Vector similarity search extension for semantic embeddings
- **Redis**: High-performance caching and real-time rating storage with Pub/Sub events
- **httpx**: High-performance async HTTP client for LLM and service integration
- **Alembic**: Database migration management with version control

### **Storage & Infrastructure**
- **MinIO**: Enterprise-grade S3-compatible object storage with bucket policies
- **Docker Compose**: Multi-container orchestration with service dependencies
- **nginx**: High-performance reverse proxy with SSL termination and load balancing
- **JWT Authentication**: Secure token-based authentication with refresh token support
- **CORS**: Comprehensive cross-origin resource sharing with secure defaults

### **AI & Machine Learning Stack**
- **OpenAI-Compatible API**: Flexible LLM provider support with fallback strategies
- **Large Language Models**: Primary and fast models for different processing needs
- **BGE-M3 Embeddings**: Multilingual embedding model (1024 dimensions) for semantic similarity
- **Custom Intelligence Pipeline**: Multi-stage background processing for content analysis
- **Emotional Analysis Engine**: Real-time sentiment and emotional state detection
- **Pattern Recognition**: Advanced algorithms for habit patterns and behavior analysis
- **Wilson Score Algorithm**: Statistical confidence intervals for rating-based ranking
- **Thompson Sampling**: Bayesian exploration strategy for cold-start problem

### **Security & Monitoring**
- **Vulnerability Intelligence Pipeline**: Multi-source threat intelligence aggregation
- **NTFY Self-Hosted**: Private notification server with encryption and authentication
- **JWT Security**: Secure token management with rotation and validation
- **Input Validation**: Comprehensive sanitization and validation for all user inputs
- **Rate Limiting**: API protection against abuse and excessive usage
- **Audit Logging**: Comprehensive activity logging for security and debugging

## 🚀 Complete Feature Overview

### **Life Management Capabilities**
- **📝 Note Taking**: Rich text editing with bidirectional linking and auto-suggestions
- **⭐ Memory Rating**: 5-star rating system with statistical ranking and temporal decay
- **📊 Habit Tracking**: Comprehensive habit formation with 4 types and RRULE scheduling
- **⏰ Time Management**: Timers, reminders, and Pomodoro technique integration
- **📅 Calendar Integration**: Event management with context-aware notifications
- **📈 Analytics**: Personal insights, habit trends, memory quality, and productivity analytics
- **🔍 Universal Search**: Search across all content types with semantic understanding

### **Knowledge Management Features**
- **🧠 Memory System**: Advanced episodic memory with emotional intelligence and user ratings
- **📚 Knowledge Graph**: Visual relationship mapping with D3.js interactive graphs
- **📄 Document Management**: Multi-format upload with intelligent processing
- **🏷️ Auto-Tagging**: AI-powered content categorization and metadata extraction
- **🔗 Auto-Linking**: Intelligent connection detection between related content
- **📊 Graph Analytics**: Centrality analysis and community detection
- **⭐ Quality Tracking**: Rating distribution analysis and memory value optimization

### **Security & Intelligence Tools**
- **🛡️ Vulnerability Monitoring**: Daily security intelligence reports with priority scoring
- **🚨 Threat Notifications**: Critical security alerts via mobile notifications
- **📊 Security Analytics**: Historical vulnerability tracking and trend analysis
- **🔍 Security Research**: Searchable vulnerability database with citations

### **AI-Powered Assistance**
- **💬 Conversational Interface**: Natural language interaction with context awareness
- **🧰 Tool Integration**: 15+ integrated tools for comprehensive task automation
- **📱 Smart Notifications**: Context-aware, personalized notification generation
- **🎯 Predictive Insights**: Pattern recognition for habits, productivity, and security
- **🤖 Background Processing**: Continuous analysis and insight generation
- **⭐ Rating Intelligence**: Wilson Score ranking with exploration-exploitation balance

### **Productivity & Wellness**
- **🎯 Goal Tracking**: Connect habits to long-term objectives with progress monitoring
- **📈 Progress Visualization**: Circular progress rings, trend charts, and analytics dashboards
- **⚡ Streak Management**: Motivation through streak tracking with grace periods
- **🧘 Wellness Integration**: Time-based habits for meditation, exercise, and self-care
- **📊 Performance Analytics**: Weekly comparisons, emotional patterns, and optimization suggestions

## 🛠 Comprehensive Tool Ecosystem

Sara integrates 15+ specialized tools for comprehensive assistance:

### **Core Tools**
1. **search_memory** - Advanced episodic memory search with rating-aware ranking
2. **rate_memory** - Submit 1-5 star ratings for memory quality and importance
3. **search_notes** - Full-text and semantic note search with relationship discovery
4. **create_note** - Rich note creation with auto-linking and metadata extraction
5. **search_documents** - Multi-format document search with citation support
6. **start_timer** - Smart timer creation with context-aware notifications

### **Productivity Tools**
7. **create_reminder** - Intelligent reminder scheduling with natural language
8. **list_reminders** - Active reminder management with priority sorting
9. **complete_reminder** - Reminder completion with habit integration
10. **list_calendar_events** - Calendar integration with event context
11. **create_calendar_event** - Event creation with automatic note linking

### **Habit & Wellness Tools**
12. **create_habit** - Comprehensive habit creation with RRULE scheduling
13. **log_habit_progress** - Progress tracking with streak management
14. **get_habit_insights** - Analytics and performance optimization suggestions

### **Security Tools**
15. **search_vulnerabilities** - Security intelligence search with priority filtering
16. **generate_vulnerability_report** - On-demand security assessment reports

### **System Tools**
17. **get_system_status** - Health monitoring and performance metrics
18. **analyze_patterns** - Cross-system pattern recognition and insights

## 📊 Advanced Analytics & Insights

### **Memory Analytics**
- **Rating Distribution**: Histogram of how you rate different types of memories
- **Quality Trends**: Track improvement in conversation quality over time
- **Most Valued**: Identify which topics and interactions you rate highest
- **Retrieval Patterns**: Analyze which memories are accessed most frequently
- **Rating Boost Impact**: Measure how ratings influence memory retrieval

### **Habit Analytics**
- **Performance Metrics**: Completion rates, streak analysis, and trend identification
- **Behavioral Patterns**: Best performing days, optimal times, and consistency analysis
- **Emotional Correlation**: Habit success correlation with emotional state
- **Weekly Comparisons**: Progress tracking with historical performance analysis
- **Predictive Insights**: AI suggestions for habit optimization and improvement

### **Knowledge Analytics**
- **Content Growth**: Note creation trends and knowledge base expansion
- **Connection Analysis**: Relationship strength and network topology insights
- **Topic Evolution**: How your interests and focus areas change over time
- **Memory Patterns**: Most accessed memories and knowledge retrieval patterns

### **Security Intelligence**
- **Threat Landscape**: Daily vulnerability trends and threat actor analysis
- **Priority Tracking**: Critical vulnerability monitoring with timeline analysis
- **Industry Impact**: Sector-specific vulnerability intelligence and recommendations
- **Historical Analysis**: Long-term threat trends and pattern recognition

### **Productivity Insights**
- **Time Allocation**: How you spend time across different activities and projects
- **Focus Patterns**: Deep work sessions, interruptions, and productivity optimization
- **Goal Progress**: Long-term objective tracking with milestone achievement
- **Wellness Correlation**: Relationship between habits, mood, and productivity

## 🎯 Use Cases & Workflows

### **Personal Knowledge Management**
1. **Research Projects**: Collect information, rate quality, create connections, analyze patterns
2. **Learning Journeys**: Track study progress, rate learning materials, connect concepts, review insights
3. **Project Planning**: Organize ideas, link resources, monitor progress with quality ratings
4. **Creative Writing**: Build character relationships, plot connections, rate plot developments

### **Productivity & Life Optimization**
1. **Habit Formation**: Build sustainable routines with intelligent tracking and insights
2. **Goal Achievement**: Connect daily habits to long-term objectives with progress monitoring
3. **Time Management**: Optimize schedule with timer integration and productivity analytics
4. **Wellness Tracking**: Monitor physical and mental health through habit integration

### **Professional Development**
1. **Security Research**: Stay updated on vulnerability intelligence and threat landscape
2. **Knowledge Sharing**: Build comprehensive documentation with intelligent linking
3. **Project Documentation**: Maintain living documents with automatic connections and quality ratings
4. **Meeting Management**: Calendar integration with note-taking and follow-up tracking

### **Personal Security**
1. **Threat Monitoring**: Daily vulnerability intelligence with priority notifications
2. **Security Education**: Learn about threats through integrated knowledge management
3. **Incident Tracking**: Document security events with timeline and relationship mapping
4. **Compliance Monitoring**: Track security requirements and implementation progress

## 🔧 Installation & Setup

### **Quick Start (Recommended)**
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

### **Development Mode**
```bash
# Backend (Terminal 1)
cd backend
export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/sara_hub"
export OPENAI_BASE_URL=<your-llm-endpoint>
export OPENAI_MODEL=<your-model>
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=<your-password>
export REDIS_URL=redis://localhost:6379/0
python3 app/main_simple.py

# Frontend (Terminal 2)
cd frontend
npm install
npm run dev
```

### **Essential Environment Configuration**
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

# Notifications & Alerts
NTFY_SERVER_URL=<your-ntfy-server>
NTFY_ENABLED=true
NTFY_VULNERABILITY_TOPIC=sara

# Sara Configuration
ASSISTANT_NAME=Sara
DOMAIN=<your-domain>

# Security
JWT_SECRET=<your-secure-secret-key>
COOKIE_DOMAIN=<your-domain>
```

## 🔗 Complete API Reference

### **Authentication & User Management**
```bash
POST   /auth/login                    # User authentication with JWT
POST   /auth/register                 # New user registration
POST   /auth/logout                   # Session termination
GET    /auth/me                       # Current user information
PATCH  /auth/profile                  # Update user profile
```

### **Conversational AI & Memory**
```bash
POST   /chat                          # Chat with Sara (streaming/non-streaming)
POST   /memory/search                 # Search episodic memory with context windows
GET    /memory/episodes               # List memory episodes with filtering
PATCH  /memory/episodes/{id}          # Update episode importance/metadata
DELETE /memory/episodes/{id}          # Delete specific memory episode
GET    /memory/analytics              # Memory usage analytics and patterns
POST   /memory/dream                  # Trigger dream cycle for pattern analysis
GET    /memory/insights               # Get dream insights and patterns
```

### **Rating System**
```bash
POST   /api/episodes/{id}/rate        # Rate episode (1-5 stars)
GET    /api/episodes/{id}/rating      # Get rating data for episode
DELETE /api/episodes/{id}/rating      # Delete user's rating
GET    /api/rating/stats              # Rating system statistics
POST   /api/episodes/find-by-content  # Find episode IDs for rating UI
```

### **Knowledge Management**
```bash
# Notes
GET    /notes                         # List notes with folder structure
POST   /notes                         # Create new note with auto-linking
GET    /notes/{id}                    # Get specific note with connections
PUT    /notes/{id}                    # Update note content and metadata
DELETE /notes/{id}                    # Delete note and update connections

# Folders
GET    /folders                       # List folder hierarchy
POST   /folders                       # Create new folder
PUT    /folders/{id}                  # Update folder name/parent
DELETE /folders/{id}                  # Delete folder and handle children

# Connections & Graph
GET    /notes/{id}/connections        # Get note relationships and strength
POST   /notes/{id}/connections        # Create manual connection
DELETE /connections/{id}              # Remove specific connection
GET    /knowledge-graph               # Graph visualization data
GET    /knowledge-clusters            # Content clustering analysis
```

### **Habit Tracking System**
```bash
# Core Habit Management
POST   /habits                        # Create new habit with RRULE scheduling
GET    /habits                        # List user habits with metadata
GET    /habits/{id}                   # Get specific habit details
PATCH  /habits/{id}                   # Update habit configuration
DELETE /habits/{id}                   # Delete habit and all associated data

# Daily Operations & Progress
GET    /habits/today                  # Today's habit instances with progress
POST   /habits/{id}/log               # Log habit completion/progress
POST   /habits/{id}/log-retro         # Retroactive habit logging
GET    /habits/{id}/streak            # Current and best streak information

# Advanced Features
POST   /habits/{id}/pause             # Pause habit (vacation mode)
POST   /habits/{id}/resume            # Resume paused habit
POST   /habits/{id}/items             # Add checklist items
GET    /habits/{id}/items             # Get checklist items
POST   /habits/{id}/link              # Link habit to notes/documents
GET    /habits/{id}/links             # Get habit connections

# Analytics & Insights
GET    /insights/habits               # Comprehensive habit analytics dashboard
GET    /habits/{id}/history           # Historical habit data and trends
```

### **Vulnerability Intelligence**
```bash
# Core Vulnerability Operations
GET    /vulnerability-reports         # List daily vulnerability reports
GET    /vulnerability-reports/{id}    # Get specific report content
POST   /vulnerability-reports/generate # Manual report generation
DELETE /vulnerability-reports/{id}    # Delete specific report

# Search & Intelligence
POST   /vulnerabilities/search        # Search vulnerability database
GET    /vulnerabilities/trends        # Threat landscape trends
GET    /vulnerabilities/critical      # Current critical vulnerabilities

# Notifications & Alerts
POST   /notifications/ntfy            # Send test notifications
GET    /notifications/history         # Notification delivery history
```

### **Document Processing**
```bash
# Document Management
POST   /documents                     # Upload document with AI processing
GET    /documents                     # List documents with metadata
GET    /documents/{id}                # Get document details and content
DELETE /documents/{id}                # Delete document and cleanup

# Document Intelligence
POST   /documents/search              # Semantic document search
GET    /documents/{id}/citations      # Get document citations
POST   /documents/{id}/analyze        # Trigger document reanalysis
```

### **Productivity Tools**
```bash
# Timers
POST   /timers                        # Create countdown timer
GET    /timers                        # List active timers
GET    /timers/{id}                   # Get timer status
PATCH  /timers/{id}/stop              # Stop active timer
DELETE /timers/{id}                   # Delete timer

# Reminders
POST   /reminders                     # Create reminder with scheduling
GET    /reminders                     # List active reminders
PATCH  /reminders/{id}/complete       # Mark reminder complete
DELETE /reminders/{id}                # Delete reminder

# Calendar
GET    /events                        # List calendar events
POST   /events                        # Create calendar event
GET    /events/{id}                   # Get event details
PUT    /events/{id}                   # Update event
DELETE /events/{id}                   # Delete event
```

### **System & Analytics**
```bash
# System Status
GET    /health                        # API health check
GET    /system/status                 # Comprehensive system status
GET    /analytics/dashboard           # User analytics dashboard

# Background Workers
GET    /workers/status                # Background worker status
POST   /workers/trigger/{worker_name} # Manually trigger worker

# Administration
GET    /admin/users                   # User management (admin only)
GET    /admin/system-metrics          # System performance metrics
POST   /admin/maintenance             # Trigger maintenance tasks
```

## 🧠 Advanced Memory System Deep Dive

### **Rating-Aware Episodic Memory Architecture**
Sara's memory system combines sophisticated episodic storage with user feedback for intelligent prioritization:

**Enhanced Episode Storage:**
```python
episode = {
    "content": "User interaction content",
    "role": "user|assistant",
    "importance": 0.75,                    # AI-scored (0-1)
    "user_rating": 5,                      # User feedback (1-5 stars)
    "rating_boost": 0.18,                  # Wilson Score + decay
    "exploration_bonus": 0.03,             # Thompson Sampling
    "emotional_tone": {                    # Real-time sentiment analysis
        "primary_emotion": "positive",
        "intensity": 0.8,
        "emotions": ["excitement", "confidence"]
    },
    "topics": ["productivity", "habits"],   # Extracted topics
    "context_tags": ["planning"],          # Contextual metadata
    "source": "chat|note|document|habit",  # Multi-source integration
    "embedding": [...],                    # 1024-dim BGE-M3 vector
    "access_count": 3,                     # Usage tracking
    "last_accessed": "2024-01-15T10:30:00Z",
    "created_at": "2024-01-10T14:20:00Z"
}
```

### **Wilson Score Confidence Interval**
Prevents single-vote manipulation and provides statistical confidence:

```python
def calculate_rating_boost(rating_sum, rating_count, created_at):
    # Normalize to 0-1 scale (5-star rating)
    p = rating_sum / (5.0 * rating_count)

    # Wilson Score parameters
    z = 1.96  # 95% confidence
    n = rating_count

    # Wilson Score lower bound
    numerator = p + (z²/(2n)) - z*√(p(1-p)/n + z²/(4n²))
    denominator = 1 + (z²/n)
    confidence = numerator / denominator

    # Temporal decay (exponential, 30-day half-life)
    age_days = (now - created_at).days
    decay_constant = ln(2) / 30.0
    age_decay = exp(-decay_constant * age_days)

    # Final boost (0-0.25 range, 25% of total score)
    rating_boost = confidence * age_decay * 0.25

    return rating_boost
```

### **Thompson Sampling (Cold-Start Mitigation)**
Addresses the cold-start problem for new memories:

```python
def calculate_exploration_bonus(rating_sum, rating_count, created_at):
    age_days = (now - created_at).days

    # Only apply for first 7 days
    if age_days >= 7:
        return 0.0

    # Beta distribution parameters
    alpha = rating_sum + 1
    beta = (5 * rating_count - rating_sum) + 1

    # Sample from Beta distribution
    sample = np.random.beta(alpha, beta)

    # Scale by remaining cold-start period
    age_factor = (7 - age_days) / 7.0

    return sample * age_factor * 0.1  # 0-0.1 range
```

### **Enhanced Retrieval Scoring**
Composite score combining multiple signals:

```sql
composite_score =
    (1 - (embedding <=> query_embedding)) * 0.40 +  -- Semantic (40%)
    EXP(-EXTRACT(EPOCH FROM (NOW() - created_at)) / (7 * 86400)) * 0.20 +  -- Recency (20%)
    COALESCE(importance, 0.5) * 0.20 +  -- AI Importance (20%)
    COALESCE(rating_boost, 0.0) * 0.15 +  -- Rating Boost (15%)
    COALESCE(exploration_bonus, 0.0) * 0.05  -- Exploration (5%)
```

### **Dynamic Context Windows**
Intelligent memory retrieval adapts based on query type:

1. **Temporal Windows**: "What did we discuss yesterday?" → Last 7 days
2. **Emotional Windows**: "When was I feeling happy?" → Positive emotions
3. **Topic Windows**: "About productivity" → Topic-filtered results
4. **Rating Windows**: "Best insights" → High-rated memories only
5. **Importance Windows**: High-value memories only
6. **Hybrid Windows**: Multi-criteria intelligent selection

### **Nightly Consolidation Process**
Scheduled job (2:30 AM) consolidates ratings and updates retrieval scores:

1. **Pull Dirty Episodes**: Fetch updated ratings from Redis dirty set
2. **Batch Processing**: Process 100 episodes at a time
3. **Calculate Scores**:
   - Wilson Score confidence intervals
   - Temporal decay factors
   - Thompson Sampling exploration bonuses
4. **Database Updates**: Sync Redis → PostgreSQL → Neo4j
5. **Consistency Checks**: Verify data integrity across stores
6. **Event Broadcasting**: Publish consolidation completion event

### **Dream Processing System**
Background analysis generates insights from accumulated memories and ratings:
- **Pattern Recognition**: "User rates productivity discussions highly"
- **Connection Discovery**: "High-rated habits correlate with goal achievement"
- **Behavioral Insights**: "5-star memories often involve specific topics"
- **Quality Trends**: "Rating patterns change over time indicating learning"

## 🏆 What Makes Sara Unique

### **🧠 True AI Memory with User Feedback**
- **Episodic Storage**: Every interaction becomes a rich, searchable memory
- **Rating-Based Prioritization**: User feedback directly influences memory retrieval
- **Statistical Confidence**: Wilson Score prevents manipulation, ensures quality ranking
- **Cold-Start Handling**: Thompson Sampling gives new memories fair exposure
- **Emotional Intelligence**: Understands and remembers your emotional context
- **Pattern Recognition**: Discovers behavioral patterns and personal insights
- **Context Awareness**: Retrieves relevant memories based on conversation flow and ratings

### **🔗 Living Knowledge Graph**
- **Dynamic Connections**: Relationships strengthen/weaken based on usage
- **Auto-Discovery**: AI finds semantic connections you might miss
- **Visual Exploration**: Interactive D3.js graphs for knowledge navigation
- **Multi-Layered**: Combines explicit links, semantic similarity, and temporal relationships

### **🎯 Comprehensive Life Management**
- **Unified Platform**: One system for notes, habits, tasks, calendar, and security
- **Cross-System Intelligence**: Habits connect to notes, timers link to goals, ratings guide retrieval
- **Predictive Insights**: AI suggests optimizations based on your patterns
- **Contextual Notifications**: Smart alerts reference your recent activities

### **🛡️ Security-First Design**
- **Daily Threat Intelligence**: Stay ahead of the security landscape
- **Privacy-Preserving**: Self-hosted with complete data ownership
- **Secure Architecture**: JWT, HTTPS, input validation, and audit logging
- **Intelligent Alerts**: Critical vulnerabilities trigger immediate notifications

### **🚀 Performance & Scalability**
- **Advanced Indexing**: Optimized vector search with pgvector
- **Intelligent Caching**: Redis for hot data and rating storage
- **Background Processing**: Async workers for intelligence analysis
- **Resource Optimization**: Efficient memory usage and connection pooling

## 🎛 System Requirements

### **Minimum Configuration**
- **RAM**: 4GB (8GB recommended for full feature set)
- **CPU**: 2 cores @ 2.0GHz (4 cores recommended)
- **Storage**: 10GB (20GB for production with documents/media)
- **Network**: Stable internet for LLM API calls

### **Production Configuration**
- **RAM**: 16GB+ (for large knowledge bases and concurrent users)
- **CPU**: 8 cores @ 3.0GHz+ (for real-time AI processing)
- **Storage**: 100GB+ SSD (for performance and growth)
- **Network**: Low-latency connection to LLM endpoints
- **Backup**: Automated daily backups for PostgreSQL, Neo4j, and Redis

### **Enterprise Scaling**
- **Distributed**: Multi-node PostgreSQL and Neo4j clusters
- **Load Balancing**: nginx with multiple backend instances
- **Caching**: Redis cluster for hot data and session management
- **Monitoring**: Comprehensive logging and alerting infrastructure

## 🔮 Roadmap & Future Enhancements

### **Near-Term**
- **🎙️ Voice Interface**: Speech-to-text integration with real-time conversation
- **📱 Mobile App**: React Native companion with offline rating capabilities
- **🔄 Real-Time Sync**: WebSocket-based live updates across devices
- **🎨 Custom Themes**: Personalized UI themes and layout options
- **📊 Rating Analytics Dashboard**: Visualize rating patterns and memory quality trends

### **Medium-Term**
- **🤝 Multi-User**: Shared knowledge spaces with permission management and aggregated ratings
- **🔗 API Integrations**: Connect to Todoist, Notion, Google Calendar, GitHub
- **🧮 Advanced Analytics**: Machine learning insights and predictive modeling
- **💬 Conversation Templates**: Pre-defined conversation flows and automation
- **⭐ Multi-Dimensional Ratings**: Rate on accuracy, helpfulness, and clarity separately

### **Long-Term**
- **🌐 Federation**: Connect multiple Sara instances with privacy preservation
- **🤖 Advanced AI**: GPT-4 integration, custom model training, and fine-tuning
- **🔒 Enterprise Features**: SSO, advanced security, compliance reporting
- **📈 Predictive Intelligence**: Proactive suggestions and automated task management
- **🎯 Personalized Scoring**: ML-tuned retrieval weights per user based on rating patterns

### **Research & Innovation**
- **🧠 Memory Consolidation**: Hierarchical memory structures with rating-based compression
- **🎯 Behavioral Modeling**: Advanced pattern recognition from rating patterns
- **🔮 Predictive Analytics**: Anticipate user needs based on rating history
- **🌟 Emergent Intelligence**: Cross-user learning with privacy-preserving rating aggregation

## 📄 License & Contributing

### **License**
MIT License - See LICENSE file for details

### **Contributing**
We welcome contributions! Please see our contributing guidelines:
1. Fork the repository
2. Create a feature branch
3. Make your changes with comprehensive tests
4. Submit a pull request with detailed description

### **Community**
- **Documentation**: Comprehensive guides and API documentation
- **Support**: GitHub issues and community discussions
- **Feature Requests**: GitHub discussions and enhancement proposals

---

## 🌟 Why Choose Sara?

Sara isn't just another AI assistant - it's a comprehensive personal intelligence system that grows with you and learns from your feedback. By combining advanced AI, sophisticated memory with rating-based prioritization, comprehensive life management, and security intelligence, Sara becomes your trusted companion for knowledge work, personal development, and staying secure in an increasingly complex digital world.

**The rating system ensures Sara prioritizes what matters most to you** - highly-rated insights resurface when relevant, low-quality memories fade naturally, and new content gets fair exposure through intelligent exploration strategies.

**Experience the future of personal AI - where memory meets intelligence, user feedback drives retrieval, and knowledge becomes actionable insight.**

---

**Sara AI Personal Hub** - Your intelligent companion for life, work, and security. Built for deep, contextual, and continuously evolving AI interaction with human-guided memory prioritization.
