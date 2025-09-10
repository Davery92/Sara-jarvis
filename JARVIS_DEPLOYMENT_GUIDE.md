# Jarvis Mode Deployment Guide

This guide walks through deploying Jarvis mode (autonomous Sara) on any server. The setup script automates most of the process.

## 📋 Prerequisites

### System Requirements
- **OS**: Ubuntu 20.04+ / Debian 11+ / CentOS 8+
- **Memory**: 4GB+ RAM recommended
- **Storage**: 10GB+ free space
- **Network**: Internet access for package installation

### Software Dependencies
- **Python**: 3.8+
- **PostgreSQL**: 12+ with pgvector extension
- **Node.js**: 16+ (for frontend)
- **Redis**: 6+ (for caching and task queues)
- **Git**: For cloning repository

### Required Information
- Database connection details
- Domain name (if using custom domain)
- SSL certificates (if using HTTPS)
- SMTP settings (for notifications)

## 🚀 Quick Setup

### 1. Clone Repository
```bash
git clone <your-repository-url> /opt/jarvis
cd /opt/jarvis
```

### 2. Run Setup Script
```bash
sudo chmod +x scripts/setup_jarvis_server.sh
sudo ./scripts/setup_jarvis_server.sh
```

The script will:
- Install system dependencies
- Create database and user
- Run migrations
- Configure services
- Set up cron jobs
- Start applications

### 3. Configure Environment
Edit `/opt/jarvis/.env`:
```bash
# Jarvis Mode Configuration
JARVIS_MODE=true
PRIVACY_STRICT=true
SOLO_USER_ID=1

# Database
DATABASE_URL="postgresql+psycopg://jarvis_user:jarvis_pass@localhost:5432/jarvis_db"

# LLM Configuration
OPENAI_BASE_URL=http://your-llm-endpoint:11434/v1
OPENAI_MODEL=your-model-name
OPENAI_API_KEY=your-api-key

# Embedding Service
EMBEDDING_BASE_URL=http://your-embedding-endpoint:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Nudge Policy
NUDGE_WINDOW=08:00-20:00
NUDGE_BATCH_INTERVAL_MIN=30
NUDGE_MAX_PER_DAY=8
DREAM_AT=02:30

# Notifications
NTFY_SERVER_URL=http://localhost:8889
NTFY_ENABLED=true

# Application
ASSISTANT_NAME="Jarvis"
DOMAIN=your-domain.com
```

### 4. Start Services
```bash
sudo systemctl start jarvis-backend
sudo systemctl start jarvis-frontend
sudo systemctl enable jarvis-backend
sudo systemctl enable jarvis-frontend
```

## 📁 Directory Structure

```
/opt/jarvis/
├── backend/                 # Python FastAPI backend
│   ├── app/                # Application code
│   ├── scripts/            # Utility scripts
│   └── logs/               # Application logs
├── frontend/               # React frontend
│   ├── src/                # Source code
│   └── dist/               # Built assets
├── scripts/                # Deployment scripts
├── logs/                   # System logs
├── .env                    # Environment configuration
└── docker-compose.yml     # Container orchestration
```

## 🔧 Manual Setup (Alternative)

If you prefer manual setup or need customization:

### 1. System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nodejs npm postgresql-14 postgresql-14-pgvector redis-server nginx certbot
```

**CentOS/RHEL:**
```bash
sudo dnf install -y python3 python3-pip nodejs npm postgresql-server postgresql-contrib redis nginx certbot
sudo postgresql-setup --initdb
```

### 2. Database Setup
```bash
sudo -u postgres psql << EOF
CREATE USER jarvis_user WITH PASSWORD 'jarvis_pass';
CREATE DATABASE jarvis_db OWNER jarvis_user;
GRANT ALL PRIVILEGES ON DATABASE jarvis_db TO jarvis_user;
\c jarvis_db;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF
```

### 3. Application Setup
```bash
# Backend
cd /opt/jarvis/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run migrations
python3 migrate_jarvis_tables.py
python3 scripts/setup_solo_user.py

# Frontend
cd /opt/jarvis/frontend
npm install
npm run build
```

### 4. Service Configuration

Create systemd services:

**/etc/systemd/system/jarvis-backend.service:**
```ini
[Unit]
Description=Jarvis Backend API
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=jarvis
Group=jarvis
WorkingDirectory=/opt/jarvis/backend
Environment=PATH=/opt/jarvis/backend/venv/bin
EnvironmentFile=/opt/jarvis/.env
ExecStart=/opt/jarvis/backend/venv/bin/python app/main_simple.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**/etc/systemd/system/jarvis-frontend.service:**
```ini
[Unit]
Description=Jarvis Frontend Server
After=network.target

[Service]
Type=simple
User=jarvis
Group=jarvis
WorkingDirectory=/opt/jarvis/frontend
ExecStart=/usr/bin/npx serve -s dist -l 3000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 5. Nginx Configuration

**/etc/nginx/sites-available/jarvis:**
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    # API Backend
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 6. SSL Setup (Optional)
```bash
sudo certbot --nginx -d your-domain.com
```

## ⏰ Cron Jobs

The setup script automatically configures these cron jobs:

```bash
# Daily Brief Generation (6:30 AM)
30 6 * * * JARVIS_MODE=true SOLO_USER_ID=1 DATABASE_URL="postgresql+psycopg://jarvis_user:jarvis_pass@localhost:5432/jarvis_db" /opt/jarvis/backend/venv/bin/python /opt/jarvis/scripts/daily_brief_simple.py >> /opt/jarvis/logs/daily_brief.log 2>&1

