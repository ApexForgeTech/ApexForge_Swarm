from abc import ABC, abstractmethod
from typing import Any, Dict


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
