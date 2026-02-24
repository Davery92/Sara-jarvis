"""
Sara Autonomous Sweep Service

This service performs background analysis of user data to generate contextual insights
based on personality modes and user activity patterns. Each sweep type has different
depth and focus areas.
"""
import json
import asyncio
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from sqlalchemy.orm import Session
from sqlalchemy import text, desc, and_, or_, func


@dataclass
class SweepMetrics:
    """Track metrics during sweep execution"""
    episodes_analyzed: int = 0
    notes_analyzed: int = 0
    patterns_found: Dict[str, int] = field(default_factory=dict)

    def add_pattern(self, pattern_type: str):
        self.patterns_found[pattern_type] = self.patterns_found.get(pattern_type, 0) + 1

# Avoid circular imports by importing models locally in methods
# These are only needed for type hints and database queries
if TYPE_CHECKING:
    from ..main_simple import (
        AutonomousInsight, BackgroundSweep,
        ActivitySession, UserProfile, Habit, HabitInstance,
        Document, Conversation, ConversationTurn, IntelligentMemoryService
    )

from ..models.episode import Episode
from ..models.note import Note
from ..services.memory_service import MemoryService
from ..models.profile import GTKYSession, DailyReflection, PrivacySettings

# Get logger
logger = logging.getLogger(__name__)

class PriorityScorer:
    """Calculates priority scores for insights using relevance × impact × novelty × timing - annoyance"""
    
    @staticmethod
    def calculate_priority(
        relevance: float,      # 0-1: How relevant to user's current context
        impact: float,         # 0-1: How much this could help the user
        novelty: float,        # 0-1: How new/surprising this insight is
        timing: float,         # 0-1: How timely this insight is
        annoyance: float = 0.1 # 0-1: How annoying this notification might be
    ) -> float:
        """
        Calculate priority score: relevance × impact × novelty × timing - annoyance
        Returns a score between -1 and 1, where > 0.3 typically warrants notification
        """
        base_score = relevance * impact * novelty * timing
        final_score = base_score - annoyance
        return max(-1.0, min(1.0, final_score))  # Clamp to [-1, 1]

    @staticmethod
    def should_surface(priority_score: float, sweep_type: str) -> bool:
        """Determine if an insight should be surfaced to the user"""
        thresholds = {
            'quick_sweep': 0.6,    # High bar for quick interruptions
            'standard_sweep': 0.4,  # Medium bar for standard notifications
            'digest_sweep': 0.2    # Lower bar for digest summaries
        }
        return priority_score >= thresholds.get(sweep_type, 0.4)

