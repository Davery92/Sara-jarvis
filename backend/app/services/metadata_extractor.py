"""
Metadata Extraction Engine
Extracts entities, topics, urgency, and other metadata from content.
"""
import re
import logging
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import Counter

from .content_intelligence import ContentType, ContentChunk

logger = logging.getLogger(__name__)

@dataclass
class Entity:
    """Represents an extracted entity"""
    name: str
    entity_type: str
    confidence: float
    context: str
    mentions: int = 1

@dataclass
class Topic:
    """Represents an extracted topic"""
    name: str
    confidence: float
    keywords: List[str]
    relevance: float

@dataclass
class TemporalInfo:
    """Represents temporal information extracted from content"""
    dates: List[datetime]
    durations: List[str]
    deadlines: List[datetime]
    schedules: List[str]

@dataclass
class ContentMetadata:
    """Complete metadata for a piece of content"""
    entities: List[Entity]
    topics: List[Topic]
    temporal_info: TemporalInfo
    urgency_score: float
    importance_score: float
    intent: str
    tags: List[str]
    actionable_items: List[str]
    mood_indicators: Optional[Dict[str, float]] = None

class EntityExtractor:
    """Extracts entities (people, places, concepts) from content"""
    
    def __init__(self):
        # Common name patterns
        self.name_patterns = [
            r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # First Last
            r'\b[A-Z][a-z]+(?:\'s)?\b',      # Possessive names
        ]
        
        # Location patterns
        self.location_patterns = [
            r'\b[A-Z][a-z]+ (?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)\b',
            r'\b[A-Z][a-z]+, [A-Z]{2}\b',   # City, State
            r'\b\d+\s+[A-Z][a-z]+ (?:Street|St|Avenue|Ave)\b',  # Address
        ]
        
        # Technology/tool patterns
        self.tech_patterns = [
            r'\b(?:API|SDK|CLI|GUI|HTTP|HTTPS|JSON|XML|SQL|NoSQL)\b',
            r'\b(?:Python|JavaScript|React|Node\.js|Docker|Kubernetes)\b',
            r'\b(?:GitHub|GitLab|AWS|Azure|Google Cloud)\b',
            r'\b(?:Ninja Foodi|kettlebell|barbell|dumbbell)\b',  # Equipment
        ]
        
        # Food/ingredient patterns
        self.food_patterns = [
            r'\b(?:beef|chicken|pork|fish|turkey|lamb)\b',
            r'\b(?:potato|onion|garlic|carrot|celery|tomato)\b',
            r'\b(?:salt|pepper|thyme|rosemary|oregano|basil)\b',
            r'\b(?:cup|cups|tablespoon|teaspoon|pound|ounce|lb|oz)\b',
        ]
        
        # Exercise/fitness patterns
        self.fitness_patterns = [
            r'\b(?:squat|deadlift|bench press|pull-up|push-up|burpee)\b',
            r'\b(?:cardio|strength|endurance|flexibility|yoga|pilates)\b',
            r'\b(?:reps|sets|weight|resistance|intensity)\b',
        ]
    
    def extract_entities(self, content: str, content_type: ContentType) -> List[Entity]:
        """Extract entities from content based on type and patterns"""
        entities = []
        
        # Extract people names
        people = self._extract_people(content)
        entities.extend(people)
        
        # Extract locations
        locations = self._extract_locations(content)
        entities.extend(locations)
        
        # Extract type-specific entities
        if content_type == ContentType.TECHNICAL_DOC:
            tech_entities = self._extract_tech_entities(content)
            entities.extend(tech_entities)
        elif content_type == ContentType.RECIPE:
            food_entities = self._extract_food_entities(content)
            entities.extend(food_entities)
        elif content_type == ContentType.WORKOUT_PLAN:
            fitness_entities = self._extract_fitness_entities(content)
            entities.extend(fitness_entities)
        
        # Remove duplicates and merge similar entities
        entities = self._deduplicate_entities(entities)
        
        logger.info(f"📍 Extracted {len(entities)} entities from {content_type.value} content")
        return entities
    
    def _extract_people(self, content: str) -> List[Entity]:
        """Extract people names from content"""
        people = []
        
        for pattern in self.name_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                # Filter out common false positives
                if not self._is_likely_name(match):
                    continue
                    
                people.append(Entity(
                    name=match,
                    entity_type="Person",
                    confidence=0.7,
                    context=self._get_context(content, match)
                ))
        
        return people
    
    def _extract_locations(self, content: str) -> List[Entity]:
        """Extract location entities"""
        locations = []
        
        for pattern in self.location_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                locations.append(Entity(
                    name=match,
                    entity_type="Location",
                    confidence=0.8,
                    context=self._get_context(content, match)
                ))
        
        return locations
    
    def _extract_tech_entities(self, content: str) -> List[Entity]:
        """Extract technology/tool entities"""
        tech_entities = []
        
        for pattern in self.tech_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                tech_entities.append(Entity(
                    name=match,
                    entity_type="Technology",
                    confidence=0.9,
                    context=self._get_context(content, match)
                ))
        
        return tech_entities
    
    def _extract_food_entities(self, content: str) -> List[Entity]:
        """Extract food/ingredient entities"""
        food_entities = []
        
        for pattern in self.food_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                food_entities.append(Entity(
                    name=match,
                    entity_type="Food",
                    confidence=0.8,
                    context=self._get_context(content, match)
                ))
        
        return food_entities
    
    def _extract_fitness_entities(self, content: str) -> List[Entity]:
        """Extract fitness/exercise entities"""
        fitness_entities = []
        
        for pattern in self.fitness_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                fitness_entities.append(Entity(
                    name=match,
                    entity_type="Exercise",
                    confidence=0.8,
                    context=self._get_context(content, match)
                ))
        
        return fitness_entities
    
    def _is_likely_name(self, text: str) -> bool:
        """Check if text is likely a person's name"""
        # Filter out common false positives
        false_positives = {
            'Ninja Foodi', 'High', 'Low', 'Medium', 'Quick', 'Easy', 'Simple',
            'Stage', 'Phase', 'Step', 'Week', 'Day', 'Month', 'Year'
        }
        return text not in false_positives and len(text.split()) <= 3
    
    def _get_context(self, content: str, entity: str, window: int = 50) -> str:
        """Get surrounding context for an entity"""
        entity_pos = content.lower().find(entity.lower())
        if entity_pos == -1:
            return ""
        
        start = max(0, entity_pos - window)
        end = min(len(content), entity_pos + len(entity) + window)
        return content[start:end].strip()
    
    def _deduplicate_entities(self, entities: List[Entity]) -> List[Entity]:
        """Remove duplicate entities and merge similar ones"""
        entity_map = {}
        
        for entity in entities:
            key = (entity.name.lower(), entity.entity_type)
            if key in entity_map:
                entity_map[key].mentions += 1
                entity_map[key].confidence = max(entity_map[key].confidence, entity.confidence)
            else:
                entity_map[key] = entity
        
        return list(entity_map.values())

