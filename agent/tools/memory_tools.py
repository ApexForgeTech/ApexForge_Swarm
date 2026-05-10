from .base import BaseTool


class RememberTool(BaseTool):
    name = "remember"
    description = "Save something to your persistent memory as a .md file. Use to remember user preferences, project facts, decisions, or any info you'll need later."
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Short name/title for this memory."},
            "content": {"type": "string", "description": "What to remember (markdown supported)."},
        },
        "required": ["topic", "content"],
    }

    def __init__(self, memory_system):
        self._mem = memory_system

    def execute(self, topic: str, content: str) -> str:
        return self._mem.remember(topic, content)


class RecallTool(BaseTool):
    name = "recall"
    description = "Read a specific memory by topic name."
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Memory topic to recall."},
        },
        "required": ["topic"],
    }

    def __init__(self, memory_system):
        self._mem = memory_system

    def execute(self, topic: str) -> str:
        return self._mem.recall(topic)


class LearnSkillTool(BaseTool):
    name = "learn_skill"
    description = "Save a new skill definition as a .md file. Skills are loaded at startup and shape how you behave. Use when you learn a new technique, workflow, or capability."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name."},
            "content": {"type": "string", "description": "Skill description and instructions (markdown)."},
        },
        "required": ["name", "content"],
    }

    def __init__(self, memory_system):
        self._mem = memory_system

    def execute(self, name: str, content: str) -> str:
        return self._mem.learn_skill(name, content)
