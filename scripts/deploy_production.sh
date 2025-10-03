#!/bin/bash

# Sara/Jarvis Production Deployment Script
# This script sets up the complete production environment on 10.185.1.188

set -e  # Exit on any error

echo "🚀 Starting Sara/Jarvis Production Deployment for 10.185.1.188"
echo "================================================================"

# Configuration for production server
PROD_SERVER_IP="10.185.1.188"
DATABASE_SERVER_IP="10.185.1.188"  # Database will also be on the prod server
FRONTEND_PORT="3000"
BACKEND_PORT="8000"
DATABASE_PORT="5432"

# User credentials (update these as needed)
SARA_USER_EMAIL="david@avery.cloud"
SARA_USER_PASSWORD="Nutman17!"
SOLO_USER_ID="64f37c56-85cb-4590-8de9-adfc17d343ed"

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "📂 Project root: $PROJECT_ROOT"
echo "🖥️  Production server: $PROD_SERVER_IP"
echo "💾 Database server: $DATABASE_SERVER_IP"

# Function to create directory if it doesn't exist
create_dir() {
    if [ ! -d "$1" ]; then
        echo "📁 Creating directory: $1"
        mkdir -p "$1"
    else
        echo "✅ Directory already exists: $1"
    fi
}

# Function to backup existing crontab
backup_crontab() {
    echo "💾 Backing up existing crontab..."
    crontab -l > "$PROJECT_ROOT/backups/crontab_backup_$(date +%Y%m%d_%H%M%S).txt" 2>/dev/null || echo "No existing crontab to backup"
}

# Function to setup directories
setup_directories() {
    echo "📁 Setting up required directories..."
    create_dir "$PROJECT_ROOT/logs"
    create_dir "$PROJECT_ROOT/backups"
    create_dir "$PROJECT_ROOT/data"
    create_dir "/data/redis"
    create_dir "/data/postgres"
    create_dir "/data/neo4j"
    create_dir "/data/minio"
}

# Function to create production environment file
create_env_file() {
    echo "⚙️  Creating production environment file..."
    cat > "$PROJECT_ROOT/.env.production" << EOF
# Sara/Jarvis Production Environment Configuration
# Generated on $(date)

# Server Configuration
VITE_DOMAIN=sara.avery.cloud
DOMAIN=sara.avery.cloud
COOKIE_DOMAIN=.sara.avery.cloud

# Database Configuration  
DATABASE_URL=postgresql+psycopg://sara:sara123@${DATABASE_SERVER_IP}:${DATABASE_PORT}/sara_hub

# AI Configuration
OPENAI_BASE_URL=http://100.104.68.115:11434/v1
OPENAI_MODEL=gpt-oss:120b
OPENAI_API_KEY=dummy
EMBEDDING_BASE_URL=http://100.104.68.115:11434
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Jarvis Mode Configuration
JARVIS_MODE=true
SOLO_USER_ID=${SOLO_USER_ID}
ASSISTANT_NAME=Sara

# Neo4j Configuration
GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=sara-graph-secret

# MinIO Configuration
MINIO_URL=http://minio:9000
MINIO_BUCKET=sara-docs
MINIO_ACCESS_KEY=sara
MINIO_SECRET_KEY=sara123

# Security
JWT_SECRET=sara-hub-jwt-secret-change-in-production
CORS_ORIGINS=["http://${PROD_SERVER_IP}:${FRONTEND_PORT}","https://sara.avery.cloud","http://localhost:3000"]

# Services
SEARXNG_BASE_URL=http://10.185.1.8:4000
REDIS_URL=redis://redis:6379/0

# Timezone
TIMEZONE=America/New_York

# Vulnerability Monitoring
SARA_USER_EMAIL=${SARA_USER_EMAIL}
SARA_USER_PASSWORD=${SARA_USER_PASSWORD}
NTFY_VULNERABILITY_TOPIC=vulns
EOF

    echo "✅ Environment file created at $PROJECT_ROOT/.env.production"
}

