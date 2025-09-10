#!/bin/bash

# Jarvis Mode Server Setup Script
# This script automates the deployment of Jarvis (autonomous Sara) on a fresh server
# 
# Usage: sudo ./setup_jarvis_server.sh
# 
# What this script does:
# 1. Installs system dependencies
# 2. Creates database and user
# 3. Sets up Python environment
# 4. Configures services
# 5. Sets up cron jobs
# 6. Configures nginx (optional)

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
JARVIS_USER="jarvis"
JARVIS_GROUP="jarvis"
JARVIS_HOME="/opt/jarvis"
DB_NAME="jarvis_db"
DB_USER="jarvis_user"
DB_PASS=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)  # Generate random password
INSTALL_NGINX=true
DOMAIN=""

# Logging
LOGFILE="/tmp/jarvis_setup.log"

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOGFILE"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}" | tee -a "$LOGFILE"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$LOGFILE"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOGFILE"
}

print_banner() {
    echo -e "${BLUE}"
    echo "=================================================================="
    echo "               JARVIS MODE SETUP SCRIPT"
    echo "        Autonomous Personal AI Hub Deployment"
    echo "=================================================================="
    echo -e "${NC}"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (use sudo)"
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        VERSION=$VERSION_ID
    else
        error "Cannot detect OS version"
    fi
    
    log "Detected OS: $OS $VERSION"
}

get_user_input() {
    echo -e "${YELLOW}=== Configuration Setup ===${NC}"
    
    # Domain configuration
    read -p "Enter your domain name (leave empty for localhost): " DOMAIN
    if [[ -z "$DOMAIN" ]]; then
        DOMAIN="localhost"
        INSTALL_NGINX=false
        warn "No domain specified, nginx setup will be skipped"
    fi
    
    # LLM configuration
    read -p "Enter your LLM endpoint URL (e.g., http://localhost:11434/v1): " LLM_URL
    read -p "Enter your LLM model name (e.g., gpt-oss:120b): " LLM_MODEL
    read -p "Enter your embedding endpoint (e.g., http://localhost:11434): " EMBEDDING_URL
    
    # Confirm settings
    echo -e "\n${BLUE}Configuration Summary:${NC}"
    echo "Domain: $DOMAIN"
    echo "LLM URL: $LLM_URL"
    echo "LLM Model: $LLM_MODEL"
    echo "Embedding URL: $EMBEDDING_URL"
    echo "Database Password: $DB_PASS"
    echo ""
    read -p "Continue with this configuration? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error "Setup cancelled by user"
    fi
}

install_dependencies() {
    log "Installing system dependencies..."
    
    case "$OS" in
        *"Ubuntu"*|*"Debian"*)
            apt update
            apt install -y \
                python3 python3-pip python3-venv \
                nodejs npm \
                postgresql-14 postgresql-14-pgvector \
                redis-server \
                nginx \
                git curl wget \
                software-properties-common \
                certbot python3-certbot-nginx \
                cron rsyslog
            ;;
        *"CentOS"*|*"Red Hat"*|*"Rocky"*|*"AlmaLinux"*)
            dnf update -y
            dnf install -y \
                python3 python3-pip \
                nodejs npm \
                postgresql-server postgresql-contrib \
                redis \
                nginx \
                git curl wget \
                certbot python3-certbot-nginx \
                cronie
            
            # Initialize PostgreSQL on RHEL-based systems
            postgresql-setup --initdb || true
            ;;
        *)
            error "Unsupported operating system: $OS"
            ;;
    esac
    
    log "System dependencies installed successfully"
}

create_user() {
    log "Creating Jarvis system user..."
    
    if ! id "$JARVIS_USER" &>/dev/null; then
        useradd -r -m -d "$JARVIS_HOME" -s /bin/bash "$JARVIS_USER"
        log "Created user: $JARVIS_USER"
    else
        warn "User $JARVIS_USER already exists"
    fi
    
    # Ensure home directory exists and has correct permissions
    mkdir -p "$JARVIS_HOME"
    chown -R "$JARVIS_USER:$JARVIS_GROUP" "$JARVIS_HOME"
}

setup_database() {
    log "Setting up PostgreSQL database..."
    
    # Start PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    
    # Create database and user
    sudo -u postgres psql << EOF
CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';
CREATE DATABASE $DB_NAME OWNER $DB_USER;
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
\c $DB_NAME;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF
    
    log "Database setup completed"
    log "Database: $DB_NAME"
    log "User: $DB_USER"
    log "Password: $DB_PASS"
}

