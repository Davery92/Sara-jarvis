"""
Content Intelligence Service
Handles intelligent content processing, chunking, and metadata extraction.
"""
import re
import logging
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class ContentType(Enum):
    """Content type classifications for intelligent processing"""
    RECIPE = "recipe"
    TECHNICAL_DOC = "technical_doc"
    WORKOUT_PLAN = "workout_plan"
    MEETING_NOTES = "meeting_notes"
    JOURNAL_ENTRY = "journal_entry"
    REFERENCE_DOC = "reference_doc"
    TODO_LIST = "todo_list"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"

class ChunkType(Enum):
    """Types of content chunks"""
    HEADER = "header"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CODE_BLOCK = "code_block"
    TABLE = "table"
    METADATA = "metadata"

@dataclass
class ContentChunk:
    """Represents a chunk of content with metadata"""
    content: str
    chunk_type: ChunkType
    order: int
    metadata: Dict[str, Any]
    parent_section: Optional[str] = None
    
class ContentTypeDetector:
    """Detects content type based on content analysis"""
    
    def __init__(self):
        self.recipe_patterns = [
            r'ingredients?:?\s*\n',
            r'directions?:?\s*\n',
            r'instructions?:?\s*\n',
            r'\d+\s*(cups?|tbsp|tsp|lbs?|oz|cloves?)',
            r'preheat|bake|cook|simmer|boil|sauté',
            r'temperature|°[CF]|\d+\s*degrees'
        ]
        
        self.technical_patterns = [
            r'```[\w]*\n.*?\n```',  # Code blocks
            r'API|endpoint|database|server|client',
            r'function|class|method|variable',
            r'implementation|architecture|system',
            r'TODO:|FIXME:|NOTE:',
            r'version \d+\.\d+|v\d+\.\d+'
        ]
        
        self.workout_patterns = [
            r'\d+\s*(reps?|sets?|lbs?|kg|minutes?|seconds?)',
            r'exercise|workout|training|fitness',
            r'squats?|deadlifts?|bench|press|curls?',
            r'kettlebell|dumbbell|barbell',
            r'rest|break|recovery'
        ]
        
        self.meeting_patterns = [
            r'meeting|agenda|action items?',
            r'attendees?:|participants?:',
            r'next steps?:|follow[- ]up',
            r'decision:|conclusion:|outcome:'
        ]
        
        self.journal_patterns = [
            r'^(today|yesterday|this morning)',
            r'feeling|felt|mood|emotional',
            r'i think|i feel|i believe|i realize',
            r'reflection|thoughts?|personal'
        ]
    
    def detect_content_type(self, content: str, title: str = "") -> ContentType:
        """Detect the primary content type based on content and title analysis"""
        content_lower = content.lower()
        title_lower = title.lower()
        combined_text = f"{title_lower} {content_lower}"
        
        # Score each content type
        scores = {}
        
        # Recipe detection
        recipe_score = self._count_patterns(combined_text, self.recipe_patterns)
        if 'recipe' in title_lower or 'stew' in title_lower or 'cook' in title_lower:
            recipe_score += 3
        scores[ContentType.RECIPE] = recipe_score
        
        # Technical document detection
        tech_score = self._count_patterns(combined_text, self.technical_patterns)
        if any(word in title_lower for word in ['api', 'system', 'feature', 'implementation']):
            tech_score += 3
        scores[ContentType.TECHNICAL_DOC] = tech_score
        
        # Workout plan detection
        workout_score = self._count_patterns(combined_text, self.workout_patterns)
        if any(word in title_lower for word in ['workout', 'kettlebell', 'training', 'plan']):
            workout_score += 3
        scores[ContentType.WORKOUT_PLAN] = workout_score
        
        # Meeting notes detection
        meeting_score = self._count_patterns(combined_text, self.meeting_patterns)
        if any(word in title_lower for word in ['meeting', 'agenda', 'notes']):
            meeting_score += 3
        scores[ContentType.MEETING_NOTES] = meeting_score
        
        # Journal entry detection
        journal_score = self._count_patterns(combined_text, self.journal_patterns)
        if any(word in title_lower for word in ['journal', 'diary', 'thoughts', 'reflection']):
            journal_score += 3
        scores[ContentType.JOURNAL_ENTRY] = journal_score
        
        # Determine best match
        best_type = max(scores.items(), key=lambda x: x[1])
        
        # Require minimum score to avoid false positives
        if best_type[1] >= 2:
            logger.info(f"📋 Detected content type: {best_type[0].value} (score: {best_type[1]})")
            return best_type[0]
        
        logger.info(f"📋 Content type: unknown (best score: {best_type[1]})")
        return ContentType.UNKNOWN
    
    def _count_patterns(self, text: str, patterns: List[str]) -> int:
        """Count pattern matches in text"""
        count = 0
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            count += len(matches)
        return count

