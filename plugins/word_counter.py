"""
Example plugin: word_counter
Counts words, characters, and lines in the given text.
"""
from agent.plugins import PluginTool


class WordCounterTool(PluginTool):
    name = "word_count"
    description = "Count words, characters, and lines in the provided text."
    version = "1.0.0"
    author = "ApexForge Swarm"
    tags = ["utility", "text"]
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to analyse.",
            },
        },
        "required": ["text"],
    }

    def execute(self, text: str = "") -> str:
        lines = text.splitlines()
        words = text.split()
        chars = len(text)
        return (
            f"Lines: {len(lines)}\n"
            f"Words: {len(words)}\n"
            f"Characters: {chars}"
        )
