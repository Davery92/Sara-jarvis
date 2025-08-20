# Sara Personal Hub

A comprehensive personal AI assistant and knowledge management system with human-like memory, intelligent knowledge graphs, and AI-powered notifications, built for sara.avery.cloud.

## 🎯 Overview

Sara is your personal AI hub that combines conversational AI, human-like memory, knowledge management, and smart notifications into a unified platform. Unlike traditional chatbots, Sara maintains persistent memory of your interactions, builds connections between your content, and provides contextual, personalized assistance.

## ✨ Core Features

### 🤖 **Conversational AI Assistant**
- Natural language interaction with tool-calling capabilities
- Selective RAG retrieval (retrieves context only when needed)
- Persistent episodic memory across sessions
- Context-aware responses based on your conversation history

### 🧠 **Human-Like Memory System**
- **Episodic Memory**: Every interaction stored with importance scoring
- **Composite Retrieval**: Combines similarity, recency, importance, and frequency
- **Memory Compaction**: Daily/weekly summaries to compress old memories
- **Smart Context**: AI decides when to retrieve relevant memories
- **Importance Scoring**: Content automatically rated for relevance (0-1 scale)

### 📚 **Knowledge Garden (Obsidian-style)**
- **Bidirectional Linking**: Auto-detects `[[Note Title]]` syntax and connections
- **Interactive Graph View**: D3.js visualization of notes and relationships
- **Timeline View**: Chronological exploration of notes and memories
- **Connection Types**: Reference (explicit), Semantic (AI-detected), Temporal (time-based)
- **Auto-Connection Detection**: AI automatically creates semantic links between related content
- **Backlinks & Related Notes**: Automatically discovered relationships
- **Hierarchical Folders**: Organize notes in nested folder structures

### 🔗 **Dual-Database Knowledge Graph**
- **Neo4j Primary**: Graph database for complex relationships and fast traversal
- **PostgreSQL Backup**: Relational database ensuring data consistency
- **Intelligent Processing Pipeline**: Background workers analyze content for connections
- **Entity Extraction**: Automatically identifies people, organizations, topics
- **Semantic Clustering**: Groups related content using AI similarity
- **Connection Suggestions**: AI recommends related content for linking

### 📄 **Document Processing & Management**
- **Multi-format Support**: PDF, DOCX, PPTX, text, markdown, CSV
- **Intelligent Extraction**: AI processes content for semantic understanding
- **Vector Search**: Find documents by meaning, not just keywords
- **Automatic Tagging**: AI categorizes and tags uploaded content
- **MinIO Storage**: Scalable object storage for file management

### ⏰ **Smart Timers & Reminders**
- **Live Countdown Timers**: Real-time updates without page refresh
- **AI-Generated Notifications**: Personalized NTFY messages based on context
- **Persistent Timers**: Continue running across browser sessions
- **Context-Aware Alerts**: Notifications reference your recent activities
- **Mobile Push Notifications**: NTFY integration for mobile alerts

### 📱 **AI-Powered Notifications**
- **Contextual Messages**: AI generates personalized notification content
- **User History Awareness**: References your recent conversations and activities
- **Multiple Notification Types**: Timers, reminders, document processing, system alerts
- **Fallback System**: Graceful degradation to simple messages if AI fails
- **Single Topic Consolidation**: All notifications via 'sara' NTFY topic

### 📅 **Calendar Integration**
- **Event Management**: Create, edit, and view calendar events
- **Time-based Connections**: Links events to related notes and memories
- **Contextual Reminders**: AI-enhanced event notifications

### 🔍 **Advanced Search & Discovery**
- **Hybrid Search**: Combines full-text, semantic, and graph-based search
- **Multi-Content Search**: Search across notes, documents, memories, and events
- **Relationship Discovery**: Find content through connection networks
- **Timeline Search**: Explore content chronologically
- **Smart Filters**: Filter by content type, date ranges, importance scores

## 🏗 Architecture

### **Frontend Stack**
- **React 18**: Modern UI framework with hooks and context
- **TypeScript**: Type-safe development
- **Vite**: Fast build tool and dev server
- **Tailwind CSS**: Utility-first styling
- **D3.js**: Interactive graph visualizations
- **TanStack Query**: Server state management

### **Backend Stack**
- **FastAPI**: Modern Python web framework
- **SQLAlchemy**: ORM with PostgreSQL and Neo4j integration
- **Neo4j**: Graph database for knowledge relationships
- **PostgreSQL 16**: Primary relational database with pgvector
- **pgvector**: Vector similarity search extension
- **httpx**: Async HTTP client for LLM integration

### **Storage & Infrastructure**
- **MinIO**: S3-compatible object storage
- **Docker Compose**: Container orchestration
- **nginx**: Reverse proxy and SSL termination
- **JWT Authentication**: Secure session management

### **AI & LLM Integration**
- **OpenAI-Compatible API**: Flexible LLM provider support
- **gpt-oss:120b**: Default large language model
- **bge-m3**: Multilingual embedding model
- **Custom Intelligence Pipeline**: Background processing for content analysis