# Function to update docker-compose for production
update_docker_compose() {
    echo "🐳 Creating production docker-compose configuration..."
    
    # Create production-specific docker-compose override
    cat > "$PROJECT_ROOT/docker-compose.prod.yml" << EOF
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "6gb", "--maxmemory-policy", "allkeys-lfu"]
    restart: unless-stopped
    volumes:
      - /data/redis:/data
    ports:
      - "${PROD_SERVER_IP}:6379:6379"

  frontend:
    build:
      context: ./frontend
      args:
        VITE_ASSISTANT_NAME: Sara
        VITE_DOMAIN: sara.avery.cloud
    ports:
      - "${PROD_SERVER_IP}:${FRONTEND_PORT}:3000"
    restart: unless-stopped
    environment:
      - VITE_SPRITE_BUS=true
      - VITE_ASSISTANT_NAME=Sara
      - VITE_DOMAIN=sara.avery.cloud
    depends_on:
      - backend

  backend:
    build: ./backend
    ports:
      - "${PROD_SERVER_IP}:${BACKEND_PORT}:8000"
    restart: unless-stopped
    env_file:
      - .env.production
    depends_on:
      db:
        condition: service_started
      minio:
        condition: service_started

  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_DB: sara_hub
      POSTGRES_USER: sara
      POSTGRES_PASSWORD: sara123
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "${DATABASE_SERVER_IP}:${DATABASE_PORT}:5432"

  minio:
    image: quay.io/minio/minio
    command: server /data --console-address ":9001"
    restart: unless-stopped
    environment:
      MINIO_ROOT_USER: sara
      MINIO_ROOT_PASSWORD: sara1234
    ports:
      - "${PROD_SERVER_IP}:9000:9000"
      - "${PROD_SERVER_IP}:9001:9001"
    volumes:
      - minio_data:/data

  neo4j:
    image: neo4j:5.15-community
    profiles: ["graph-neo4j"]
    restart: unless-stopped
    environment:
      NEO4J_AUTH: neo4j/sara-graph-secret
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
      NEO4J_dbms_security_procedures_unrestricted: apoc.*,gds.*
      NEO4J_dbms_security_procedures_allowlist: apoc.*,gds.*
      NEO4J_apoc_export_file_enabled: 'true'
      NEO4J_apoc_import_file_enabled: 'true'
      NEO4J_apoc_import_file_use__neo4j__config: 'true'
      NEO4J_ACCEPT_LICENSE_AGREEMENT: 'yes'
    ports:
      - "${PROD_SERVER_IP}:7474:7474"  # HTTP
      - "${PROD_SERVER_IP}:7687:7687"  # Bolt
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - neo4j_import:/var/lib/neo4j/import
      - neo4j_plugins:/plugins
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "sara-graph-secret", "RETURN 1;"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 25s

volumes:
  postgres_data:
  minio_data:
  neo4j_data:
  neo4j_logs:
  neo4j_import:
  neo4j_plugins:
EOF

    echo "✅ Production docker-compose configuration created"
}

# Function to setup cron jobs
setup_cron_jobs() {
    echo "⏰ Setting up cron jobs..."
    
    # Backup existing crontab
    backup_crontab
    
    # Create new crontab content
    cat > "$PROJECT_ROOT/temp_crontab.txt" << EOF
# Sara/Jarvis Production Cron Jobs
# Generated on $(date)

# Daily vulnerability report at 5:00 AM
0 5 * * * SARA_USER_EMAIL=${SARA_USER_EMAIL} SARA_USER_PASSWORD=${SARA_USER_PASSWORD} /usr/bin/python3 ${PROJECT_ROOT}/scripts/generate_daily_vulnerability_report.py >> ${PROJECT_ROOT}/logs/vulnerability_reports.log 2>&1

# Daily brief at 6:30 AM  
30 6 * * * JARVIS_MODE=true SOLO_USER_ID=${SOLO_USER_ID} DATABASE_URL="postgresql+psycopg://sara:sara123@${DATABASE_SERVER_IP}:${DATABASE_PORT}/sara_hub" /usr/bin/python3 ${PROJECT_ROOT}/scripts/daily_brief_simple.py >> ${PROJECT_ROOT}/logs/daily_brief.log 2>&1

# Weekly system health check every Sunday at 2:00 AM
0 2 * * 0 ${PROJECT_ROOT}/scripts/weekly_health_check.sh >> ${PROJECT_ROOT}/logs/health_check.log 2>&1

# Monthly log rotation on the 1st at 1:00 AM
0 1 1 * * ${PROJECT_ROOT}/scripts/rotate_logs.sh >> ${PROJECT_ROOT}/logs/log_rotation.log 2>&1
EOF

    # Install the new crontab
    crontab "$PROJECT_ROOT/temp_crontab.txt"
    rm "$PROJECT_ROOT/temp_crontab.txt"
    
    echo "✅ Cron jobs installed successfully"
    echo "📋 Current crontab:"
    crontab -l
}