class TopicClassifier:
    """Classifies content into topics and themes"""
    
    def __init__(self):
        self.topic_keywords = {
            'cooking': ['recipe', 'ingredient', 'cook', 'bake', 'stew', 'pot', 'heat', 'simmer', 'season'],
            'fitness': ['workout', 'exercise', 'training', 'weight', 'reps', 'sets', 'muscle', 'strength'],
            'technology': ['api', 'system', 'code', 'development', 'server', 'database', 'programming'],
            'planning': ['plan', 'schedule', 'agenda', 'timeline', 'deadline', 'project', 'task', 'goal'],
            'health': ['health', 'wellness', 'nutrition', 'diet', 'medical', 'doctor', 'symptoms'],
            'personal': ['personal', 'feeling', 'emotion', 'thoughts', 'reflection', 'mood', 'journal'],
            'work': ['work', 'job', 'meeting', 'team', 'project', 'deadline', 'business', 'office'],
            'learning': ['learn', 'study', 'education', 'course', 'tutorial', 'knowledge', 'skill']
        }
    
    def classify_topics(self, content: str, content_type: ContentType) -> List[Topic]:
        """Classify content into relevant topics"""
        content_lower = content.lower()
        topics = []
        
        for topic_name, keywords in self.topic_keywords.items():
            # Count keyword matches
            matches = sum(1 for keyword in keywords if keyword in content_lower)
            
            if matches > 0:
                confidence = min(matches / len(keywords), 1.0)
                relevance = matches / len(content.split()) * 100  # Percentage of content
                
                # Boost confidence based on content type
                if self._topic_matches_content_type(topic_name, content_type):
                    confidence *= 1.5
                    confidence = min(confidence, 1.0)
                
                if confidence > 0.1:  # Minimum threshold
                    topics.append(Topic(
                        name=topic_name,
                        confidence=confidence,
                        keywords=[k for k in keywords if k in content_lower],
                        relevance=relevance
                    ))
        
        # Sort by confidence
        topics.sort(key=lambda t: t.confidence, reverse=True)
        
        logger.info(f"🏷️ Classified into {len(topics)} topics")
        return topics[:5]  # Return top 5 topics
    
    def _topic_matches_content_type(self, topic: str, content_type: ContentType) -> bool:
        """Check if topic aligns with content type"""
        alignments = {
            ContentType.RECIPE: ['cooking', 'health'],
            ContentType.WORKOUT_PLAN: ['fitness', 'health', 'planning'],
            ContentType.TECHNICAL_DOC: ['technology', 'work', 'learning'],
            ContentType.MEETING_NOTES: ['work', 'planning'],
            ContentType.JOURNAL_ENTRY: ['personal', 'health'],
        }
        
        return topic in alignments.get(content_type, [])