## 🚀 Quick Start

### **1. Clone and Setup**
```bash
git clone <this-repo>
cd sara-hub
cp .env.example .env
# Edit .env with your configuration
```

### **2. Start Services**
```bash
# Start all services
docker-compose up -d

# Or start specific services
docker-compose up -d postgres minio
```

### **3. Manual Development Mode**
```bash
# Backend (Terminal 1)
cd backend
export DATABASE_URL="postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub"
export OPENAI_BASE_URL=http://100.104.68.115:11434/v1
export OPENAI_MODEL=gpt-oss:120b
export NEO4J_URI=bolt://10.185.1.180:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=sara-graph-secret
python3 app/main_simple.py

# Frontend (Terminal 2)
cd frontend
npm run dev
```

### **4. Access Points**
- **Frontend**: http://10.185.1.180:3000
- **Backend API**: http://10.185.1.180:8000
- **API Docs**: http://10.185.1.180:8000/docs
- **Database**: 10.185.1.180:5432
- **Neo4j Browser**: http://10.185.1.180:7474
- **MinIO Console**: http://10.185.1.180:9001

## ⚙️ Configuration

### **Environment Variables**

```env
# LLM Configuration
OPENAI_BASE_URL=http://100.104.68.115:11434/v1
OPENAI_MODEL=gpt-oss:120b
OPENAI_API_KEY=dummy

# Embeddings
EMBEDDING_BASE_URL=http://100.104.68.115:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Neo4j Knowledge Graph
NEO4J_URI=bolt://10.185.1.180:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=sara-graph-secret

# Database
DATABASE_URL=postgresql+psycopg://sara:sara123@10.185.1.180:5432/sara_hub

# NTFY Notifications
NTFY_SERVER_URL=http://10.185.1.8:8889
NTFY_ENABLED=true

# Sara Branding
ASSISTANT_NAME=Sara
DOMAIN=sara.avery.cloud

# Security
JWT_SECRET=your-secret-key
COOKIE_DOMAIN=.sara.avery.cloud
```

### **Development Commands**

```bash
# Frontend
cd frontend
npm run dev        # Development server (port 3000)
npm run build      # Production build
npm run lint       # ESLint checks
npm run preview    # Preview production build

# Backend
cd backend
python3 app/main_simple.py                    # Start development server
python3 data_consistency_check.py             # Check database consistency
python3 cleanup_orphaned_neo4j_data.py        # Clean orphaned graph data
```

## 🧠 Memory System Deep Dive

### **Episodic Memory**
Every interaction with Sara is stored as an "episode" with metadata:
- **Content**: The actual conversation turn
- **Role**: User or assistant
- **Importance**: AI-scored relevance (0-1)
- **Embedding**: Vector representation for similarity search
- **Metadata**: Timestamps, source, context tags

### **Retrieval Strategy**
Sara uses composite scoring to find relevant memories:
```python
relevance_score = (
    0.4 * cosine_similarity +
    0.3 * recency_score +
    0.2 * importance_score +
    0.1 * frequency_score
)
```

### **Memory Compaction**
- **Daily Summaries**: Compress interactions into key insights
- **Weekly Reviews**: Higher-level pattern recognition
- **Importance Decay**: Reduce importance of stale memories
- **Connection Strengthening**: Reinforce frequently accessed memories

## 🔗 Knowledge Graph Features

### **Connection Types**
- **REFERENCES**: Explicit `[[Note Title]]` links
- **SEMANTIC_SIMILAR**: AI-detected content similarity (threshold: 0.6+)
- **TEMPORAL_NEAR**: Created within similar timeframes
- **MENTIONS**: Entity/topic references
- **FOLLOWS**: Sequential content relationships

### **Graph Capabilities**
- **Traversal**: Find related content up to N degrees of separation
- **Clustering**: Community detection for topic groups
- **Centrality**: Identify important hub content
- **Path Finding**: Discover connection routes between content
- **Subgraph Extraction**: Extract focused topic networks

### **Intelligence Pipeline**
Background workers continuously analyze content:
1. **Fast Processing**: Embedding generation, basic connections
2. **Deep Processing**: Entity extraction, semantic analysis, topic modeling
3. **Relationship Scoring**: Strengthen/weaken connections based on usage
4. **Consistency Monitoring**: Ensure Neo4j and PostgreSQL stay synchronized

## 📱 AI Notification System

### **Context-Aware Generation**
Sara generates personalized notifications by:
1. **Context Gathering**: Recent conversation history (last 3 interactions)
2. **Prompt Engineering**: Type-specific prompts for timers, reminders, documents
3. **LLM Generation**: AI creates contextual title and message
4. **Fallback Handling**: Graceful degradation to simple messages if AI fails

### **Notification Types**
- **Timer Completion**: "Great job on that 25-minute focus session! Time for a well-deserved break 🎯"
- **Reminders**: "Don't forget to call mom - I know you mentioned wanting to catch up this week! 📞"
- **Document Processing**: "Your meeting notes are ready! I've extracted the key action items for you 📋"

