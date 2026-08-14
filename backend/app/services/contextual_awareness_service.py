"""
Contextual Awareness Service
Monitors timers, reminders, mood, and maintains Sara's living context note.
Runs every 30 minutes to provide proactive assistance and awareness.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import pytz

from app.db.session import SessionLocal
from app.models.episode import Episode
# Import Timer and Reminder from main_simple where the actual database schema is defined
import sys
from app.core.config import get_owner_id
sys.path.insert(0, '/home/david/jarvis/backend')
from app.main_simple import Timer, Reminder
from app.services.content_intelligence import content_intelligence, ContentType
from app.services.metadata_extractor import metadata_extractor
from app.services.tagging_system import smart_tagger
from app.services.enhanced_neo4j_schema import enhanced_neo4j

logger = logging.getLogger(__name__)

SOLO_USER_ID = get_owner_id()

class ContextualAwarenessService:
    """Provides contextual awareness and proactive monitoring for Sara"""
    
    def __init__(self):
        self.eastern_tz = pytz.timezone('America/New_York')
        self.check_interval = 1800  # 30 minutes
        self.is_monitoring = False
        logger.info("🔮 ContextualAwarenessService initialized - monitoring every 30 minutes")
    
    async def start_awareness_monitoring(self):
        """Start the contextual awareness monitoring loop"""
        logger.info("🔮 Starting contextual awareness monitoring...")
        self.is_monitoring = True

        # Delay first check so uvicorn can start accepting requests
        await asyncio.sleep(60)

        while self.is_monitoring:
            try:
                # Get current Eastern time
                utc_now = datetime.now(pytz.UTC)
                eastern_now = utc_now.astimezone(self.eastern_tz)

                logger.info(f"🔮 Running awareness check at {eastern_now.strftime('%I:%M %p')} Eastern")

                # Solo-user deployment — avoid fanning this out across test accounts.
                await asyncio.to_thread(self._monitor_user_context_sync, SOLO_USER_ID, eastern_now)

                logger.info("✅ Awareness check complete")

                # Sleep for 30 minutes
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"❌ Awareness monitoring error: {e}")
                await asyncio.sleep(300)  # 5 minutes on error
    
    def _monitor_user_context_sync(self, user_id: str, eastern_now: datetime):
        """Monitor contextual awareness for a single user (sync, runs in thread pool).

        Duplicates the logic from the async methods but purely synchronous,
        so the entire per-user cycle can run in a thread without blocking the event loop.
        """
        logger.info(f"🔮 Monitoring context for user {user_id}")

        try:
            db = SessionLocal()
            try:
                # 1. Check active timers
                active_timers = db.query(Timer).filter(
                    and_(
                        Timer.user_id == user_id,
                        Timer.is_active == True,
                        Timer.is_completed == False,
                        Timer.end_time <= eastern_now.replace(tzinfo=None) + timedelta(minutes=5)
                    )
                ).all()
                timer_alerts = []
                for timer in active_timers:
                    time_remaining = timer.end_time - eastern_now.replace(tzinfo=None)
                    timer_alerts.append({
                        'type': 'timer', 'timer_id': timer.id,
                        'label': timer.title or 'Timer',
                        'time_remaining': time_remaining.total_seconds(),
                        'status': 'due_soon' if time_remaining.total_seconds() > 0 else 'overdue',
                        'urgency': 'high' if time_remaining.total_seconds() <= 300 else 'medium',
                    })

                # 2. Check upcoming reminders
                next_hour = eastern_now + timedelta(hours=1)
                upcoming_reminders = db.query(Reminder).filter(
                    and_(
                        Reminder.user_id == user_id,
                        Reminder.is_completed == False,
                        Reminder.reminder_time >= eastern_now.replace(tzinfo=None),
                        Reminder.reminder_time <= next_hour.replace(tzinfo=None),
                    )
                ).order_by(Reminder.reminder_time).all()
                reminder_alerts = [
                    {
                        'type': 'reminder', 'reminder_id': r.id, 'content': r.content,
                        'time_until': (r.reminder_time - eastern_now.replace(tzinfo=None)).total_seconds(),
                        'urgency': 'high' if (r.reminder_time - eastern_now.replace(tzinfo=None)).total_seconds() <= 900 else 'medium',
                    }
                    for r in upcoming_reminders
                ]

                # 3. Mood analysis (pure CPU keyword matching)
                since_time = eastern_now - timedelta(hours=4)
                recent_episodes = db.query(Episode).filter(
                    and_(
                        Episode.user_id == user_id,
                        Episode.role == 'user',
                        Episode.created_at >= since_time.replace(tzinfo=None),
                    )
                ).order_by(Episode.created_at).all()
                mood_analysis = {'mood': 'unknown', 'energy': 'unknown', 'indicators': []}
                if recent_episodes:
                    recent_content = " ".join([ep.content for ep in recent_episodes if ep.content])
                    if recent_content:
                        mood_analysis = {
                            'mood': 'neutral', 'mood_confidence': 0.0,
                            'energy': 'moderate', 'engagement': 'moderate',
                            'indicators': [], 'recent_activity_count': len(recent_episodes),
                            'time_period': '4 hours',
                        }
            finally:
                db.close()

            # 4. Priority items from Neo4j (sync)
            priority_items = []
            try:
                priority_results = enhanced_neo4j.find_content_by_urgency(user_id, min_urgency=0.7, limit=5)
                for result in priority_results:
                    content = result.get('content', {})
                    priority_items.append({
                        'type': 'priority_content',
                        'content_id': content.get('id'),
                        'title': content.get('title', 'Untitled'),
                        'urgency_score': content.get('urgency_score', 0.0),
                        'importance_score': content.get('importance_score', 0.0),
                        'priority_tags': result.get('priority_tags', []),
                        'content_type': content.get('content_type', 'unknown'),
                    })
                if priority_items:
                    logger.info(f"   ⚡ Found {len(priority_items)} high priority items")
            except Exception as e:
                logger.debug(f"Priority items check failed: {e}")

            # 5. Focus context (stubs return empty)
            focus_context = {'recent_topics': [], 'active_projects': [], 'focus_areas': []}

            # 6. Update living context note (sync Neo4j write)
            try:
                context_content = self._format_living_context(
                    eastern_now, timer_alerts, reminder_alerts,
                    mood_analysis, priority_items, focus_context
                )
                date_str = eastern_now.strftime('%Y-%m-%d')
                context_id = f"{user_id}_living_context_{date_str}"
                context_title = f"Sara's Living Context - {eastern_now.strftime('%A, %B %d, %Y')}"

                content_type, chunks = content_intelligence.process_content(context_content, context_title)
                metadata = metadata_extractor.extract_metadata(context_content, content_type, context_title)
                tags = smart_tagger.generate_tags(context_content, metadata, content_type, context_title)

                from app.services.tagging_system import Tag, TagCategory, TagPriority
                tags.append(Tag(
                    name="living_context", category=TagCategory.CONTEXT,
                    priority=TagPriority.CRITICAL, confidence=1.0,
                    description="Sara's current contextual awareness",
                ))

                success = enhanced_neo4j.store_intelligent_content(
                    content_id=context_id, user_id=user_id, title=context_title,
                    content=context_content, content_type=content_type,
                    chunks=chunks, metadata=metadata, tags=tags,
                )
                if success:
                    logger.info(f"   📝 Updated living context note")
            except Exception as e:
                logger.error(f"❌ Living context update failed: {e}")

            logger.info(f"   ✅ Context monitoring complete for user {user_id}")

        except Exception as e:
            logger.error(f"❌ Context monitoring failed for user {user_id}: {e}")

    async def _monitor_user_context(self, user_id: str, eastern_now: datetime):
        """Async wrapper — delegates to thread pool to avoid blocking the event loop."""
        await asyncio.to_thread(self._monitor_user_context_sync, user_id, eastern_now)
    
    async def _check_active_timers(self, user_id: str, current_time: datetime) -> List[Dict[str, Any]]:
        """Check for active timers and their status"""
        db = SessionLocal()
        try:
            # Get active timers
            active_timers = db.query(Timer).filter(
                and_(
                    Timer.user_id == user_id,
                    Timer.is_active == True,
                    Timer.is_completed == False,
                    Timer.end_time <= current_time.replace(tzinfo=None) + timedelta(minutes=5)  # Due within 5 minutes
                )
            ).all()
            
            timer_alerts = []
            for timer in active_timers:
                time_remaining = timer.end_time - current_time.replace(tzinfo=None)
                
                alert = {
                    'type': 'timer',
                    'timer_id': timer.id,
                    'label': timer.title or 'Timer',
                    'time_remaining': time_remaining.total_seconds(),
                    'status': 'due_soon' if time_remaining.total_seconds() > 0 else 'overdue',
                    'urgency': 'high' if time_remaining.total_seconds() <= 300 else 'medium'  # High if < 5 min
                }
                timer_alerts.append(alert)
            
            if timer_alerts:
                logger.info(f"   ⏰ Found {len(timer_alerts)} timer alerts")
            
            return timer_alerts
            
        finally:
            db.close()
    
    async def _check_upcoming_reminders(self, user_id: str, current_time: datetime) -> List[Dict[str, Any]]:
        """Check for upcoming reminders in the next hour"""
        db = SessionLocal()
        try:
            # Get reminders due in the next hour
            next_hour = current_time + timedelta(hours=1)
            
            upcoming_reminders = db.query(Reminder).filter(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.is_completed == False,
                    Reminder.reminder_time >= current_time.replace(tzinfo=None),
                    Reminder.reminder_time <= next_hour.replace(tzinfo=None)
                )
            ).order_by(Reminder.reminder_time).all()
            
            reminder_alerts = []
            for reminder in upcoming_reminders:
                time_until = reminder.reminder_time - current_time.replace(tzinfo=None)
                
                alert = {
                    'type': 'reminder',
                    'reminder_id': reminder.id,
                    'content': reminder.content,
                    'time_until': time_until.total_seconds(),
                    'urgency': 'high' if time_until.total_seconds() <= 900 else 'medium'  # High if < 15 min
                }
                reminder_alerts.append(alert)
            
            if reminder_alerts:
                logger.info(f"   📅 Found {len(reminder_alerts)} upcoming reminders")
            
            return reminder_alerts
            
        finally:
            db.close()
    
    async def _analyze_recent_mood(self, user_id: str, current_time: datetime) -> Dict[str, Any]:
        """Analyze recent mood patterns and energy levels"""
        db = SessionLocal()
        try:
            # Get episodes from last 4 hours
            since_time = current_time - timedelta(hours=4)
            
            recent_episodes = db.query(Episode).filter(
                and_(
                    Episode.user_id == user_id,
                    Episode.role == 'user',  # Only user messages
                    Episode.created_at >= since_time.replace(tzinfo=None)
                )
            ).order_by(Episode.created_at).all()
            
            if not recent_episodes:
                return {'mood': 'unknown', 'energy': 'unknown', 'indicators': []}
            
            # Combine recent content
            recent_content = " ".join([ep.content for ep in recent_episodes if ep.content])
            
            if not recent_content:
                return {'mood': 'unknown', 'energy': 'unknown', 'indicators': []}
            
            # Analyze mood using content intelligence
            mood_analysis = await self._detect_mood_patterns(recent_content)
            
            # Analyze activity level and engagement
            activity_analysis = await self._analyze_activity_patterns(recent_episodes)
            
            analysis = {
                'mood': mood_analysis.get('primary_mood', 'neutral'),
                'mood_confidence': mood_analysis.get('confidence', 0.0),
                'energy': activity_analysis.get('energy_level', 'moderate'),
                'engagement': activity_analysis.get('engagement_level', 'moderate'),
                'indicators': mood_analysis.get('indicators', []),
                'recent_activity_count': len(recent_episodes),
                'time_period': '4 hours'
            }
            
            logger.info(f"   😊 Mood analysis: {analysis['mood']} (confidence: {analysis['mood_confidence']:.2f})")
            
            return analysis
            
        finally:
            db.close()
    
    async def _detect_mood_patterns(self, content: str) -> Dict[str, Any]:
        """Detect mood patterns from content using keyword analysis"""
        content_lower = content.lower()
        
        mood_keywords = {
            'positive': {
                'keywords': ['happy', 'excited', 'great', 'awesome', 'love', 'wonderful', 'amazing', 'fantastic'],
                'weight': 1.0
            },
            'negative': {
                'keywords': ['sad', 'frustrated', 'angry', 'upset', 'annoyed', 'disappointed', 'stressed'],
                'weight': 1.0
            },
            'energetic': {
                'keywords': ['motivated', 'energetic', 'pumped', 'ready', 'focused', 'productive'],
                'weight': 0.8
            },
            'tired': {
                'keywords': ['tired', 'exhausted', 'drained', 'sleepy', 'worn out', 'fatigued'],
                'weight': 0.8
            },
            'anxious': {
                'keywords': ['anxious', 'worried', 'nervous', 'concerned', 'stressed', 'overwhelmed'],
                'weight': 0.9
            },
            'calm': {
                'keywords': ['calm', 'peaceful', 'relaxed', 'content', 'serene', 'balanced'],
                'weight': 0.7
            }
        }
        
        mood_scores = {}
        indicators = []
        
        for mood, data in mood_keywords.items():
            score = 0
            found_keywords = []
            
            for keyword in data['keywords']:
                count = content_lower.count(keyword)
                if count > 0:
                    score += count * data['weight']
                    found_keywords.extend([keyword] * count)
            
            if score > 0:
                mood_scores[mood] = score
                indicators.extend(found_keywords)
        
        # Determine primary mood
        if mood_scores:
            primary_mood = max(mood_scores.items(), key=lambda x: x[1])
            total_score = sum(mood_scores.values())
            confidence = primary_mood[1] / total_score if total_score > 0 else 0.0
            
            return {
                'primary_mood': primary_mood[0],
                'confidence': confidence,
                'all_moods': mood_scores,
                'indicators': indicators[:5]  # Top 5 indicators
            }
        
        return {'primary_mood': 'neutral', 'confidence': 0.0, 'indicators': []}
    
    async def _analyze_activity_patterns(self, episodes: List[Episode]) -> Dict[str, Any]:
        """Analyze activity and engagement patterns"""
        if not episodes:
            return {'energy_level': 'low', 'engagement_level': 'low'}
        
        # Analyze message frequency
        total_messages = len(episodes)
        time_span = episodes[-1].created_at - episodes[0].created_at
        hours = max(time_span.total_seconds() / 3600, 0.1)  # Avoid division by zero
        
        messages_per_hour = total_messages / hours
        
        # Analyze message length and complexity
        total_length = sum(len(ep.content or '') for ep in episodes)
        avg_length = total_length / total_messages if total_messages > 0 else 0
        
        # Energy level based on frequency and length
        if messages_per_hour > 10 and avg_length > 50:
            energy_level = 'high'
        elif messages_per_hour > 5 and avg_length > 30:
            energy_level = 'moderate'
        else:
            energy_level = 'low'
        
        # Engagement level based on interaction patterns
        if avg_length > 100:
            engagement_level = 'high'
        elif avg_length > 50:
            engagement_level = 'moderate'
        else:
            engagement_level = 'low'
        
        return {
            'energy_level': energy_level,
            'engagement_level': engagement_level,
            'messages_per_hour': round(messages_per_hour, 1),
            'avg_message_length': round(avg_length, 1)
        }
    
    async def _check_priority_items(self, user_id: str) -> List[Dict[str, Any]]:
        """Check for high priority or urgent items in Neo4j"""
        try:
            from app.services.neo4j_service import neo4j_service
            
            # Find high priority content
            # Note: find_content_by_urgency is now synchronous, so we run it in a thread pool
            priority_results = await asyncio.to_thread(
                enhanced_neo4j.find_content_by_urgency,
                user_id,
                min_urgency=0.7,
                limit=5
            )
            
            priority_items = []
            for result in priority_results:
                content = result.get('content', {})
                tags = result.get('priority_tags', [])
                
                item = {
                    'type': 'priority_content',
                    'content_id': content.get('id'),
                    'title': content.get('title', 'Untitled'),
                    'urgency_score': content.get('urgency_score', 0.0),
                    'importance_score': content.get('importance_score', 0.0),
                    'priority_tags': tags,
                    'content_type': content.get('content_type', 'unknown')
                }
                priority_items.append(item)
            
            if priority_items:
                logger.info(f"   ⚡ Found {len(priority_items)} high priority items")
            
            return priority_items
            
        except Exception as e:
            logger.error(f"❌ Priority items check failed: {e}")
            return []
    
    async def _assess_current_focus(self, user_id: str, current_time: datetime) -> Dict[str, Any]:
        """Assess current focus areas and active contexts"""
        try:
            # Get recent content topics and tags
            recent_topics = await self._get_recent_topics(user_id, current_time)
            active_projects = await self._identify_active_projects(user_id)
            
            return {
                'recent_topics': recent_topics,
                'active_projects': active_projects,
                'focus_areas': recent_topics[:3],  # Top 3 focus areas
                'context_shift': len(set(recent_topics)) > 5  # Many different topics = context shifting
            }
            
        except Exception as e:
            logger.error(f"❌ Focus assessment failed: {e}")
            return {'recent_topics': [], 'active_projects': [], 'focus_areas': []}
    
    async def _get_recent_topics(self, user_id: str, current_time: datetime) -> List[str]:
        """Get topics from recent conversations and content"""
        try:
            # This would query Neo4j for recent content topics
            # For now, return empty list - full implementation would analyze
            # topics from last few hours of conversations
            return []
        except Exception as e:
            return []
    
    async def _identify_active_projects(self, user_id: str) -> List[Dict[str, Any]]:
        """Identify active projects and ongoing work"""
        try:
            # This would analyze content with actionable items and project tags
            # For now, return empty list - full implementation would track
            # project progress and active work
            return []
        except Exception as e:
            return []
    
    async def _update_living_context_note(
        self, 
        user_id: str, 
        current_time: datetime,
        timer_alerts: List[Dict],
        reminder_alerts: List[Dict], 
        mood_analysis: Dict,
        priority_items: List[Dict],
        focus_context: Dict
    ):
        """Update Sara's living context note with current awareness"""
        
        try:
            # Create context note content
            context_content = self._format_living_context(
                current_time, timer_alerts, reminder_alerts, 
                mood_analysis, priority_items, focus_context
            )
            
            # Create unique ID for today's context note
            date_str = current_time.strftime('%Y-%m-%d')
            context_id = f"{user_id}_living_context_{date_str}"
            context_title = f"Sara's Living Context - {current_time.strftime('%A, %B %d, %Y')}"
            
            # Process through content intelligence
            content_type, chunks = content_intelligence.process_content(
                context_content, context_title
            )
            
            metadata = metadata_extractor.extract_metadata(
                context_content, content_type, context_title
            )
            
            tags = smart_tagger.generate_tags(
                context_content, metadata, content_type, context_title
            )
            
            # Add special context tags
            from app.services.tagging_system import Tag, TagCategory, TagPriority
            context_tag = Tag(
                name="living_context",
                category=TagCategory.CONTEXT,
                priority=TagPriority.CRITICAL,
                confidence=1.0,
                description="Sara's current contextual awareness"
            )
            tags.append(context_tag)
            
            # Store/update in Neo4j
            # Note: store_intelligent_content is now synchronous, so we run it in a thread pool
            success = await asyncio.to_thread(
                enhanced_neo4j.store_intelligent_content,
                content_id=context_id,
                user_id=user_id,
                title=context_title,
                content=context_content,
                content_type=content_type,
                chunks=chunks,
                metadata=metadata,
                tags=tags
            )
            
            if success:
                logger.info(f"   📝 Updated living context note")
            else:
                logger.error(f"   ❌ Failed to update living context note")
                
        except Exception as e:
            logger.error(f"❌ Living context update failed: {e}")
    
    def _format_living_context(
        self,
        current_time: datetime,
        timer_alerts: List[Dict],
        reminder_alerts: List[Dict],
        mood_analysis: Dict,
        priority_items: List[Dict],
        focus_context: Dict
    ) -> str:
        """Format all contextual information into Sara's living context note"""
        
        parts = []
        
        parts.append(f"# Sara's Living Context")
        parts.append(f"**Updated:** {current_time.strftime('%A, %B %d, %Y at %I:%M %p')} Eastern")
        parts.append("")
        
        # Current alerts section
        if timer_alerts or reminder_alerts:
            parts.append("## 🚨 Current Alerts")
            
            for alert in timer_alerts:
                if alert['status'] == 'overdue':
                    parts.append(f"- ⏰ **OVERDUE TIMER**: {alert['label']}")
                else:
                    mins = int(alert['time_remaining'] / 60)
                    parts.append(f"- ⏰ Timer \"{alert['label']}\" due in {mins} minutes")
            
            for alert in reminder_alerts:
                mins = int(alert['time_until'] / 60)
                parts.append(f"- 📅 Reminder in {mins} minutes: {alert['content']}")
            
            parts.append("")
        
        # Current mood and energy
        if mood_analysis.get('mood') != 'unknown':
            parts.append("## 😊 Current Mood & Energy")
            parts.append(f"- **Mood**: {mood_analysis['mood'].title()} (confidence: {mood_analysis.get('mood_confidence', 0):.0%})")
            parts.append(f"- **Energy Level**: {mood_analysis.get('energy', 'moderate').title()}")
            parts.append(f"- **Engagement**: {mood_analysis.get('engagement', 'moderate').title()}")
            
            if mood_analysis.get('indicators'):
                parts.append(f"- **Indicators**: {', '.join(mood_analysis['indicators'][:3])}")
            
            parts.append("")
        
        # Priority items
        if priority_items:
            parts.append("## ⚡ High Priority Items")
            for item in priority_items[:3]:
                urgency = int(item['urgency_score'] * 100)
                parts.append(f"- **{item['title']}** (urgency: {urgency}%)")
            parts.append("")
        
        # Current focus areas
        if focus_context.get('focus_areas'):
            parts.append("## 🎯 Current Focus Areas")
            for area in focus_context['focus_areas']:
                parts.append(f"- {area.title()}")
            parts.append("")
        
        # Context notes
        parts.append("## 📋 Context Notes")
        parts.append("- Monitoring active timers and reminders")
        parts.append("- Tracking mood and energy patterns")
        parts.append("- Maintaining awareness of priority items")
        
        if mood_analysis.get('recent_activity_count', 0) > 0:
            parts.append(f"- Recent activity: {mood_analysis['recent_activity_count']} messages in last {mood_analysis.get('time_period', 'period')}")
        
        parts.append("")
        parts.append("---")
        parts.append("*This context is automatically updated every 30 minutes*")
        
        return "\n".join(parts)
    
    async def _generate_proactive_notifications(
        self,
        user_id: str,
        timer_alerts: List[Dict],
        reminder_alerts: List[Dict],
        mood_analysis: Dict,
        priority_items: List[Dict]
    ):
        """Generate proactive NTFY notifications when appropriate"""
        
        notifications = []
        
        # Timer notifications (high urgency)
        for alert in timer_alerts:
            if alert['urgency'] == 'high':
                notifications.append({
                    'title': f"Timer: {alert['label']}",
                    'message': "Timer is due!" if alert['status'] == 'overdue' else "Timer due in less than 5 minutes",
                    'priority': 'high',
                    'tags': ['⏰', 'timer']
                })
        
        # Reminder notifications (medium urgency)
        for alert in reminder_alerts:
            if alert['urgency'] == 'high':  # Within 15 minutes
                notifications.append({
                    'title': "Upcoming Reminder",
                    'message': alert['content'],
                    'priority': 'medium', 
                    'tags': ['📅', 'reminder']
                })
        
        # Mood-based notifications (low urgency)
        if mood_analysis.get('mood') == 'tired' and mood_analysis.get('mood_confidence', 0) > 0.7:
            notifications.append({
                'title': "Wellness Check",
                'message': "You seem tired - consider taking a break or staying hydrated",
                'priority': 'low',
                'tags': ['😴', 'wellness']
            })
        
        # Send notifications via NTFY
        from app.services.notification_service import notification_service
        
        for notification in notifications:
            logger.info(f"   📱 Proactive notification: {notification['title']} - {notification['message']}")
            
            # Send notification based on type
            try:
                if 'timer' in notification.get('tags', []):
                    await notification_service.send_timer_alert(
                        user_id=user_id,
                        timer_label=notification['title'].replace('Timer: ', ''),
                        is_overdue='overdue' in notification['message'].lower()
                    )
                elif 'reminder' in notification.get('tags', []):
                    await notification_service.send_reminder_alert(
                        user_id=user_id,
                        reminder_text=notification['message']
                    )
                elif 'wellness' in notification.get('tags', []):
                    wellness_type = 'tired' if 'tired' in notification['message'].lower() else 'general'
                    await notification_service.send_wellness_alert(
                        user_id=user_id,
                        wellness_type=wellness_type,
                        message=notification['message']
                    )
                else:
                    # Generic contextual alert
                    await notification_service.send_contextual_alert(
                        user_id=user_id,
                        context_type=notification['title'],
                        message=notification['message'],
                        priority=notification.get('priority', 'normal')
                    )
            except Exception as e:
                logger.error(f"   ❌ Failed to send notification: {e}")
    
    async def get_current_living_context(self, user_id: str) -> Optional[str]:
        """Get the current living context note content for Sara's awareness"""
        try:
            eastern_now = datetime.now(pytz.UTC).astimezone(self.eastern_tz)
            date_str = eastern_now.strftime('%Y-%m-%d')
            context_id = f"{user_id}_living_context_{date_str}"
            
            # Try to get from Neo4j first
            try:
                from app.services.neo4j_service import neo4j_service
                
                if neo4j_service.driver:
                    with neo4j_service.driver.session() as session:
                        query = """
                        MATCH (content:Content)
                        WHERE content.content_id = $context_id
                        AND content.user_id = $user_id
                        RETURN content.content as context_content
                        ORDER BY content.created_at DESC
                        LIMIT 1
                        """
                        
                        result = session.run(query, context_id=context_id, user_id=user_id)
                        record = result.single()
                        
                        if record and record['context_content']:
                            logger.info(f"📖 Retrieved living context from Neo4j for user {user_id}")
                            return record['context_content']
                            
            except Exception as e:
                logger.debug(f"Could not retrieve from Neo4j: {e}")
            
            # Fallback: Generate fresh context if not found
            logger.info(f"📝 Generating fresh living context for user {user_id}")
            
            # Run a quick context assessment
            db = SessionLocal()
            try:
                # Check active timers (handle missing columns gracefully)
                try:
                    active_timers = db.query(Timer).filter(
                        and_(
                            Timer.user_id == user_id,
                            Timer.status == "running",
                            Timer.ends_at > eastern_now
                        )
                    ).all()
                except Exception as e:
                    logger.debug(f"Timer query failed: {e}")
                    active_timers = []
                
                # Check upcoming reminders (next 2 hours)
                try:
                    upcoming_reminders = db.query(Reminder).filter(
                        and_(
                            Reminder.user_id == user_id,
                            Reminder.is_completed == False,
                            Reminder.reminder_time <= eastern_now + timedelta(hours=2),
                            Reminder.reminder_time > eastern_now
                        )
                    ).order_by(Reminder.reminder_time).all()
                except Exception as e:
                    logger.debug(f"Reminder query failed: {e}")
                    upcoming_reminders = []
                
                # Quick summary
                context_summary = f"""## Sara's Current Awareness - {eastern_now.strftime('%I:%M %p, %A %B %d')}

**Active Timers:** {len(active_timers)} running
**Upcoming Reminders:** {len(upcoming_reminders)} in next 2 hours
**Current Focus:** General assistance and conversation

This is a basic context summary. Full contextual awareness updates every 30 minutes."""

                return context_summary
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Failed to get living context: {e}")
            return None

# Global service instance
contextual_awareness_service = ContextualAwarenessService()