setup_python_env() {
    log "Setting up Python environment..."
    
    # Create virtual environment
    sudo -u "$JARVIS_USER" python3 -m venv "$JARVIS_HOME/venv"
    
    # Install Python dependencies (assuming requirements.txt exists)
    if [[ -f "$JARVIS_HOME/backend/requirements.txt" ]]; then
        sudo -u "$JARVIS_USER" "$JARVIS_HOME/venv/bin/pip" install -r "$JARVIS_HOME/backend/requirements.txt"
    else
        warn "requirements.txt not found, installing basic dependencies"
        sudo -u "$JARVIS_USER" "$JARVIS_HOME/venv/bin/pip" install \
            fastapi uvicorn sqlalchemy psycopg2-binary redis python-multipart \
            pydantic python-jose cryptography passlib aiofiles httpx
    fi
    
    log "Python environment setup completed"
}

create_env_file() {
    log "Creating environment configuration..."
    
    cat > "$JARVIS_HOME/.env" << EOF
# Jarvis Mode Configuration
JARVIS_MODE=true
PRIVACY_STRICT=true
SOLO_USER_ID=1

# Database Configuration
DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
REDIS_URL="redis://localhost:6379/0"

# LLM Configuration
OPENAI_BASE_URL=$LLM_URL
OPENAI_MODEL=$LLM_MODEL
OPENAI_API_KEY=dummy

# Embedding Configuration
EMBEDDING_BASE_URL=$EMBEDDING_URL
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Jarvis Behavior
NUDGE_WINDOW=08:00-20:00
NUDGE_BATCH_INTERVAL_MIN=30
NUDGE_MAX_PER_DAY=8
DREAM_AT=02:30
RESEARCH_MAX_MINUTES=8

# Application Settings
ASSISTANT_NAME=Jarvis
DOMAIN=$DOMAIN
HOST=0.0.0.0
PORT=8000

# CORS Configuration
CORS_ORIGINS=http://localhost:3000,http://$DOMAIN:3000,https://$DOMAIN

# Notifications
NTFY_SERVER_URL=http://localhost:8889
NTFY_ENABLED=true
NTFY_TIMERS_TOPIC=jarvis
NTFY_REMINDERS_TOPIC=jarvis
NTFY_SYSTEM_TOPIC=jarvis

# Logging
LOG_LEVEL=INFO
EOF
    
    chown "$JARVIS_USER:$JARVIS_GROUP" "$JARVIS_HOME/.env"
    chmod 600 "$JARVIS_HOME/.env"
    
    log "Environment file created at $JARVIS_HOME/.env"
}

run_migrations() {
    log "Running database migrations..."
    
    cd "$JARVIS_HOME"
    
    # Run Jarvis table migrations
    if [[ -f "$JARVIS_HOME/backend/migrate_jarvis_tables.py" ]]; then
        sudo -u "$JARVIS_USER" bash -c "
            source $JARVIS_HOME/venv/bin/activate && 
            cd $JARVIS_HOME/backend && 
            DATABASE_URL='postgresql+psycopg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME' python3 migrate_jarvis_tables.py
        "
    else
        warn "Jarvis migration script not found"
    fi
    
    # Create solo user
    if [[ -f "$JARVIS_HOME/scripts/setup_solo_user.py" ]]; then
        sudo -u "$JARVIS_USER" bash -c "
            source $JARVIS_HOME/venv/bin/activate && 
            DATABASE_URL='postgresql+psycopg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME' python3 $JARVIS_HOME/scripts/setup_solo_user.py
        "
    else
        warn "Solo user setup script not found"
    fi
    
    log "Database migrations completed"
}

setup_frontend() {
    log "Setting up frontend..."
    
    if [[ -d "$JARVIS_HOME/frontend" ]]; then
        cd "$JARVIS_HOME/frontend"
        
        # Install Node.js dependencies
        sudo -u "$JARVIS_USER" npm install
        
        # Build frontend
        sudo -u "$JARVIS_USER" npm run build
        
        log "Frontend built successfully"
    else
        warn "Frontend directory not found, skipping frontend setup"
    fi
}