class AutonomousSweepService:
    """Core service for generating autonomous insights based on user data analysis"""

    def __init__(self, db: Session):
        self.db = db
        self.scorer = PriorityScorer()
        self.memory_service = MemoryService(db)
        # Import IntelligentMemoryService here to avoid circular import
        from ..main_simple import IntelligentMemoryService
        self.intelligent_memory = IntelligentMemoryService()
    
    async def execute_sweep(
        self,
        user_id: str,
        sweep_type: str,
        triggered_by: str = "idle_threshold"
    ) -> List[Dict[str, Any]]:
        """Execute a background sweep and generate insights"""

        # Import models here to avoid circular import
        from ..main_simple import UserProfile

        start_time = time.time()
        insights_generated = []
        errors = []
        metrics = SweepMetrics()

        try:
            # Get user profile for personalization
            profile = self.db.query(UserProfile).filter(
                UserProfile.user_id == user_id
            ).first()

            # Count items analyzed for metrics
            recent_cutoff = datetime.utcnow() - timedelta(days=7)
            metrics.episodes_analyzed = self.db.query(func.count(Episode.id)).filter(
                Episode.user_id == user_id,
                Episode.created_at >= recent_cutoff
            ).scalar() or 0
            metrics.notes_analyzed = self.db.query(func.count(Note.id)).filter(
                Note.user_id == user_id,
                Note.updated_at >= recent_cutoff
            ).scalar() or 0

            # Execute sweep based on type
            if sweep_type == 'quick_sweep':
                insights_generated = await self._quick_sweep(user_id, profile)
            elif sweep_type == 'standard_sweep':
                insights_generated = await self._standard_sweep(user_id, profile)
            elif sweep_type == 'digest_sweep':
                insights_generated = await self._digest_sweep(user_id, profile)
            else:
                raise ValueError(f"Unknown sweep type: {sweep_type}")

            # Track patterns found from insights
            for insight in insights_generated:
                insight_type = insight.get('type', 'unknown')
                metrics.add_pattern(insight_type)

            # Enrich insights with memory context
            if insights_generated and sweep_type != 'quick_sweep':
                insights_generated = await self._enrich_with_memory_context(
                    user_id, insights_generated
                )

        except Exception as e:
            errors.append(str(e))

        # Log the sweep execution with metrics
        execution_time_ms = int((time.time() - start_time) * 1000)
        self._log_sweep_execution(
            user_id, sweep_type, triggered_by,
            execution_time_ms, len(insights_generated), errors, metrics
        )

        return insights_generated
    
    async def _enrich_with_memory_context(
        self,
        user_id: str,
        insights: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Enrich insights with relevant memory context for deeper understanding"""

        enriched_insights = []

        for insight in insights:
            try:
                # Generate search query based on insight content
                search_queries = self._generate_memory_queries(insight)
                
                # Search for relevant memories
                relevant_memories = []
                for query in search_queries:
                    memory_results = await self.memory_service.search_memory(
                        user_id=user_id,
                        query=query,
                        limit=5,
                        scopes=["episodes", "notes"]
                    )
                    relevant_memories.extend(memory_results[:3])  # Top 3 per query
                
                # Add memory context to insight
                if relevant_memories:
                    insight['memory_context'] = {
                        'related_memories': relevant_memories[:5],  # Top 5 overall
                        'context_summary': self._summarize_memory_context(relevant_memories[:5])
                    }
                    
                    # Boost priority if memories show patterns
                    if len(relevant_memories) >= 3:
                        insight['priority_score'] = min(1.0, insight['priority_score'] * 1.15)
                        insight['title'] = f"🧠 {insight['title']}"  # Mark as memory-enhanced
                
                enriched_insights.append(insight)
                
            except Exception as e:
                logger.warning(f"Memory enrichment failed for insight: {e}")
                enriched_insights.append(insight)  # Keep original insight
        
        return enriched_insights
    
    def _generate_memory_queries(self, insight: Dict[str, Any]) -> List[str]:
        """Generate search queries to find relevant memories for an insight"""
        queries = []

        insight_type = insight.get('type', '')
        title = insight.get('title', '')
        message = insight.get('message', '')

        # Base queries from insight content
        queries.append(f"{title} {message}")

        # Type-specific queries
        if insight_type == 'habit_salvage':
            queries.extend([
                "habit failure motivation",
                "missed goal reflection",
                "habit struggle pattern"
            ])
        elif insight_type == 'content_pattern':
            queries.extend([
                "similar topic discussion",
                "repeated interest pattern",
                "knowledge connection"
            ])
        elif insight_type == 'knowledge_connection':
            queries.extend([
                "note connection insight",
                "learning pattern discovery",
                "topic relationship"
            ])

        return queries[:4]  # Limit to avoid over-querying
    
    def _summarize_memory_context(self, memories: List[Dict[str, Any]]) -> str:
        """Create a brief summary of memory context for the insight"""
        if not memories:
            return ""
            
        memory_count = len(memories)
        recent_count = sum(1 for m in memories if 'days_ago' in m and m.get('days_ago', 0) < 7)
        
        if memory_count == 1:
            return "Found 1 related memory from your history"
        elif recent_count > 0:
            return f"Found {memory_count} related memories, including {recent_count} from this week"
        else:
            return f"Found {memory_count} related memories from your conversation history"
    
    async def _analyze_conversation_patterns_with_memory(
        self, 
        user_id: str
    ) -> List[Dict[str, Any]]:
        """Use memory service to analyze conversation patterns and themes"""
        insights = []
        
        try:
            # Search for recent conversation themes
            theme_searches = [
                "question about learning",
                "goal progress discussion", 
                "problem solving conversation",
                "planning future activity",
                "reflection on past experience"
            ]
            
            pattern_findings = {}
            for theme in theme_searches:
                memories = await self.memory_service.search_memory(
                    user_id=user_id,
                    query=theme,
                    limit=10,
                    scopes=["episodes"]
                )
                
                if len(memories) >= 3:  # Found a pattern
                    pattern_findings[theme] = memories[:5]
            
            # Generate insights based on patterns
            for theme, memories in pattern_findings.items():
                if theme == "question about learning":
                    priority = self.scorer.calculate_priority(0.7, 0.6, 0.5, 0.8)
                    if self.scorer.should_surface(priority, 'standard_sweep'):
                        insights.append({
                            'type': 'learning_pattern',
                            'title': '📚 I notice your curiosity trend',
                            'message': f'You\'ve been asking lots of learning questions lately. Want to explore this topic deeper?',
                            'priority_score': priority,
                            'memory_context': {
                                'related_memories': memories,
                                'context_summary': f"Found {len(memories)} learning-related conversations"
                            }
                        })
                        
                elif theme == "goal progress discussion":
                    priority = self.scorer.calculate_priority(0.8, 0.7, 0.4, 0.9)
                    if self.scorer.should_surface(priority, 'standard_sweep'):
                        insights.append({
                            'type': 'goal_pattern',
                            'title': '🎯 Tracking your goal journey',
                            'message': f'I see consistent goal discussions in our conversations. Ready for a progress check?',
                            'priority_score': priority,
                            'memory_context': {
                                'related_memories': memories,
                                'context_summary': f"Found {len(memories)} goal-related conversations"
                            }
                        })
                        
                elif theme == "reflection on past experience":
                    priority = self.scorer.calculate_priority(0.6, 0.8, 0.6, 0.7)
                    if self.scorer.should_surface(priority, 'standard_sweep'):
                        insights.append({
                            'type': 'reflection_pattern',
                            'title': '💭 I see you processing experiences',
                            'message': f'You\'ve been reflecting thoughtfully on past events. That shows great self-awareness.',
                            'priority_score': priority,
                            'memory_context': {
                                'related_memories': memories,
                                'context_summary': f"Found {len(memories)} reflective conversations"
                            }
                        })
                        
        except Exception as e:
            logger.warning(f"Memory-based conversation analysis failed: {e}")
            
        return insights
    
    async def _quick_sweep(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Quick sweep: Fast, lightweight checks with minimal processing"""
        insights = []

        try:
            # Check for GTKY completion status
            insights.extend(await self._check_gtky_status(user_id, profile))

            # Check for nightly reflection needs
            insights.extend(await self._check_reflection_needs(user_id, profile))

            # Check recent activity for habit salvage opportunities
            insights.extend(await self._check_habit_salvage(user_id))

            # Check for upcoming calendar conflicts
            insights.extend(await self._check_calendar_prep(user_id))

        except Exception as e:
            logger.warning("Error in quick sweep: %s", e)

        return insights

    async def _standard_sweep(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Standard sweep: Deeper analysis with pattern recognition"""
        insights = []

        try:
            # Check reflection insights and patterns
            insights.extend(await self._analyze_reflection_patterns(user_id, profile))

            # Generate profile-based personalized insights
            insights.extend(await self._generate_profile_insights(user_id, profile))

            # Analyze recent patterns in notes and conversations
            insights.extend(await self._analyze_content_patterns(user_id))

            # Generate habit analytics and suggestions
            insights.extend(await self._generate_habit_insights(user_id))

            # Analyze knowledge graph connections
            insights.extend(await self._analyze_knowledge_connections(user_id))

            # Check for emotional patterns
            insights.extend(await self._analyze_emotional_patterns(user_id))

            # Analyze conversation patterns using memory service
            insights.extend(await self._analyze_conversation_patterns_with_memory(user_id))

        except Exception as e:
            logger.warning("Error in standard sweep: %s", e)

        return insights

    async def _digest_sweep(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Digest sweep: Comprehensive analysis with summaries and recommendations"""
        insights = []

        try:
            # Generate weekly/daily summaries
            insights.extend(await self._generate_periodic_summaries(user_id))

            # Identify long-term patterns and trends
            insights.extend(await self._identify_long_term_trends(user_id))

            # Generate "one big suggestion" for the user
            big_suggestion = await self._generate_big_suggestion(user_id)
            if big_suggestion:
                insights.append(big_suggestion)

            # Deep memory analysis for comprehensive insights
            insights.extend(await self._analyze_conversation_patterns_with_memory(user_id))

        except Exception as e:
            logger.warning("Error in digest sweep: %s", e)

        return insights
    
    async def _check_gtky_status(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Check if user needs to complete GTKY interview"""
        insights = []
        
        # Check privacy settings first
        privacy = self.db.query(PrivacySettings).filter(
            PrivacySettings.user_id == user_id
        ).first()
        
        # Skip if user has disabled autonomous level
        if privacy and privacy.autonomous_level == 'disabled':
            return insights
        
        # Check if GTKY is completed (completed_at is not null means completed)
        gtky_session = self.db.query(GTKYSession).filter(
            GTKYSession.user_id == user_id,
            GTKYSession.completed_at.isnot(None)
        ).first()
        
        if not gtky_session:
            # High priority if no GTKY completed
            priority = self.scorer.calculate_priority(0.9, 0.8, 0.7, 0.9, 0.05)
            if self.scorer.should_surface(priority, 'quick_sweep'):
                insights.append({
                    'type': 'gtky_prompt',
                    'title': '👋 Let me get to know you better',
                    'message': self._get_gtky_message(),
                    'priority_score': priority,
                    'related_data': {'action': 'start_gtky'}
                })
        
        return insights
    
    async def _check_reflection_needs(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Check if user needs to do nightly reflection"""
        insights = []
        
        # Check privacy settings
        privacy = self.db.query(PrivacySettings).filter(
            PrivacySettings.user_id == user_id
        ).first()
        
        if privacy and privacy.autonomous_level == 'disabled':
            return insights
        
        # Check if reflection is done today (reflection existing means it's done)
        today = datetime.now().date()
        today_reflection = self.db.query(DailyReflection).filter(
            DailyReflection.user_id == user_id,
            DailyReflection.reflection_date == today
        ).first()
        
        # Check time - only suggest after 5 PM
        current_hour = datetime.now().hour
        
        if not today_reflection and current_hour >= 17:
            # Higher priority later in the evening
            timing_boost = min(1.0, (current_hour - 17) / 5)  # 0 at 5PM, 1.0 at 10PM
            priority = self.scorer.calculate_priority(0.8, 0.7, 0.6, 0.6 + timing_boost)
            
            if self.scorer.should_surface(priority, 'quick_sweep'):
                insights.append({
                    'type': 'reflection_prompt',
                    'title': '🌙 Ready for tonight\'s reflection?',
                    'message': self._get_reflection_message(current_hour),
                    'priority_score': priority,
                    'related_data': {'action': 'start_reflection'}
                })
        
        return insights
    
    async def _analyze_reflection_patterns(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Analyze reflection patterns and generate insights"""
        insights = []
        
        # Get recent reflections (last 2 weeks) - all existing reflections are completed
        two_weeks_ago = datetime.now() - timedelta(days=14)
        recent_reflections = self.db.query(DailyReflection).filter(
            DailyReflection.user_id == user_id,
            DailyReflection.created_at >= two_weeks_ago
        ).order_by(desc(DailyReflection.created_at)).all()
        
        if len(recent_reflections) >= 3:
            # Calculate reflection streak
            consecutive_days = 0
            current_date = datetime.now().date()
            
            for i in range(14):  # Check last 14 days
                check_date = current_date - timedelta(days=i)
                has_reflection = any(r.reflection_date == check_date for r in recent_reflections)
                if has_reflection:
                    consecutive_days += 1
                else:
                    break
            
            if consecutive_days >= 3:
                priority = self.scorer.calculate_priority(0.6, 0.7, 0.5, 0.6)
                if self.scorer.should_surface(priority, 'standard_sweep'):
                    insights.append({
                        'type': 'reflection_streak',
                        'title': f'🔥 {consecutive_days}-day reflection streak!',
                        'message': self._get_streak_message(consecutive_days),
                        'priority_score': priority,
                        'related_data': {'streak_days': consecutive_days}
                    })
            
            # Analyze mood trends if we have mood data
            mood_scores = []
            for reflection in recent_reflections:
                if reflection.responses and 'mood_scale' in reflection.responses:
                    mood_scores.append(reflection.responses['mood_scale'])
            
            if len(mood_scores) >= 5:
                avg_mood = sum(mood_scores) / len(mood_scores)
                recent_avg = sum(mood_scores[:3]) / 3 if len(mood_scores) >= 3 else avg_mood
                
                if recent_avg > avg_mood + 1.5:  # Mood improved significantly
                    priority = self.scorer.calculate_priority(0.7, 0.6, 0.8, 0.7)
                    if self.scorer.should_surface(priority, 'standard_sweep'):
                        insights.append({
                            'type': 'mood_improvement',
                            'title': '📈 Your mood is trending up!',
                            'message': f'Your recent mood average is {recent_avg:.1f}/10, up from {avg_mood:.1f}/10. What\'s been working?',
                            'priority_score': priority,
                            'related_data': {'recent_avg': recent_avg, 'overall_avg': avg_mood}
                        })
        
        return insights
    
    async def _generate_profile_insights(self, user_id: str, profile: Optional["UserProfile"]) -> List[Dict[str, Any]]:
        """Generate insights based on user profile data from GTKY"""
        insights = []
        
        if not profile or not profile.profile_data:
            return insights
        
        profile_data = profile.profile_data
        
        # Generate insights based on profile data
        if 'goals' in profile_data and profile_data['goals']:
            goals = profile_data['goals']
            if isinstance(goals, dict) and 'main_goals' in goals:
                main_goals = goals['main_goals']
                if main_goals and len(main_goals) > 0:
                    priority = self.scorer.calculate_priority(0.7, 0.8, 0.4, 0.6)
                    if self.scorer.should_surface(priority, 'standard_sweep'):
                        goal_text = main_goals[0] if isinstance(main_goals, list) else str(main_goals)
                        insights.append({
                            'type': 'goal_check',
                            'title': '🎯 How\'s your main goal going?',
                            'message': f'You mentioned wanting to work on: "{goal_text[:50]}..." How\'s progress?',
                            'priority_score': priority,
                            'related_data': {'goal': goal_text}
                        })
        
        # Check communication style preferences
        if profile.communication_style == 'direct':
            priority = self.scorer.calculate_priority(0.5, 0.6, 0.7, 0.4)
            if self.scorer.should_surface(priority, 'standard_sweep'):
                insights.append({
                    'type': 'style_adjustment',
                    'title': '💬 Adjusting my communication style',
                    'message': 'I notice you prefer direct communication. I\'ll keep things concise and actionable.',
                    'priority_score': priority,
                    'related_data': {'style': profile.communication_style}
                })
        
        return insights
    
    async def _check_habit_salvage(self, user_id: str) -> List[Dict[str, Any]]:
        """Check for habits that can still be salvaged today"""
        from ..models.habit import Habit, HabitInstance

        insights = []

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        completed_today = self.db.query(HabitInstance.habit_id).filter(
            HabitInstance.user_id == user_id,
            HabitInstance.date >= today_start,
            HabitInstance.date < tomorrow_start,
            HabitInstance.status == "complete"
        ).distinct().all()
        completed_habit_ids = {row[0] for row in completed_today}

        # Query habits that haven't been completed today but still can be
        habits = self.db.query(Habit).filter(
            Habit.user_id == user_id,
            or_(Habit.paused == 0, Habit.paused.is_(None))
        ).all()

        for habit in habits:
            if habit.id in completed_habit_ids:
                continue

            # Calculate priority score
            relevance = 0.8  # High relevance for habit tracking
            impact = 0.7     # Good impact on user goals
            novelty = 0.3    # Not very novel, but useful
            timing = 0.9     # Very timely (can still do today)

            priority = self.scorer.calculate_priority(relevance, impact, novelty, timing)

            if self.scorer.should_surface(priority, 'quick_sweep'):
                insights.append({
                    'type': 'habit_salvage',
                    'title': f'Time to {habit.title}?',
                    'message': self._get_habit_salvage_message(habit.title),
                    'priority_score': priority,
                    'related_data': {'habit_id': habit.id}
                })
        
        return insights[:2]  # Limit to 2 habit salvage suggestions
    
    async def _check_calendar_prep(self, user_id: str) -> List[Dict[str, Any]]:
        """Check for upcoming events that need preparation (Concierge mode)"""
        insights = []
        
        # This would integrate with calendar data when available
        # For now, return a placeholder insight
        if True:  # Always check calendar prep
            priority = self.scorer.calculate_priority(0.6, 0.5, 0.4, 0.8)
            if self.scorer.should_surface(priority, 'quick_sweep'):
                insights.append({
                    'type': 'calendar_prep',
                    'title': 'Upcoming events to prep for',
                    'message': 'I notice you have meetings coming up. Shall I help you prepare?',
                    'priority_score': priority,
                    'related_data': {}
                })
        
        return insights
    
    async def _analyze_content_patterns(self, user_id: str) -> List[Dict[str, Any]]:
        """Analyze patterns in recent notes and conversations"""
        insights = []
        
        # Get recent notes (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        recent_notes = self.db.query(Note).filter(
            Note.user_id == user_id,
            Note.updated_at >= week_ago
        ).order_by(desc(Note.updated_at)).limit(10).all()
        
        if len(recent_notes) >= 3:
            # Simple pattern detection: frequent topics
            topics = []
            for note in recent_notes:
                # Basic keyword extraction from note content
                words = note.content.lower().split()
                topics.extend([w for w in words if len(w) > 4])  # Simple topic extraction
            
            if topics:
                from collections import Counter
                common_topics = Counter(topics).most_common(3)
                
                if common_topics and common_topics[0][1] >= 2:  # Topic appears at least twice
                    priority = self.scorer.calculate_priority(0.7, 0.6, 0.6, 0.5)
                    if self.scorer.should_surface(priority, 'standard_sweep'):
                        topic = common_topics[0][0]
                        insights.append({
                            'type': 'content_pattern',
                            'title': f'Frequent topic: {topic}',
                            'message': self._get_pattern_message(topic),
                            'priority_score': priority,
                            'related_data': {'topics': common_topics[:3]}
                        })
        
        return insights
    
    async def _generate_habit_insights(self, user_id: str) -> List[Dict[str, Any]]:
        """Generate coaching insights about habit performance"""
        from ..models.habit import HabitInstance

        insights = []
        
        if False:  # Always generate habit insights
            return insights
        
        # Get recent habit performance
        week_ago = datetime.now() - timedelta(days=7)
        recent_instances = self.db.query(HabitInstance).filter(
            and_(
                HabitInstance.user_id == user_id,
                HabitInstance.date >= week_ago,
                HabitInstance.status == "complete"
            )
        ).all()
        
        if recent_instances:
            # Calculate completion rate
            total_expected = self.db.query(HabitInstance).filter(
                and_(
                    HabitInstance.user_id == user_id,
                    HabitInstance.date >= week_ago
                )
            ).count()
            
            completion_rate = len(recent_instances) / max(total_expected, 1)
            
            if completion_rate > 0.8:  # High performance
                priority = self.scorer.calculate_priority(0.6, 0.7, 0.4, 0.6)
                if self.scorer.should_surface(priority, 'standard_sweep'):
                    insights.append({
                        'type': 'habit_performance',
                        'title': 'Crushing your habits! 💪',
                        'message': f'You\'re at {completion_rate:.0%} completion rate this week. What\'s your secret?',
                        'priority_score': priority,
                        'related_data': {'completion_rate': completion_rate}
                    })
            elif completion_rate < 0.4:  # Struggling
                priority = self.scorer.calculate_priority(0.8, 0.9, 0.3, 0.7)
                if self.scorer.should_surface(priority, 'standard_sweep'):
                    insights.append({
                        'type': 'habit_struggle',
                        'title': 'Let\'s get back on track',
                        'message': f'{completion_rate:.0%} completion this week. Want to adjust your approach?',
                        'priority_score': priority,
                        'related_data': {'completion_rate': completion_rate}
                    })
        
        return insights
    
    async def _analyze_knowledge_connections(self, user_id: str) -> List[Dict[str, Any]]:
        """Analyze knowledge connections in notes (Analyst/Librarian modes)"""
        insights = []
        
        if False:  # Always analyze knowledge
            return insights
        
        # Get notes without many connections
        from ..main_simple import NoteConnection
        notes = self.db.query(Note).filter(Note.user_id == user_id).all()
        
        for note in notes:
            connection_count = self.db.query(NoteConnection).filter(
                or_(
                    NoteConnection.source_note_id == note.id,
                    NoteConnection.target_note_id == note.id
                )
            ).count()
            
            if connection_count == 0 and len(note.content) > 100:  # Unconnected substantial note
                priority = self.scorer.calculate_priority(0.5, 0.6, 0.7, 0.4)
                if self.scorer.should_surface(priority, 'standard_sweep'):
                    insights.append({
                        'type': 'knowledge_connection',
                        'title': 'Unconnected note found',
                        'message': f'"{note.title}" might connect to other ideas in your knowledge graph.',
                        'priority_score': priority,
                        'related_data': {'note_id': note.id}
                    })
                    break  # Only suggest one at a time
        
        return insights
    
    async def _analyze_emotional_patterns(self, user_id: str) -> List[Dict[str, Any]]:
        """Analyze emotional patterns in conversations (Companion mode)"""
        # Import here to avoid circular import
        from ..main_simple import ConversationTurn

        insights = []

        if False:  # Always check emotional patterns
            return insights

        # Get recent conversation turns
        week_ago = datetime.now() - timedelta(days=7)
        recent_turns = self.db.query(ConversationTurn).filter(
            and_(
                ConversationTurn.user_id == user_id,
                ConversationTurn.role == 'user',
                ConversationTurn.created_at >= week_ago
            )
        ).order_by(desc(ConversationTurn.created_at)).limit(10).all()
        
        if recent_turns:
            # Simple sentiment analysis (placeholder - could be enhanced)
            positive_words = ['good', 'great', 'happy', 'excited', 'love', 'awesome', 'wonderful']
            negative_words = ['bad', 'sad', 'frustrated', 'angry', 'worried', 'stressed', 'difficult']
            
            sentiment_score = 0
            for turn in recent_turns:
                content = turn.content.lower()
                sentiment_score += sum(1 for word in positive_words if word in content)
                sentiment_score -= sum(1 for word in negative_words if word in content)
            
            if sentiment_score < -2:  # Negative sentiment detected
                priority = self.scorer.calculate_priority(0.8, 0.7, 0.4, 0.6)
                if self.scorer.should_surface(priority, 'standard_sweep'):
                    insights.append({
                        'type': 'emotional_check',
                        'title': 'How are you feeling?',
                        'message': 'I\'ve noticed some challenging themes in our recent chats. Want to talk about it?',
                        'priority_score': priority,
                        'related_data': {'sentiment_score': sentiment_score}
                    })
        
        return insights
    
    async def _generate_periodic_summaries(self, user_id: str) -> List[Dict[str, Any]]:
        """Generate daily/weekly summaries (Digest sweep)"""
        from ..models.conversation import Conversation

        insights = []
        
        # Generate a summary based on recent activity
        week_ago = datetime.now() - timedelta(days=7)
        
        # Count activities
        notes_count = self.db.query(Note).filter(
            and_(Note.user_id == user_id, Note.updated_at >= week_ago)
        ).count()
        
        conversations_count = self.db.query(Conversation).filter(
            and_(Conversation.user_id == user_id, Conversation.updated_at >= week_ago)
        ).count()
        
        if notes_count > 0 or conversations_count > 0:
            priority = self.scorer.calculate_priority(0.6, 0.5, 0.3, 0.8)
            if self.scorer.should_surface(priority, 'digest_sweep'):
                insights.append({
                    'type': 'weekly_summary',
                    'title': 'Your week in review',
                    'message': self._get_weekly_summary_message(notes_count, conversations_count),
                    'priority_score': priority,
                    'related_data': {
                        'notes_count': notes_count,
                        'conversations_count': conversations_count
                    }
                })
        
        return insights
    
    async def _identify_long_term_trends(self, user_id: str) -> List[Dict[str, Any]]:
        """Identify long-term patterns and trends"""
        insights = []
        
        # Placeholder for trend analysis
        # This would analyze data over months to identify growth patterns
        priority = self.scorer.calculate_priority(0.5, 0.6, 0.8, 0.4)
        if self.scorer.should_surface(priority, 'digest_sweep'):
            insights.append({
                'type': 'long_term_trend',
                'title': 'Growth pattern detected',
                'message': 'Your knowledge creation has increased 40% this month compared to last.',
                'priority_score': priority,
                'related_data': {}
            })
        
        return insights[:1]  # Limit to prevent overwhelming
    
    async def _generate_big_suggestion(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Generate one major suggestion based on comprehensive analysis"""
        priority = self.scorer.calculate_priority(0.7, 0.8, 0.6, 0.5)
        if self.scorer.should_surface(priority, 'digest_sweep'):
            return {
                'type': 'big_suggestion',
                'title': 'One big suggestion',
                'message': 'Consider one focused habit this week that supports your top priority.',
                'priority_score': priority,
                'related_data': {}
            }
        
        return None
    
    def _get_habit_salvage_message(self, habit_title: str) -> str:
        """Get message for habit salvage"""
        return f"Still time to complete {habit_title} today!"
    
    def _get_pattern_message(self, topic: str) -> str:
        """Get message for content patterns."""
        return f"I notice you're focused on {topic} lately."
    
    def _get_weekly_summary_message(self, notes_count: int, conversations_count: int) -> str:
        """Get weekly summary message."""
        return f"Weekly summary: {notes_count} notes organized, {conversations_count} discussions facilitated."
    
    def _get_gtky_message(self) -> str:
        """Get message for GTKY interview prompt."""
        return "I'd love to learn more about you to provide better assistance!"
    
    def _get_reflection_message(self, current_hour: int) -> str:
        """Get message for reflection prompt."""
        time_context = "Perfect time for reflection" if current_hour >= 19 else "Good time to reflect"
        return f"{time_context} on your day - just 3 minutes of thoughtful questions."
    
    def _get_streak_message(self, streak_days: int) -> str:
        """Get message for reflection streak."""
        return f"Great consistency: {streak_days} days of reflection in a row."
    
    def _log_sweep_execution(
        self,
        user_id: str,
        sweep_type: str,
        triggered_by: str,
        execution_time_ms: int,
        insights_generated: int,
        errors: List[str],
        metrics: Optional[SweepMetrics] = None
    ):
        """Log the execution of a background sweep with metrics"""
        # Import BackgroundSweep here to avoid circular import
        from ..main_simple import BackgroundSweep

        # Use metrics if provided, otherwise defaults
        episodes_analyzed = metrics.episodes_analyzed if metrics else 0
        notes_analyzed = metrics.notes_analyzed if metrics else 0
        patterns_found = metrics.patterns_found if metrics else {}

        sweep_log = BackgroundSweep(
            user_id=user_id,
            sweep_type=sweep_type,
            triggered_by=triggered_by,
            execution_time_ms=execution_time_ms,
            insights_generated=insights_generated,
            errors_encountered=json.dumps(errors) if errors else None,
            episodes_analyzed=episodes_analyzed,
            notes_analyzed=notes_analyzed,
            patterns_found=json.dumps(patterns_found) if patterns_found else None
        )
        self.db.add(sweep_log)
        self.db.commit()

        logger.info(f"🤖 Sweep completed: {sweep_type} in {execution_time_ms}ms, "
                   f"{insights_generated} insights, {episodes_analyzed} episodes, "
                   f"{notes_analyzed} notes analyzed")