# Function to create health check script
create_health_check_script() {
    echo "🏥 Creating health check script..."
    cat > "$PROJECT_ROOT/scripts/weekly_health_check.sh" << 'EOF'
#!/bin/bash

# Weekly Health Check Script for Sara/Jarvis
echo "=== Sara/Jarvis Weekly Health Check - $(date) ==="

# Check Docker containers
echo "🐳 Docker Container Status:"
docker compose ps

# Check disk space
echo "💾 Disk Space:"
df -h

# Check memory usage
echo "🧠 Memory Usage:"
free -h

# Check database connectivity
echo "🗄️  Database Connection:"
if pg_isready -h 10.185.1.188 -p 5432 -U sara; then
    echo "✅ Database is accessible"
else
    echo "❌ Database connection failed"
fi

# Check Redis
echo "🔴 Redis Status:"
if redis-cli -h 10.185.1.188 -p 6379 ping; then
    echo "✅ Redis is accessible"
else
    echo "❌ Redis connection failed"
fi

# Check Neo4j
echo "📊 Neo4j Status:"
if curl -s http://10.185.1.188:7474/db/neo4j/tx/commit > /dev/null; then
    echo "✅ Neo4j is accessible"
else
    echo "❌ Neo4j connection failed"
fi

# Check log file sizes
echo "📄 Log File Sizes:"
ls -lh /home/david/jarvis/logs/

echo "=== Health Check Complete ==="
EOF

    chmod +x "$PROJECT_ROOT/scripts/weekly_health_check.sh"
    echo "✅ Health check script created and made executable"
}

# Function to create log rotation script
create_log_rotation_script() {
    echo "🔄 Creating log rotation script..."
    cat > "$PROJECT_ROOT/scripts/rotate_logs.sh" << EOF
#!/bin/bash

# Log Rotation Script for Sara/Jarvis
LOG_DIR="${PROJECT_ROOT}/logs"
BACKUP_DIR="${PROJECT_ROOT}/logs/archive"

echo "=== Log Rotation Started - \$(date) ==="

# Create backup directory
mkdir -p "\$BACKUP_DIR"

# Rotate logs older than 30 days
find "\$LOG_DIR" -name "*.log" -type f -mtime +30 -exec gzip {} \;
find "\$LOG_DIR" -name "*.log.gz" -type f -exec mv {} "\$BACKUP_DIR/" \;

# Clean up very old archives (older than 90 days)
find "\$BACKUP_DIR" -name "*.log.gz" -type f -mtime +90 -delete

echo "=== Log Rotation Complete ==="
EOF

    chmod +x "$PROJECT_ROOT/scripts/rotate_logs.sh"
    echo "✅ Log rotation script created and made executable"
}