create_systemd_services() {
    log "Creating systemd services..."
    
    # Backend service
    cat > "/etc/systemd/system/jarvis-backend.service" << EOF
[Unit]
Description=Jarvis Backend API
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=$JARVIS_USER
Group=$JARVIS_GROUP
WorkingDirectory=$JARVIS_HOME/backend
Environment=PATH=$JARVIS_HOME/venv/bin
EnvironmentFile=$JARVIS_HOME/.env
ExecStart=$JARVIS_HOME/venv/bin/python app/main_simple.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # Frontend service (if frontend exists)
    if [[ -d "$JARVIS_HOME/frontend" ]]; then
        cat > "/etc/systemd/system/jarvis-frontend.service" << EOF
[Unit]
Description=Jarvis Frontend Server
After=network.target

[Service]
Type=simple
User=$JARVIS_USER
Group=$JARVIS_GROUP
WorkingDirectory=$JARVIS_HOME/frontend
ExecStart=/usr/bin/npx serve -s dist -l 3000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    fi
    
    # Reload systemd
    systemctl daemon-reload
    
    log "Systemd services created"
}

setup_nginx() {
    if [[ "$INSTALL_NGINX" != "true" || "$DOMAIN" == "localhost" ]]; then
        warn "Skipping nginx setup"
        return
    fi
    
    log "Setting up nginx configuration..."
    
    cat > "/etc/nginx/sites-available/jarvis" << EOF
server {
    listen 80;
    server_name $DOMAIN;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    
    # API Backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
    
    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_set_header Host \$host;
        access_log off;
    }
    
    # Frontend
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    
    # Enable site
    ln -sf "/etc/nginx/sites-available/jarvis" "/etc/nginx/sites-enabled/"
    rm -f "/etc/nginx/sites-enabled/default"
    
    # Test nginx configuration
    nginx -t || error "Nginx configuration test failed"
    
    # Start nginx
    systemctl start nginx
    systemctl enable nginx
    
    log "Nginx configured successfully"
}

setup_cron_jobs() {
    log "Setting up cron jobs..."
    
    # Create logs directory
    mkdir -p "$JARVIS_HOME/logs"
    chown "$JARVIS_USER:$JARVIS_GROUP" "$JARVIS_HOME/logs"
    
    # Create crontab for jarvis user
    cat > "/tmp/jarvis_crontab" << EOF
# Jarvis Daily Brief Generation (6:30 AM)
30 6 * * * cd $JARVIS_HOME && source $JARVIS_HOME/.env && $JARVIS_HOME/venv/bin/python $JARVIS_HOME/scripts/daily_brief_simple.py >> $JARVIS_HOME/logs/daily_brief.log 2>&1

# Log cleanup (weekly, Sunday 3 AM)
0 3 * * 0 find $JARVIS_HOME/logs -name "*.log" -mtime +7 -delete

# Health check (every 5 minutes)
*/5 * * * * curl -f http://localhost:8000/health >/dev/null 2>&1 || echo "\$(date): Jarvis health check failed" >> $JARVIS_HOME/logs/health.log
EOF
    
    # Install crontab for jarvis user
    sudo -u "$JARVIS_USER" crontab "/tmp/jarvis_crontab"
    rm "/tmp/jarvis_crontab"
    
    # Ensure cron service is running
    systemctl start cron || systemctl start crond
    systemctl enable cron || systemctl enable crond
    
    log "Cron jobs configured"
}

setup_firewall() {
    log "Configuring firewall..."
    
    if command -v ufw >/dev/null 2>&1; then
        # Ubuntu/Debian firewall
        ufw --force enable
        ufw default deny incoming
        ufw default allow outgoing
        ufw allow ssh
        ufw allow 80/tcp
        ufw allow 443/tcp
        
        # Deny direct access to backend and frontend ports
        ufw deny 8000/tcp
        ufw deny 3000/tcp
        
        log "UFW firewall configured"
    elif command -v firewall-cmd >/dev/null 2>&1; then
        # RHEL/CentOS firewall
        systemctl start firewalld
        systemctl enable firewalld
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --reload
        
        log "Firewalld configured"
    else
        warn "No firewall utility found, skipping firewall setup"
    fi
}

