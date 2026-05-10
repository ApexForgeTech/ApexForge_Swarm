import re
from abc import ABC, abstractmethod
from typing import Any, Dict


def strip_code_fence(content: str) -> str:
    """Remove markdown code fences (e.g. ```py ... ```) that LLMs sometimes wrap file content in."""
    if not content:
        return content
    stripped = content.strip()
    match = re.match(r'^```[a-zA-Z0-9_]*\n(.*?)\n?```\s*$', stripped, re.DOTALL)
    if match:
        return match.group(1)
    return content


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict = {}

    def to_ollama_schema(self) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def execute(self, **kwargs) -> str:
        ...