class TemporalExtractor:
    """Extracts temporal information (dates, deadlines, schedules)"""
    
    def __init__(self):
        self.date_patterns = [
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',          # MM/DD/YYYY
            r'\b\d{4}-\d{2}-\d{2}\b',              # YYYY-MM-DD
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b',
            r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b',
        ]
        
        self.time_patterns = [
            r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)\b',
            r'\b\d{1,2}\s*(?:AM|PM|am|pm)\b',
        ]
        
        self.duration_patterns = [
            r'\b\d+\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\b',
            r'\b\d+[-–]\d+\s*(?:minutes?|mins?|hours?|hrs?)\b',
        ]
        
        self.deadline_indicators = [
            'deadline', 'due', 'by', 'until', 'before', 'no later than'
        ]
    
    def extract_temporal_info(self, content: str) -> TemporalInfo:
        """Extract all temporal information from content"""
        dates = self._extract_dates(content)
        durations = self._extract_durations(content)
        deadlines = self._extract_deadlines(content)
        schedules = self._extract_schedules(content)
        
        return TemporalInfo(
            dates=dates,
            durations=durations,
            deadlines=deadlines,
            schedules=schedules
        )
    
    def _extract_dates(self, content: str) -> List[datetime]:
        """Extract explicit dates"""
        dates = []
        # Implementation would parse various date formats
        # For now, return empty list
        return dates
    
    def _extract_durations(self, content: str) -> List[str]:
        """Extract duration mentions"""
        durations = []
        for pattern in self.duration_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            durations.extend(matches)
        return durations
    
    def _extract_deadlines(self, content: str) -> List[datetime]:
        """Extract deadline information"""
        # Implementation would parse deadlines relative to date mentions
        return []
    
    def _extract_schedules(self, content: str) -> List[str]:
        """Extract schedule information"""
        schedules = []
        # Look for recurring patterns
        recurring_patterns = [
            r'(?:every|each)\s+(?:day|week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
            r'(?:daily|weekly|monthly|yearly)',
            r'\b\d+\s*times?\s+(?:per|a)\s+(?:day|week|month)'
        ]
        
        for pattern in recurring_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            schedules.extend(matches)
        
        return schedules

class UrgencyAssessor:
    """Assesses urgency and importance of content"""
    
    def __init__(self):
        self.urgency_keywords = {
            'high': ['urgent', 'asap', 'immediately', 'emergency', 'critical', 'now', 'today'],
            'medium': ['soon', 'priority', 'important', 'needed', 'tomorrow', 'this week'],
            'low': ['eventually', 'sometime', 'when possible', 'low priority', 'later']
        }
        
        self.importance_indicators = [
            'crucial', 'essential', 'vital', 'key', 'main', 'primary', 'major', 'significant'
        ]
    
    def assess_urgency(self, content: str, content_type: ContentType) -> float:
        """Assess urgency score (0.0 to 1.0)"""
        content_lower = content.lower()
        
        urgency_score = 0.0
        
        # Check for urgency keywords
        for level, keywords in self.urgency_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in content_lower)
            if level == 'high':
                urgency_score += matches * 0.8
            elif level == 'medium':
                urgency_score += matches * 0.5
            elif level == 'low':
                urgency_score -= matches * 0.3
        
        # Content type affects base urgency
        type_urgency = {
            ContentType.TODO_LIST: 0.6,
            ContentType.MEETING_NOTES: 0.4,
            ContentType.TECHNICAL_DOC: 0.3,
            ContentType.RECIPE: 0.1,
            ContentType.JOURNAL_ENTRY: 0.1,
            ContentType.REFERENCE_DOC: 0.1,
        }
        
        urgency_score += type_urgency.get(content_type, 0.2)
        
        return min(max(urgency_score, 0.0), 1.0)
    
    def assess_importance(self, content: str, content_type: ContentType) -> float:
        """Assess importance score (0.0 to 1.0)"""
        content_lower = content.lower()
        
        importance_score = 0.2  # Base score
        
        # Check for importance indicators
        matches = sum(1 for indicator in self.importance_indicators if indicator in content_lower)
        importance_score += matches * 0.2
        
        # Length suggests detail/importance
        word_count = len(content.split())
        if word_count > 500:
            importance_score += 0.3
        elif word_count > 200:
            importance_score += 0.2
        
        return min(importance_score, 1.0)

