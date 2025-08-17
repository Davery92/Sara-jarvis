from abc import ABC, abstractmethod
from typing import Dict, Any, List
from pydantic import BaseModel


class ToolResult(BaseModel):
    """Result from a tool execution"""
    success: bool
    data: Any = None
    message: str = ""
    citations: List[str] = []


class BaseTool(ABC):
    """Base class for all AI tools"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description"""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON schema for tool parameters"""
        pass
    
    @abstractmethod
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Execute the tool with given parameters"""
        pass
    
    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }