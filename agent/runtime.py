import logging
from pathlib import Path

from .core import Agent
from .plugins.loader import PluginLoader
from .rag import RAGSystem
from .tools import (
    ReadFileTool, WriteFileTool, ListDirTool,
    SearchFilesTool, MakeDirTool, DeletePathTool, MovePathTool,
    ShellTool, AutoShellTool, EditFileTool, PythonTool, JavaScriptTool,
    FetchUrlTool, WebSearchTool, ReadDocTool, RememberTool, RecallTool, LearnSkillTool,
)
from .tools.rag_tools import RAGIngestTool, RAGSearchTool, RAGStatsTool, RAGClearTool

logger = logging.getLogger("runtime")
logger.addHandler(logging.NullHandler())


def _make_rag(config) -> RAGSystem:
    rag_cfg = config.rag
    # persist_dir relative to project root
    persist = Path(rag_cfg.persist_dir)
    if not persist.is_absolute():
        persist = Path(__file__).parent.parent / persist
    rag_cfg.persist_dir = str(persist)
    return RAGSystem(rag_cfg, ollama_host=config.ollama.host)


def register_standard_tools(agent: Agent, config) -> Agent:
    mem = agent.memory
    agent.register_tool(ReadFileTool())
    agent.register_tool(WriteFileTool())
    agent.register_tool(ListDirTool())
    agent.register_tool(SearchFilesTool())
    agent.register_tool(MakeDirTool())
    agent.register_tool(DeletePathTool())
    agent.register_tool(MovePathTool())
    agent.register_tool(ShellTool(timeout=config.shell.timeout))
    agent.register_tool(AutoShellTool(default_timeout=config.shell.timeout))
    agent.register_tool(EditFileTool())
    agent.register_tool(PythonTool(timeout=config.code.timeout))
    agent.register_tool(JavaScriptTool(timeout=config.code.timeout))
    agent.register_tool(FetchUrlTool())
    agent.register_tool(WebSearchTool())
    agent.register_tool(ReadDocTool())
    agent.register_tool(RememberTool(mem))
    agent.register_tool(RecallTool(mem))
    agent.register_tool(LearnSkillTool(mem))

    if config.rag.enabled:
        rag = _make_rag(config)
        agent.register_tool(RAGIngestTool(rag))
        agent.register_tool(RAGSearchTool(rag))
        agent.register_tool(RAGStatsTool(rag))
        agent.register_tool(RAGClearTool(rag))
        agent.rag = rag

    if config.plugins.enabled:
        plugins_dir = Path(config.plugins.plugins_dir)
        if not plugins_dir.is_absolute():
            plugins_dir = Path(__file__).parent.parent / plugins_dir
        loader = PluginLoader(plugins_dir)
        result = loader.load()
        for tool in result.loaded:
            agent.register_tool(tool)
        if result.errors:
            for fname, err in result.errors:
                logger.warning("plugin_skipped_due_to_error", file=fname, error=err)
        agent.plugin_load_result = result

    return agent


def build_agent(config, memory=None) -> Agent:
    agent = Agent(config, memory=memory)
    return register_standard_tools(agent, config)