# Memory Consolidation (2:30 AM) - Phase 2
# 30 2 * * * JARVIS_MODE=true /opt/jarvis/backend/venv/bin/python /opt/jarvis/scripts/dream_consolidation.py >> /opt/jarvis/logs/dream.log 2>&1

# Log Rotation (Weekly)
0 3 * * 0 /usr/bin/find /opt/jarvis/logs -name "*.log" -mtime +7 -delete
```

## 🔍 Health Checks

### Verify Installation
```bash
# Check services
sudo systemctl status jarvis-backend jarvis-frontend

# Check database connection
psql "postgresql://jarvis_user:jarvis_pass@localhost:5432/jarvis_db" -c "SELECT version();"

# Check API health
curl http://localhost:8000/health

# Check frontend
curl http://localhost:3000/
```

### View Logs
```bash
# Application logs
tail -f /opt/jarvis/logs/daily_brief.log
tail -f /opt/jarvis/backend/logs/*.log

# System logs
journalctl -u jarvis-backend -f
journalctl -u jarvis-frontend -f
```

## 🔧 Configuration Options

### Jarvis Mode Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `JARVIS_MODE` | `false` | Enable autonomous mode |
| `SOLO_USER_ID` | `1` | Primary user ID |
| `NUDGE_WINDOW` | `08:00-20:00` | Active hours for notifications |
| `NUDGE_MAX_PER_DAY` | `8` | Maximum daily notifications |
| `DREAM_AT` | `02:30` | Memory consolidation time |

### Database Configuration

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection (for caching) |

### AI/LLM Configuration

| Variable | Description |
|----------|-------------|
| `OPENAI_BASE_URL` | LLM API endpoint |
| `OPENAI_MODEL` | Model name |
| `EMBEDDING_MODEL` | Embedding model |

## 🚨 Troubleshooting

### Common Issues

**1. Database Connection Errors**
```bash
# Check PostgreSQL status
sudo systemctl status postgresql
sudo systemctl start postgresql

# Test connection
psql "postgresql://jarvis_user:jarvis_pass@localhost:5432/jarvis_db" -c "SELECT 1;"
```

**2. Permission Errors**
```bash
# Fix ownership
sudo chown -R jarvis:jarvis /opt/jarvis
chmod +x /opt/jarvis/scripts/*.py
```

**3. Cron Job Not Running**
```bash
# Check cron service
sudo systemctl status cron

# View cron logs
grep CRON /var/log/syslog
tail -f /opt/jarvis/logs/daily_brief.log
```

**4. API Not Responding**
```bash
# Check backend service
sudo systemctl status jarvis-backend
journalctl -u jarvis-backend --since "1 hour ago"

# Check port binding
sudo netstat -tlnp | grep :8000
```

### Log Locations

- **Application Logs**: `/opt/jarvis/logs/`
- **System Logs**: `journalctl -u jarvis-*`
- **Nginx Logs**: `/var/log/nginx/`
- **Cron Logs**: `/var/log/cron`

## 🔄 Updates

### Updating Jarvis
```bash
cd /opt/jarvis
git pull origin main

# Backend updates
cd backend
source venv/bin/activate
pip install -r requirements.txt
python3 migrate_jarvis_tables.py  # Run any new migrations

# Frontend updates
cd ../frontend
npm install
npm run build

# Restart services
sudo systemctl restart jarvis-backend jarvis-frontend
```

## 🛡️ Security

### Firewall Configuration
```bash
# UFW (Ubuntu)
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Deny direct access to backend
sudo ufw deny 8000/tcp
```

### Database Security
```bash
# Restrict PostgreSQL access
sudo nano /etc/postgresql/14/main/pg_hba.conf
# Change 'trust' to 'md5' for local connections

sudo systemctl restart postgresql
```

## 📊 Monitoring

### Health Monitoring Script
Create `/opt/jarvis/scripts/health_check.sh`:
```bash
#!/bin/bash
# Basic health monitoring for Jarvis

# Check services
systemctl is-active --quiet jarvis-backend || echo "Backend service down"
systemctl is-active --quiet jarvis-frontend || echo "Frontend service down"

# Check API
curl -f http://localhost:8000/health || echo "API health check failed"

# Check database
psql $DATABASE_URL -c "SELECT 1;" || echo "Database connection failed"
```

### Monitoring Cron
```bash
# Add to crontab
*/5 * * * * /opt/jarvis/scripts/health_check.sh >> /opt/jarvis/logs/health.log 2>&1
```

## 📞 Support

For issues or questions:

1. Check logs: `/opt/jarvis/logs/`
2. Review this guide
3. Check GitHub issues
4. Join community discussions

---

**Next Steps**: After successful deployment, your Jarvis AI will:
- Generate daily briefs at 6:30 AM
- Process notifications through the unified inbox
- Operate in proactive autonomous mode
- Be ready for Phase 2 enhancements (memory consolidation, sprite system, etc.)