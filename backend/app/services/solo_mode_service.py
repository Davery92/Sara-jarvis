"""
Solo Mode Service - Manages single-user Jarvis configuration

This service handles:
- Solo user mode detection and configuration
- Simplified authentication for single-user setups
- Environment-based Jarvis mode settings
"""

import os
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SoloModeService:
    """Service for managing solo user mode"""
    
    def __init__(self):
        # Load configuration from environment
        self.enabled = os.getenv("JARVIS_MODE", "false").lower() == "true"
        self.solo_user_id = os.getenv("SOLO_USER_ID", "1")
        self.privacy_strict = os.getenv("PRIVACY_STRICT", "false").lower() == "true"
        
        logger.info(f"Solo mode: {'enabled' if self.enabled else 'disabled'}")
        if self.enabled:
            logger.info(f"Solo user ID: {self.solo_user_id}")
    
    def is_solo_mode(self) -> bool:
        """Check if Jarvis is running in solo mode"""
        return self.enabled
    
    def get_solo_user_id(self) -> int:
        """Get the configured solo user ID"""
        return self.solo_user_id
    
    def get_or_create_solo_user(self, db: Session):
        """Get or create the solo user account"""
        
        if not self.enabled:
            raise ValueError("Solo mode is not enabled")
        
        # For now, just return a simple dict since we'll implement this later
        # This is a placeholder for solo mode setup
        logger.info("Solo mode user management not yet implemented")
        return {
            "id": str(self.solo_user_id),
            "email": "owner@jarvis.local",
            "is_owner": True
        }
    
    def should_skip_auth(self) -> bool:
        """Check if authentication should be bypassed in solo mode"""
        return self.enabled
    
    def get_default_user(self, db: Session) -> Optional[dict]:
        """Get the default user for solo mode requests"""
        
        if not self.enabled:
            return None
        
        return self.get_or_create_solo_user(db)
    
    def get_jarvis_config(self) -> dict:
        """Get Jarvis-specific configuration"""
        
        return {
            "mode": "jarvis" if self.enabled else "sara",
            "solo_mode": self.enabled,
            "privacy_strict": self.privacy_strict,
            "user_id": self.solo_user_id if self.enabled else None,
            "features": {
                "inbox": self.enabled,
                "daily_brief": self.enabled,
                "autonomous_tasks": self.enabled,
                "proactive_monitors": self.enabled
            }
        }
    
    def validate_solo_request(self, user_id: Optional[int] = None) -> int:
        """
        Validate and normalize user ID for solo mode requests
        
        In solo mode, all requests are assumed to be for the solo user,
        regardless of what user_id is provided.
        """
        
        if not self.enabled:
            if user_id is None:
                raise ValueError("User ID is required when not in solo mode")
            return user_id
        
        # In solo mode, always use the configured solo user ID
        return self.solo_user_id


# Global service instance
solo_mode_service = SoloModeService()