class ContentChunker:
    """Intelligently chunks content based on type and structure"""
    
    def __init__(self):
        self.max_chunk_size = {
            ContentType.RECIPE: 300,           # Small chunks for ingredients/steps
            ContentType.TECHNICAL_DOC: 800,   # Larger chunks for complex concepts
            ContentType.WORKOUT_PLAN: 200,    # Small chunks for exercises
            ContentType.MEETING_NOTES: 400,   # Medium chunks for topics
            ContentType.JOURNAL_ENTRY: 600,   # Medium-large for thoughts
            ContentType.REFERENCE_DOC: 1000,  # Large chunks for reference
            ContentType.TODO_LIST: 100,       # Very small for individual tasks
            ContentType.CONVERSATION: 500,    # Medium for dialogue
            ContentType.UNKNOWN: 500          # Default medium size
        }
    
    def chunk_content(self, content: str, content_type: ContentType, title: str = "") -> List[ContentChunk]:
        """Chunk content intelligently based on its type"""
        logger.info(f"📝 Chunking {content_type.value} content: {len(content)} chars")
        
        if content_type == ContentType.RECIPE:
            return self._chunk_recipe(content)
        elif content_type == ContentType.TECHNICAL_DOC:
            return self._chunk_technical_doc(content)
        elif content_type == ContentType.WORKOUT_PLAN:
            return self._chunk_workout_plan(content)
        elif content_type == ContentType.MEETING_NOTES:
            return self._chunk_meeting_notes(content)
        elif content_type == ContentType.JOURNAL_ENTRY:
            return self._chunk_journal_entry(content)
        else:
            return self._chunk_generic(content, content_type)
    
    def _chunk_recipe(self, content: str) -> List[ContentChunk]:
        """Chunk recipe content by ingredients, directions, etc."""
        chunks = []
        order = 0
        
        # Split into major sections
        sections = re.split(r'\n\s*#+\s*', content)
        
        for section in sections:
            if not section.strip():
                continue
                
            # Detect section type
            section_lower = section.lower()
            if 'ingredient' in section_lower:
                # Chunk ingredients by groups or individual items
                items = re.split(r'\n\s*[-*]\s*', section)
                for item in items:
                    if item.strip():
                        chunks.append(ContentChunk(
                            content=item.strip(),
                            chunk_type=ChunkType.LIST_ITEM,
                            order=order,
                            metadata={'section': 'ingredients', 'item_type': 'ingredient'},
                            parent_section='ingredients'
                        ))
                        order += 1
            
            elif any(word in section_lower for word in ['direction', 'instruction', 'step']):
                # Chunk directions by numbered steps
                steps = re.split(r'\n\s*\d+\.?\s*', section)
                for i, step in enumerate(steps):
                    if step.strip():
                        chunks.append(ContentChunk(
                            content=step.strip(),
                            chunk_type=ChunkType.PARAGRAPH,
                            order=order,
                            metadata={'section': 'directions', 'step_number': i+1},
                            parent_section='directions'
                        ))
                        order += 1
            
            else:
                # Generic recipe section
                chunks.append(ContentChunk(
                    content=section.strip(),
                    chunk_type=ChunkType.PARAGRAPH,
                    order=order,
                    metadata={'section': 'general'},
                    parent_section='general'
                ))
                order += 1
        
        logger.info(f"🍳 Recipe chunked into {len(chunks)} pieces")
        return chunks
    
    def _chunk_technical_doc(self, content: str) -> List[ContentChunk]:
        """Chunk technical documentation by sections and code blocks"""
        chunks = []
        order = 0
        
        # First, extract code blocks
        code_blocks = []
        def replace_code_block(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_{len(code_blocks)-1}__"
        
        content_no_code = re.sub(r'```[\w]*\n.*?\n```', replace_code_block, content, flags=re.DOTALL)
        
        # Split by headers
        sections = re.split(r'\n\s*#+\s*', content_no_code)
        
        for section in sections:
            if not section.strip():
                continue
                
            # Process paragraphs in section
            paragraphs = [p.strip() for p in section.split('\n\n') if p.strip()]
            
            for paragraph in paragraphs:
                # Check if this paragraph contains a code block placeholder
                if '__CODE_BLOCK_' in paragraph:
                    # Replace with actual code block
                    for i, code_block in enumerate(code_blocks):
                        paragraph = paragraph.replace(f'__CODE_BLOCK_{i}__', code_block)
                    
                    chunks.append(ContentChunk(
                        content=paragraph,
                        chunk_type=ChunkType.CODE_BLOCK,
                        order=order,
                        metadata={'section': 'technical', 'contains_code': True}
                    ))
                else:
                    chunks.append(ContentChunk(
                        content=paragraph,
                        chunk_type=ChunkType.PARAGRAPH,
                        order=order,
                        metadata={'section': 'technical', 'contains_code': False}
                    ))
                order += 1
        
        logger.info(f"🔧 Technical doc chunked into {len(chunks)} pieces")
        return chunks
    
    def _chunk_workout_plan(self, content: str) -> List[ContentChunk]:
        """Chunk workout plan by exercises and sets"""
        chunks = []
        order = 0
        
        # Split by exercises or major sections
        sections = re.split(r'\n\s*(?:#+\s*|\*\*|\d+\.)', content)
        
        for section in sections:
            if not section.strip():
                continue
                
            # Look for exercise patterns
            if re.search(r'\d+\s*(reps?|sets?|lbs?|kg)', section.lower()):
                chunks.append(ContentChunk(
                    content=section.strip(),
                    chunk_type=ChunkType.LIST_ITEM,
                    order=order,
                    metadata={'section': 'exercise', 'has_reps': True},
                    parent_section='workout'
                ))
            else:
                chunks.append(ContentChunk(
                    content=section.strip(),
                    chunk_type=ChunkType.PARAGRAPH,
                    order=order,
                    metadata={'section': 'general', 'has_reps': False},
                    parent_section='workout'
                ))
            order += 1
        
        logger.info(f"💪 Workout plan chunked into {len(chunks)} pieces")
        return chunks
    
    def _chunk_meeting_notes(self, content: str) -> List[ContentChunk]:
        """Chunk meeting notes by topics and action items"""
        chunks = []
        order = 0
        
        # Split by bullets or numbered items
        items = re.split(r'\n\s*[-*•]\s*|\n\s*\d+\.?\s*', content)
        
        for item in items:
            if not item.strip():
                continue
                
            # Detect if this is an action item
            is_action = any(word in item.lower() for word in ['todo', 'action', 'follow up', 'next step'])
            
            chunks.append(ContentChunk(
                content=item.strip(),
                chunk_type=ChunkType.LIST_ITEM if is_action else ChunkType.PARAGRAPH,
                order=order,
                metadata={'section': 'meeting', 'is_action_item': is_action}
            ))
            order += 1
        
        logger.info(f"📝 Meeting notes chunked into {len(chunks)} pieces")
        return chunks
    
    def _chunk_journal_entry(self, content: str) -> List[ContentChunk]:
        """Chunk journal entry by thoughts and topics"""
        chunks = []
        order = 0
        
        # Split by paragraphs, but keep related thoughts together
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        for paragraph in paragraphs:
            # Detect emotional content
            has_emotion = any(word in paragraph.lower() for word in 
                            ['feel', 'felt', 'emotion', 'mood', 'happy', 'sad', 'angry', 'excited'])
            
            chunks.append(ContentChunk(
                content=paragraph,
                chunk_type=ChunkType.PARAGRAPH,
                order=order,
                metadata={'section': 'journal', 'has_emotion': has_emotion}
            ))
            order += 1
        
        logger.info(f"📔 Journal entry chunked into {len(chunks)} pieces")
        return chunks
    
    def _chunk_generic(self, content: str, content_type: ContentType) -> List[ContentChunk]:
        """Generic chunking for unknown content types"""
        chunks = []
        max_size = self.max_chunk_size[content_type]
        
        # Split by paragraphs first
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        current_chunk = ""
        order = 0
        
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) > max_size and current_chunk:
                # Save current chunk
                chunks.append(ContentChunk(
                    content=current_chunk.strip(),
                    chunk_type=ChunkType.PARAGRAPH,
                    order=order,
                    metadata={'section': 'generic'}
                ))
                order += 1
                current_chunk = paragraph
            else:
                current_chunk += "\n\n" + paragraph if current_chunk else paragraph
        
        # Add final chunk
        if current_chunk:
            chunks.append(ContentChunk(
                content=current_chunk.strip(),
                chunk_type=ChunkType.PARAGRAPH,
                order=order,
                metadata={'section': 'generic'}
            ))
        
        logger.info(f"📄 Generic content chunked into {len(chunks)} pieces")
        return chunks

class ContentIntelligenceService:
    """Main service for intelligent content processing"""
    
    def __init__(self):
        self.detector = ContentTypeDetector()
        self.chunker = ContentChunker()
    
    def process_content(self, content: str, title: str = "") -> Tuple[ContentType, List[ContentChunk]]:
        """Process content through the full intelligence pipeline"""
        logger.info(f"🧠 Processing content: '{title}' ({len(content)} chars)")
        
        # Detect content type
        content_type = self.detector.detect_content_type(content, title)
        
        # Chunk content intelligently
        chunks = self.chunker.chunk_content(content, content_type, title)
        
        logger.info(f"✅ Content processed: {content_type.value}, {len(chunks)} chunks")
        return content_type, chunks

# Global service instance
content_intelligence = ContentIntelligenceService()