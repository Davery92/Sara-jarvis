"""
Smart Tagging System
Creates intelligent, hierarchical tags for content organization and retrieval.
"""
import logging
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .content_intelligence import ContentType
from .metadata_extractor import ContentMetadata, Entity, Topic

logger = logging.getLogger(__name__)

class TagCategory(Enum):
    """Categories for organizing tags"""
    CONTENT_TYPE = "content_type"
    DOMAIN = "domain"
    PRIORITY = "priority"
    TEMPORAL = "temporal"
    ENTITY_TYPE = "entity_type"
    ACTION_STATUS = "action_status"
    MOOD = "mood"
    CONTEXT = "context"

class TagPriority(Enum):
    """Priority levels for tags"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class Tag:
    """Represents a smart tag with metadata"""
    name: str
    category: TagCategory
    priority: TagPriority
    confidence: float
    parent_tag: Optional[str] = None
    aliases: List[str] = None
    description: Optional[str] = None
    auto_generated: bool = True
    
    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []

class TagTaxonomy:
    """Hierarchical tag taxonomy for intelligent organization"""
    
    def __init__(self):
        self.taxonomy = self._build_taxonomy()
        
    def _build_taxonomy(self) -> Dict[str, Dict[str, List[str]]]:
        """Build the hierarchical tag taxonomy"""
        return {
            # Content domains
            "cooking": {
                "techniques": ["baking", "sautéing", "pressure_cooking", "grilling", "roasting"],
                "meal_types": ["breakfast", "lunch", "dinner", "snack", "dessert"],
                "cuisines": ["italian", "asian", "mexican", "american", "mediterranean"],
                "dietary": ["vegetarian", "vegan", "gluten_free", "keto", "paleo"],
                "equipment": ["ninja_foodi", "instant_pot", "oven", "stovetop", "grill"]
            },
            
            "fitness": {
                "exercise_types": ["strength", "cardio", "flexibility", "balance", "endurance"],
                "equipment": ["kettlebell", "dumbbell", "barbell", "bodyweight", "resistance_bands"],
                "muscle_groups": ["legs", "arms", "core", "back", "chest", "shoulders"],
                "goals": ["weight_loss", "muscle_gain", "endurance", "strength", "flexibility"],
                "intensity": ["beginner", "intermediate", "advanced", "high_intensity", "low_intensity"]
            },
            
            "technology": {
                "languages": ["python", "javascript", "java", "cpp", "rust", "go"],
                "frameworks": ["react", "django", "flask", "node", "express", "fastapi"],
                "platforms": ["web", "mobile", "desktop", "cloud", "api"],
                "tools": ["docker", "kubernetes", "git", "ci_cd", "database"],
                "concepts": ["architecture", "security", "performance", "testing", "deployment"]
            },
            
            "planning": {
                "project_phases": ["planning", "design", "implementation", "testing", "deployment"],
                "time_horizons": ["daily", "weekly", "monthly", "quarterly", "yearly"],
                "priority_levels": ["urgent", "important", "normal", "low_priority"],
                "status": ["todo", "in_progress", "completed", "blocked", "cancelled"]
            },
            
            "personal": {
                "moods": ["happy", "sad", "excited", "anxious", "calm", "energetic", "tired"],
                "activities": ["learning", "working", "exercising", "cooking", "socializing"],
                "goals": ["health", "career", "relationships", "hobbies", "finance"],
                "reflection": ["achievement", "challenge", "insight", "question", "decision"]
            },
            
            "work": {
                "meeting_types": ["standup", "planning", "review", "retrospective", "one_on_one"],
                "project_types": ["feature", "bug_fix", "research", "maintenance", "documentation"],
                "urgency": ["asap", "this_week", "this_month", "eventual"],
                "collaboration": ["solo", "team", "cross_team", "external", "client"]
            }
        }
    
    def get_parent_domain(self, tag: str) -> Optional[str]:
        """Get the parent domain for a tag"""
        for domain, categories in self.taxonomy.items():
            for category, tags in categories.items():
                if tag in tags:
                    return domain
        return None
    
    def get_related_tags(self, tag: str) -> List[str]:
        """Get tags related to the given tag"""
        related = []
        
        # Find the category this tag belongs to
        for domain, categories in self.taxonomy.items():
            for category, tags in categories.items():
                if tag in tags:
                    # Add other tags from the same category
                    related.extend([t for t in tags if t != tag])
                    break
        
        return related[:5]  # Limit to 5 related tags
    
    def suggest_tags(self, entities: List[Entity], topics: List[Topic], content_type: ContentType) -> List[str]:
        """Suggest additional tags based on extracted information"""
        suggestions = []
        
        # Map content type to domain
        type_to_domain = {
            ContentType.RECIPE: "cooking",
            ContentType.WORKOUT_PLAN: "fitness", 
            ContentType.TECHNICAL_DOC: "technology",
            ContentType.MEETING_NOTES: "work",
            ContentType.JOURNAL_ENTRY: "personal"
        }
        
        domain = type_to_domain.get(content_type)
        if domain and domain in self.taxonomy:
            # Get all tags from the domain
            domain_tags = []
            for category, tags in self.taxonomy[domain].items():
                domain_tags.extend(tags)
            
            # Match against entities and topics
            for entity in entities:
                entity_name_lower = entity.name.lower().replace(" ", "_")
                if entity_name_lower in domain_tags:
                    suggestions.append(entity_name_lower)
            
            for topic in topics:
                topic_name_lower = topic.name.lower()
                if topic_name_lower in domain_tags:
                    suggestions.append(topic_name_lower)
        
        return list(set(suggestions))  # Remove duplicates

class SmartTagger:
    """Main tagging service that creates intelligent tags"""
    
    def __init__(self):
        self.taxonomy = TagTaxonomy()
        
    def generate_tags(
        self, 
        content: str, 
        metadata: ContentMetadata, 
        content_type: ContentType, 
        title: str = ""
    ) -> List[Tag]:
        """Generate comprehensive tags for content"""
        
        logger.info(f"🏷️ Generating smart tags for {content_type.value} content")
        
        tags = []
        
        # 1. Content type tags
        tags.extend(self._generate_content_type_tags(content_type))
        
        # 2. Domain-specific tags
        tags.extend(self._generate_domain_tags(metadata.topics, metadata.entities))
        
        # 3. Priority/urgency tags
        tags.extend(self._generate_priority_tags(metadata.urgency_score, metadata.importance_score))
        
        # 4. Entity-based tags
        tags.extend(self._generate_entity_tags(metadata.entities))
        
        # 5. Temporal tags
        tags.extend(self._generate_temporal_tags(metadata.temporal_info, content))
        
        # 6. Action status tags
        tags.extend(self._generate_action_tags(metadata.actionable_items, metadata.intent))
        
        # 7. Context tags
        tags.extend(self._generate_context_tags(content, title))
        
        # 8. Mood tags (for personal content)
        if content_type == ContentType.JOURNAL_ENTRY:
            tags.extend(self._generate_mood_tags(content))
        
        # Remove duplicates and sort by priority
        tags = self._deduplicate_and_prioritize(tags)
        
        logger.info(f"✅ Generated {len(tags)} smart tags")
        return tags
    
    def _generate_content_type_tags(self, content_type: ContentType) -> List[Tag]:
        """Generate tags based on content type"""
        tags = []
        
        # Primary content type tag
        tags.append(Tag(
            name=content_type.value,
            category=TagCategory.CONTENT_TYPE,
            priority=TagPriority.HIGH,
            confidence=1.0,
            description=f"Content identified as {content_type.value}"
        ))
        
        # Secondary type tags
        type_mappings = {
            ContentType.RECIPE: ["food", "cooking", "instructions"],
            ContentType.WORKOUT_PLAN: ["fitness", "exercise", "health"],
            ContentType.TECHNICAL_DOC: ["technology", "documentation", "development"],
            ContentType.MEETING_NOTES: ["work", "collaboration", "communication"],
            ContentType.JOURNAL_ENTRY: ["personal", "reflection", "thoughts"],
            ContentType.TODO_LIST: ["planning", "tasks", "productivity"],
            ContentType.REFERENCE_DOC: ["reference", "information", "knowledge"]
        }
        
        for tag_name in type_mappings.get(content_type, []):
            tags.append(Tag(
                name=tag_name,
                category=TagCategory.DOMAIN,
                priority=TagPriority.MEDIUM,
                confidence=0.9,
                parent_tag=content_type.value
            ))
        
        return tags
    
    def _generate_domain_tags(self, topics: List[Topic], entities: List[Entity]) -> List[Tag]:
        """Generate domain-specific tags from topics and entities"""
        tags = []
        
        # Topic-based tags
        for topic in topics:
            if topic.confidence > 0.3:  # Minimum confidence threshold
                priority = TagPriority.HIGH if topic.confidence > 0.7 else TagPriority.MEDIUM
                tags.append(Tag(
                    name=topic.name,
                    category=TagCategory.DOMAIN,
                    priority=priority,
                    confidence=topic.confidence,
                    description=f"Topic identified with {topic.confidence:.2f} confidence"
                ))
        
        # Entity-type based domain tags
        entity_domains = {
            "Food": "cooking",
            "Exercise": "fitness", 
            "Technology": "technology",
            "Person": "social"
        }
        
        for entity in entities:
            if entity.entity_type in entity_domains and entity.confidence > 0.5:
                domain = entity_domains[entity.entity_type]
                tags.append(Tag(
                    name=domain,
                    category=TagCategory.DOMAIN,
                    priority=TagPriority.MEDIUM,
                    confidence=entity.confidence,
                    description=f"Domain inferred from {entity.entity_type} entities"
                ))
        
        return tags
    
    def _generate_priority_tags(self, urgency_score: float, importance_score: float) -> List[Tag]:
        """Generate priority-based tags"""
        tags = []
        
        # Urgency tags
        if urgency_score > 0.7:
            tags.append(Tag(
                name="urgent",
                category=TagCategory.PRIORITY,
                priority=TagPriority.CRITICAL,
                confidence=urgency_score,
                description="Content requires immediate attention"
            ))
        elif urgency_score > 0.4:
            tags.append(Tag(
                name="moderate_urgency",
                category=TagCategory.PRIORITY,
                priority=TagPriority.MEDIUM,
                confidence=urgency_score
            ))
        
        # Importance tags
        if importance_score > 0.6:
            tags.append(Tag(
                name="important",
                category=TagCategory.PRIORITY,
                priority=TagPriority.HIGH,
                confidence=importance_score,
                description="Content is of high importance"
            ))
        
        return tags
    
    def _generate_entity_tags(self, entities: List[Entity]) -> List[Tag]:
        """Generate tags based on extracted entities"""
        tags = []
        
        # Group entities by type
        entity_groups = {}
        for entity in entities:
            if entity.entity_type not in entity_groups:
                entity_groups[entity.entity_type] = []
            entity_groups[entity.entity_type].append(entity)
        
        # Create entity type tags
        for entity_type, entity_list in entity_groups.items():
            if len(entity_list) >= 2:  # Only tag if multiple entities of this type
                confidence = sum(e.confidence for e in entity_list) / len(entity_list)
                tags.append(Tag(
                    name=f"contains_{entity_type.lower()}",
                    category=TagCategory.ENTITY_TYPE,
                    priority=TagPriority.LOW,
                    confidence=confidence,
                    description=f"Contains {len(entity_list)} {entity_type} entities"
                ))
        
        return tags
    
    def _generate_temporal_tags(self, temporal_info, content: str) -> List[Tag]:
        """Generate temporal-based tags"""
        tags = []
        
        # Duration-based tags
        if temporal_info.durations:
            has_short_duration = any("minute" in d or "hour" in d for d in temporal_info.durations)
            has_long_duration = any("week" in d or "month" in d for d in temporal_info.durations)
            
            if has_short_duration:
                tags.append(Tag(
                    name="short_term",
                    category=TagCategory.TEMPORAL,
                    priority=TagPriority.MEDIUM,
                    confidence=0.8
                ))
            
            if has_long_duration:
                tags.append(Tag(
                    name="long_term", 
                    category=TagCategory.TEMPORAL,
                    priority=TagPriority.MEDIUM,
                    confidence=0.8
                ))
        
        # Schedule-based tags
        if temporal_info.schedules:
            tags.append(Tag(
                name="recurring",
                category=TagCategory.TEMPORAL,
                priority=TagPriority.MEDIUM,
                confidence=0.9,
                description="Contains recurring schedule information"
            ))
        
        return tags
    
    def _generate_action_tags(self, actionable_items: List[str], intent: str) -> List[Tag]:
        """Generate action status tags"""
        tags = []
        
        if actionable_items:
            tags.append(Tag(
                name="actionable",
                category=TagCategory.ACTION_STATUS,
                priority=TagPriority.HIGH,
                confidence=0.9,
                description=f"Contains {len(actionable_items)} actionable items"
            ))
            
            # Categorize action types
            if any(word in item.lower() for item in actionable_items for word in ["todo", "task"]):
                tags.append(Tag(
                    name="tasks",
                    category=TagCategory.ACTION_STATUS,
                    priority=TagPriority.MEDIUM,
                    confidence=0.8
                ))
            
            if any(word in item.lower() for item in actionable_items for word in ["follow", "next", "continue"]):
                tags.append(Tag(
                    name="follow_up",
                    category=TagCategory.ACTION_STATUS,
                    priority=TagPriority.MEDIUM,
                    confidence=0.7
                ))
        else:
            tags.append(Tag(
                name="informational",
                category=TagCategory.ACTION_STATUS,
                priority=TagPriority.LOW,
                confidence=0.8,
                description="Content is informational only"
            ))
        
        return tags
    
    def _generate_context_tags(self, content: str, title: str) -> List[Tag]:
        """Generate contextual tags"""
        tags = []
        
        content_lower = (content + " " + title).lower()
        
        # Context indicators
        context_patterns = {
            "tutorial": ["tutorial", "how to", "step by step", "guide", "walkthrough"],
            "reference": ["reference", "documentation", "spec", "manual", "api"],
            "personal": ["my", "i feel", "i think", "personal", "reflection"],
            "collaboration": ["team", "meeting", "discussion", "collaborate", "together"],
            "learning": ["learn", "study", "understand", "research", "explore"],
            "planning": ["plan", "strategy", "roadmap", "timeline", "schedule"]
        }
        
        for context_name, patterns in context_patterns.items():
            matches = sum(1 for pattern in patterns if pattern in content_lower)
            if matches > 0:
                confidence = min(matches / len(patterns), 1.0)
                tags.append(Tag(
                    name=context_name,
                    category=TagCategory.CONTEXT,
                    priority=TagPriority.MEDIUM,
                    confidence=confidence
                ))
        
        return tags
    
    def _generate_mood_tags(self, content: str) -> List[Tag]:
        """Generate mood tags for personal content"""
        tags = []
        
        mood_patterns = {
            "positive": ["happy", "excited", "great", "awesome", "love", "enjoy", "wonderful"],
            "negative": ["sad", "frustrated", "angry", "upset", "difficult", "challenging"],
            "neutral": ["okay", "fine", "normal", "usual", "routine"],
            "energetic": ["energetic", "motivated", "pumped", "active", "ready"],
            "tired": ["tired", "exhausted", "drained", "sleepy", "low energy"]
        }
        
        content_lower = content.lower()
        
        for mood, patterns in mood_patterns.items():
            matches = sum(1 for pattern in patterns if pattern in content_lower)
            if matches > 0:
                confidence = min(matches / 5, 1.0)  # Normalize to 0-1
                tags.append(Tag(
                    name=mood,
                    category=TagCategory.MOOD,
                    priority=TagPriority.LOW,
                    confidence=confidence,
                    description=f"Mood detected from content patterns"
                ))
        
        return tags
    
    def _deduplicate_and_prioritize(self, tags: List[Tag]) -> List[Tag]:
        """Remove duplicates and sort by priority"""
        # Remove duplicates by name
        seen_names = set()
        unique_tags = []
        
        for tag in tags:
            if tag.name not in seen_names:
                seen_names.add(tag.name)
                unique_tags.append(tag)
        
        # Sort by priority then confidence
        priority_order = {
            TagPriority.CRITICAL: 0,
            TagPriority.HIGH: 1,
            TagPriority.MEDIUM: 2,
            TagPriority.LOW: 3
        }
        
        unique_tags.sort(key=lambda t: (priority_order[t.priority], -t.confidence))
        
        return unique_tags

# Global service instance
smart_tagger = SmartTagger()