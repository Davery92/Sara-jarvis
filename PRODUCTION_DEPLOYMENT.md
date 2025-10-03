# Sara/Jarvis Production Deployment Guide

## Quick Start for 10.185.1.188

### 1. Copy Project to Production Server
```bash
# On your local machine or from the current server
rsync -avz --exclude 'node_modules' --exclude '.git' /home/david/jarvis/ user@10.185.1.188:/home/david/jarvis/
```

### 2. Run the Single Deployment Script
```bash
# On the production server (10.185.1.188)
cd /home/david/jarvis
./scripts/deploy_production.sh
```

This single script will:
- ✅ Create all required directories
- ✅ Generate production environment configuration
- ✅ Create production docker-compose setup
- ✅ Install all cron jobs (vulnerability reports, daily briefs, health checks)
- ✅ Create utility scripts for monitoring and maintenance

### 3. Start Production Environment
```bash
# Start all services
./scripts/start_production.sh

# Setup the user account
python3 ./scripts/setup_production_user.py

# Check everything is running
./scripts/check_status.sh
```

## What Gets Automatically Configured

### 🐳 Docker Services
- **Frontend**: http://10.185.1.188:3000
- **Backend**: http://10.185.1.188:8000  
- **Database**: PostgreSQL with pgvector on 10.185.1.188:5432
- **Neo4j**: Graph database on 10.185.1.188:7474 (browser) and 7687 (bolt)
- **Redis**: Cache on 10.185.1.188:6379
- **MinIO**: Object storage on 10.185.1.188:9000 (API) and 9001 (console)

### ⏰ Automated Cron Jobs
- **5:00 AM Daily**: Vulnerability intelligence reports
- **6:30 AM Daily**: Personal daily briefs
- **2:00 AM Sundays**: System health checks
- **1:00 AM Monthly**: Log file rotation and cleanup

### 📁 Directory Structure
```
/home/david/jarvis/
├── logs/                    # All application logs
├── backups/                 # Crontab and data backups
├── data/                    # Application data
├── scripts/                 # Deployment and maintenance scripts
├── .env.production         # Production environment variables
└── docker-compose.prod.yml # Production Docker configuration
```

### 🔧 Utility Scripts Created
- `scripts/start_production.sh` - Start all services
- `scripts/check_status.sh` - Check system health
- `scripts/weekly_health_check.sh` - Automated health monitoring
- `scripts/rotate_logs.sh` - Log rotation and cleanup
- `scripts/setup_production_user.py` - User account setup

## Environment Configuration

The deployment script automatically configures:

### Database & Storage
- PostgreSQL with pgvector extension
- Neo4j graph database for knowledge garden
- Redis for caching and session storage
- MinIO for document storage

### AI & ML Services  
- OpenAI-compatible API endpoint (100.104.68.115:11434)
- Embedding service for semantic search
- Model configurations (gpt-oss:120b, bge-m3)

### Security & Authentication
- JWT-based authentication with HTTP-only cookies
- CORS configuration for production domain
- Secure password hashing and user management

### Monitoring & Automation
- Vulnerability intelligence monitoring
- Daily brief generation
- Health checks and log rotation
- NTFY notifications for critical alerts

## Manual Configuration (If Needed)

### Update IP Addresses
If you need to change IP addresses, edit:
```bash
nano .env.production
```

### Modify Cron Schedule
```bash
crontab -e
```

### Check Logs
```bash
# All logs are in /home/david/jarvis/logs/
tail -f logs/vulnerability_reports.log
tail -f logs/daily_brief.log
tail -f logs/health_check.log
```

### Restart Services
```bash
cd /home/david/jarvis
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart
```

## Troubleshooting

### Check Service Status
```bash
./scripts/check_status.sh
```

### View Service Logs
```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db
```

### Database Connection Issues
```bash
# Test database connectivity
pg_isready -h 10.185.1.188 -p 5432 -U sara
```

### Reset User Credentials
```bash
python3 scripts/setup_production_user.py
```

## Production URLs

After successful deployment:

- **Main Application**: http://10.185.1.188:3000
- **API Documentation**: http://10.185.1.188:8000/docs
- **Neo4j Browser**: http://10.185.1.188:7474
- **MinIO Console**: http://10.185.1.188:9001
- **Redis**: 10.185.1.188:6379

## Security Notes

- Change the JWT secret in `.env.production` for production
- Update MinIO root password (`MINIO_ROOT_PASSWORD`)
- Consider setting up SSL/TLS termination with nginx
- Ensure firewall rules are properly configured
- Regular security updates for Docker images

## Support

All configuration is automated through the deployment script. If you encounter issues:

1. Check logs in `/home/david/jarvis/logs/`
2. Run `./scripts/check_status.sh` for system overview
3. Verify environment variables in `.env.production`
4. Ensure all required ports are accessible