class MetadataExtractor:
    """Main metadata extraction service"""
    
    def __init__(self):
        self.entity_extractor = EntityExtractor()
        self.topic_classifier = TopicClassifier()
        self.temporal_extractor = TemporalExtractor()
        self.urgency_assessor = UrgencyAssessor()
    
    def extract_metadata(self, content: str, content_type: ContentType, title: str = "") -> ContentMetadata:
        """Extract complete metadata from content"""
        logger.info(f"🔍 Extracting metadata from {content_type.value} content")
        
        # Extract entities
        entities = self.entity_extractor.extract_entities(content, content_type)
        
        # Classify topics
        topics = self.topic_classifier.classify_topics(content, content_type)
        
        # Extract temporal information
        temporal_info = self.temporal_extractor.extract_temporal_info(content)
        
        # Assess urgency and importance
        urgency_score = self.urgency_assessor.assess_urgency(content, content_type)
        importance_score = self.urgency_assessor.assess_importance(content, content_type)
        
        # Determine intent
        intent = self._determine_intent(content, content_type)
        
        # Generate tags
        tags = self._generate_tags(entities, topics, content_type)
        
        # Extract actionable items
        actionable_items = self._extract_actionable_items(content)
        
        metadata = ContentMetadata(
            entities=entities,
            topics=topics,
            temporal_info=temporal_info,
            urgency_score=urgency_score,
            importance_score=importance_score,
            intent=intent,
            tags=tags,
            actionable_items=actionable_items
        )
        
        logger.info(f"✅ Metadata extracted: {len(entities)} entities, {len(topics)} topics, {len(tags)} tags")
        return metadata
    
    def _determine_intent(self, content: str, content_type: ContentType) -> str:
        """Determine the intent of the content"""
        content_lower = content.lower()
        
        if any(word in content_lower for word in ['todo', 'task', 'action', 'do', 'complete']):
            return 'actionable'
        elif any(word in content_lower for word in ['reference', 'documentation', 'guide', 'manual']):
            return 'reference'
        elif any(word in content_lower for word in ['learn', 'understand', 'study', 'research']):
            return 'learning'
        elif content_type == ContentType.JOURNAL_ENTRY:
            return 'personal'
        else:
            return 'informational'
    
    def _generate_tags(self, entities: List[Entity], topics: List[Topic], content_type: ContentType) -> List[str]:
        """Generate tags based on extracted information"""
        tags = []
        
        # Add content type as base tag
        tags.append(content_type.value)
        
        # Add entity types as tags
        entity_types = list(set(entity.entity_type.lower() for entity in entities))
        tags.extend(entity_types)
        
        # Add top topics as tags
        top_topics = [topic.name for topic in topics[:3]]
        tags.extend(top_topics)
        
        return list(set(tags))  # Remove duplicates
    
    def _extract_actionable_items(self, content: str) -> List[str]:
        """Extract actionable items from content"""
        actionable_items = []
        
        # Look for explicit action patterns
        action_patterns = [
            r'TODO:?\s*(.+)',
            r'Action:?\s*(.+)',
            r'Next steps?:?\s*(.+)',
            r'Follow[- ]up:?\s*(.+)',
            r'\d+\.\s*([A-Z].+?)(?:\n|$)',  # Numbered lists
            r'-\s*([A-Z].+?)(?:\n|$)',      # Bullet lists starting with capital
        ]
        
        for pattern in action_patterns:
            matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            actionable_items.extend([match.strip() for match in matches])
        
        return actionable_items

# Global service instance
metadata_extractor = MetadataExtractor()