### **NTFY Integration**
- **Self-Hosted**: Private notification server at 10.185.1.8:8889
- **Mobile Apps**: Subscribe to 'sara' topic in NTFY mobile app
- **Action Buttons**: Quick actions like "Dismiss" or "View Document"
- **Priority Levels**: High priority for timers, normal for reminders

## 🛠 API Reference

### **Authentication**
```bash
POST /auth/login
POST /auth/register
POST /auth/logout
```

### **Chat & Memory**
```bash
POST /chat                    # Chat with Sara
POST /memory/search           # Search episodic memory
GET  /memory/episodes         # List memory episodes
PATCH /memory/episodes/{id}   # Update episode importance
DELETE /memory/episodes/{id}  # Delete episode
```

### **Knowledge Management**
```bash
GET    /notes                 # List notes
POST   /notes                 # Create note
PUT    /notes/{id}            # Update note
DELETE /notes/{id}            # Delete note
GET    /notes/{id}/connections # Get note relationships
POST   /notes/{id}/connections # Create note connection

GET    /knowledge-graph       # Get graph visualization data
GET    /knowledge-clusters    # Get content clusters
```

### **Documents**
```bash
POST   /documents             # Upload document
GET    /documents             # List documents
DELETE /documents/{id}        # Delete document
POST   /documents/search      # Search documents
```

### **Timers & Reminders**
```bash
POST   /timers               # Create timer
GET    /timers               # List active timers
PATCH  /timers/{id}/stop     # Stop timer
DELETE /timers/{id}          # Delete timer

POST   /reminders            # Create reminder
GET    /reminders            # List reminders
PATCH  /reminders/{id}/complete # Complete reminder
DELETE /reminders/{id}       # Delete reminder
```

### **Calendar**
```bash
GET    /events               # List calendar events
POST   /events               # Create event
PUT    /events/{id}          # Update event
DELETE /events/{id}          # Delete event
```

## 🔧 Development & Extension

### **Adding New Tools**
1. Create tool function in `backend/app/tools/`
2. Register in `backend/app/tools/registry.py`
3. Add to available tools in chat handler

### **Adding Frontend Features**
1. Create component in `frontend/src/components/`
2. Add route/view to `frontend/src/App-interactive.tsx`
3. Add any required API calls

### **Database Migrations**
1. Modify models in `backend/app/main_simple.py`
2. Create Alembic migration: `alembic revision --autogenerate`
3. Apply migration: `alembic upgrade head`

### **Neo4j Schema Changes**
1. Update `backend/app/services/neo4j_service.py`
2. Add new constraints/indexes in `initialize_schema()`
3. Update intelligence pipeline if needed

## 🚀 Deployment

### **Production Setup**
```bash
# 1. Clone and configure
git clone <repo>
cd sara-hub
cp .env.example .env
# Edit .env for production

# 2. Start services
docker-compose up -d

# 3. Configure reverse proxy
# Point sara.avery.cloud → 10.185.1.180:3000
# Enable SSL termination
```

### **nginx Configuration**
```nginx
server {
    listen 443 ssl;
    server_name sara.avery.cloud;
    
    location / {
        proxy_pass http://10.185.1.180:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /api {
        proxy_pass http://10.185.1.180:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### **Monitoring & Maintenance**
```bash
# Check service health
docker-compose ps

# View logs
docker-compose logs -f

# Database consistency check
python3 backend/data_consistency_check.py

# Backup databases
pg_dump sara_hub > backup.sql
neo4j-admin database dump sara
```

## 📊 System Requirements

### **Minimum**
- **RAM**: 4GB (8GB recommended)
- **CPU**: 2 cores (4 cores recommended)  
- **Storage**: 10GB (50GB recommended)
- **Network**: Stable internet for LLM API calls

### **Recommended Production**
- **RAM**: 16GB+
- **CPU**: 8 cores+
- **Storage**: 100GB+ SSD
- **Network**: Low-latency connection to LLM endpoint

## 🆘 Troubleshooting

### **Common Issues**

**Chat not working**: Check OPENAI_BASE_URL and model availability
```bash
curl http://100.104.68.115:11434/v1/models
```

**Graph view empty**: Verify Neo4j connection and run consistency check
```bash
python3 backend/data_consistency_check.py
```

**Notifications not working**: Check NTFY server status
```bash
curl http://10.185.1.8:8889/sara -d "Test message"
```

**Database errors**: Check PostgreSQL connection and migrations
```bash
psql postgresql://sara:sara123@10.185.1.180:5432/sara_hub
```

### **Debug Mode**
Set environment variables for detailed logging:
```bash
export LOG_LEVEL=DEBUG
export PYTHONPATH=/home/david/jarvis/backend
```

## 📝 License

[Add your license information here]

## 🤝 Contributing

[Add contribution guidelines here]

---

**Sara Personal Hub** - Your intelligent personal assistant with human-like memory and knowledge graphs. Built for deep, contextual, and personalized AI interaction.