start_services() {
    log "Starting Jarvis services..."
    
    # Start and enable backend
    systemctl start jarvis-backend
    systemctl enable jarvis-backend
    
    # Start and enable frontend (if exists)
    if [[ -f "/etc/systemd/system/jarvis-frontend.service" ]]; then
        systemctl start jarvis-frontend
        systemctl enable jarvis-frontend
    fi
    
    # Start supporting services
    systemctl start redis
    systemctl enable redis
    
    log "All services started and enabled"
}

run_health_check() {
    log "Running health checks..."
    
    sleep 5  # Give services time to start
    
    # Check backend
    if curl -f http://localhost:8000/health >/dev/null 2>&1; then
        log "✓ Backend health check passed"
    else
        error "✗ Backend health check failed"
    fi
    
    # Check frontend (if exists)
    if [[ -f "/etc/systemd/system/jarvis-frontend.service" ]]; then
        if curl -f http://localhost:3000 >/dev/null 2>&1; then
            log "✓ Frontend health check passed"
        else
            warn "✗ Frontend health check failed"
        fi
    fi
    
    # Check database
    if sudo -u postgres psql -d "$DB_NAME" -c "SELECT 1;" >/dev/null 2>&1; then
        log "✓ Database health check passed"
    else
        warn "✗ Database health check failed"
    fi
    
    log "Health checks completed"
}

print_summary() {
    echo -e "\n${GREEN}=================================================================="
    echo "                    SETUP COMPLETED SUCCESSFULLY!"
    echo "==================================================================${NC}"
    echo
    echo -e "${BLUE}📋 Configuration Summary:${NC}"
    echo "  • Installation Path: $JARVIS_HOME"
    echo "  • Database: $DB_NAME"
    echo "  • Database User: $DB_USER"
    echo "  • Database Password: $DB_PASS"
    echo "  • Domain: $DOMAIN"
    echo
    echo -e "${BLUE}🌐 Service URLs:${NC}"
    if [[ "$DOMAIN" != "localhost" ]]; then
        echo "  • Frontend: http://$DOMAIN"
        echo "  • API: http://$DOMAIN/api"
        echo "  • Health Check: http://$DOMAIN/health"
    else
        echo "  • Frontend: http://localhost:3000"
        echo "  • API: http://localhost:8000"
        echo "  • Health Check: http://localhost:8000/health"
    fi
    echo
    echo -e "${BLUE}📊 Service Status:${NC}"
    systemctl is-active jarvis-backend && echo "  • Backend: Running" || echo "  • Backend: Stopped"
    [[ -f "/etc/systemd/system/jarvis-frontend.service" ]] && systemctl is-active jarvis-frontend && echo "  • Frontend: Running" || echo "  • Frontend: Not installed"
    systemctl is-active nginx && echo "  • Nginx: Running" || echo "  • Nginx: Stopped"
    systemctl is-active postgresql && echo "  • Database: Running" || echo "  • Database: Stopped"
    echo
    echo -e "${BLUE}📁 Important Files:${NC}"
    echo "  • Configuration: $JARVIS_HOME/.env"
    echo "  • Logs: $JARVIS_HOME/logs/"
    echo "  • Setup Log: $LOGFILE"
    echo
    echo -e "${BLUE}🔧 Management Commands:${NC}"
    echo "  • Start services: sudo systemctl start jarvis-backend jarvis-frontend"
    echo "  • Stop services: sudo systemctl stop jarvis-backend jarvis-frontend"
    echo "  • View logs: sudo journalctl -u jarvis-backend -f"
    echo "  • Check status: sudo systemctl status jarvis-backend"
    echo
    echo -e "${BLUE}⚡ Next Steps:${NC}"
    echo "  1. Review configuration in $JARVIS_HOME/.env"
    echo "  2. Test the web interface"
    echo "  3. Check daily brief generation tomorrow morning"
    if [[ "$DOMAIN" != "localhost" ]]; then
        echo "  4. Set up SSL: sudo certbot --nginx -d $DOMAIN"
    fi
    echo
    echo -e "${GREEN}🎉 Your Jarvis AI is now operational!${NC}"
    echo
}

# Main execution
main() {
    print_banner
    check_root
    detect_os
    get_user_input
    
    log "Starting Jarvis setup process..."
    
    install_dependencies
    create_user
    setup_database
    setup_python_env
    create_env_file
    run_migrations
    setup_frontend
    create_systemd_services
    setup_nginx
    setup_cron_jobs
    setup_firewall
    start_services
    run_health_check
    
    print_summary
}

# Run main function
main "$@"