# Function to create deployment status script
create_status_script() {
    echo "📊 Creating status check script..."
    cat > "$PROJECT_ROOT/scripts/check_status.sh" << EOF
#!/bin/bash

# Sara/Jarvis Status Check Script
echo "=== Sara/Jarvis System Status ==="
echo "Generated: \$(date)"
echo "Server: ${PROD_SERVER_IP}"
echo

# Docker status
echo "🐳 Docker Services:"
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

echo
echo "🌐 Service URLs:"
echo "Frontend: http://${PROD_SERVER_IP}:${FRONTEND_PORT}"
echo "Backend API: http://${PROD_SERVER_IP}:${BACKEND_PORT}"
echo "Database: ${DATABASE_SERVER_IP}:${DATABASE_PORT}"
echo "Neo4j Browser: http://${PROD_SERVER_IP}:7474"
echo "MinIO Console: http://${PROD_SERVER_IP}:9001"

echo
echo "📋 Recent Cron Jobs:"
crontab -l

echo
echo "📄 Recent Logs:"
tail -n 5 ${PROJECT_ROOT}/logs/*.log 2>/dev/null || echo "No log files found"
EOF

    chmod +x "$PROJECT_ROOT/scripts/check_status.sh"
    echo "✅ Status check script created"
}

# Function to create startup script
create_startup_script() {
    echo "🚀 Creating startup script..."
    cat > "$PROJECT_ROOT/scripts/start_production.sh" << EOF
#!/bin/bash

# Sara/Jarvis Production Startup Script
cd ${PROJECT_ROOT}

echo "🚀 Starting Sara/Jarvis Production Environment..."
echo "Server: ${PROD_SERVER_IP}"
echo "Time: \$(date)"

# Load environment variables
if [ -f .env.production ]; then
    export \$(cat .env.production | grep -v '^#' | xargs)
fi

# Start all services with production configuration
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile graph-neo4j up -d

echo "⏳ Waiting for services to start..."
sleep 30

echo "🔍 Checking service health..."
${PROJECT_ROOT}/scripts/check_status.sh

echo "✅ Production environment started!"
echo "🌐 Frontend: http://${PROD_SERVER_IP}:${FRONTEND_PORT}"
echo "🔧 Backend: http://${PROD_SERVER_IP}:${BACKEND_PORT}"
EOF

    chmod +x "$PROJECT_ROOT/scripts/start_production.sh"
    echo "✅ Startup script created"
}

# Function to create user setup script
create_user_setup_script() {
    echo "👤 Creating user setup script..."
    cat > "$PROJECT_ROOT/scripts/setup_production_user.py" << EOF
#!/usr/bin/env python3
"""
Setup production user for Sara/Jarvis
"""
import os
import sys
import asyncio
import psycopg
from datetime import datetime

# Add the backend app to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

async def setup_user():
    database_url = "postgresql+psycopg://sara:sara123@${DATABASE_SERVER_IP}:${DATABASE_PORT}/sara_hub"
    
    try:
        # Connect to database
        async with await psycopg.AsyncConnection.connect(database_url) as conn:
            async with conn.cursor() as cur:
                # Check if user exists
                await cur.execute(
                    "SELECT id FROM users WHERE email = %s",
                    ("${SARA_USER_EMAIL}",)
                )
                user = await cur.fetchone()
                
                if user:
                    print(f"✅ User ${SARA_USER_EMAIL} already exists with ID: {user[0]}")
                    
                    # Update user details
                    await cur.execute("""
                        UPDATE users 
                        SET updated_at = %s
                        WHERE email = %s
                    """, (datetime.utcnow(), "${SARA_USER_EMAIL}"))
                    
                else:
                    # Create new user
                    from passlib.context import CryptContext
                    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
                    hashed_password = pwd_context.hash("${SARA_USER_PASSWORD}")
                    
                    await cur.execute("""
                        INSERT INTO users (id, email, hashed_password, is_active, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        "${SOLO_USER_ID}",
                        "${SARA_USER_EMAIL}",
                        hashed_password,
                        True,
                        datetime.utcnow(),
                        datetime.utcnow()
                    ))
                    
                    print(f"✅ Created user ${SARA_USER_EMAIL} with ID: ${SOLO_USER_ID}")
                
                await conn.commit()
                print("✅ User setup complete")
                
    except Exception as e:
        print(f"❌ Error setting up user: {e}")
        return False
    
    return True

if __name__ == "__main__":
    asyncio.run(setup_user())
EOF

    chmod +x "$PROJECT_ROOT/scripts/setup_production_user.py"
    echo "✅ User setup script created"
}

# Main deployment function
main() {
    echo "🎯 Starting main deployment process..."
    
    # Setup directories
    setup_directories
    
    # Create configuration files
    create_env_file
    update_docker_compose
    
    # Create utility scripts
    create_health_check_script
    create_log_rotation_script
    create_status_script
    create_startup_script
    create_user_setup_script
    
    # Setup cron jobs
    setup_cron_jobs
    
    echo ""
    echo "🎉 Production deployment setup complete!"
    echo "================================================"
    echo ""
    echo "📋 Next Steps:"
    echo "1. Review the generated configuration files:"
    echo "   - $PROJECT_ROOT/.env.production"
    echo "   - $PROJECT_ROOT/docker-compose.prod.yml"
    echo ""
    echo "2. Start the production environment:"
    echo "   cd $PROJECT_ROOT"
    echo "   ./scripts/start_production.sh"
    echo ""
    echo "3. Setup the production user:"
    echo "   python3 ./scripts/setup_production_user.py"
    echo ""
    echo "4. Check system status:"
    echo "   ./scripts/check_status.sh"
    echo ""
    echo "🌐 Production URLs (after startup):"
    echo "   Frontend: http://$PROD_SERVER_IP:$FRONTEND_PORT"
    echo "   Backend:  http://$PROD_SERVER_IP:$BACKEND_PORT"
    echo "   Neo4j:    http://$PROD_SERVER_IP:7474"
    echo "   MinIO:    http://$PROD_SERVER_IP:9001"
    echo ""
    echo "⏰ Cron Jobs Scheduled:"
    echo "   - Daily vulnerability reports (5:00 AM)"
    echo "   - Daily briefs (6:30 AM)"
    echo "   - Weekly health checks (Sunday 2:00 AM)"
    echo "   - Monthly log rotation (1st of month 1:00 AM)"
    echo ""
    echo "✅ Ready for production deployment!"
}

# Run the main function
main "$@"