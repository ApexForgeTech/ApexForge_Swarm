#!/usr/bin/env python3
"""
ApexForge Swarm
  python main.py                           — CLI, default profile
  python main.py --profile work            — CLI, named profile
  python main.py --resume                  — Resume last session
  python main.py -p "question"             — Direct prompt, no interactive
  python main.py -p "question" --plain     — Plain text (pipeable)
  python main.py --parallel-prompt "a" --parallel-prompt "b"
  python main.py --web                     — FastAPI Web UI
  python main.py --serve                   — API server (no UI root)
  python main.py --desktop                 — Desktop App (Comic UI)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def _apply_model_override(config, model: str):
    setattr(config, "_explicit_model_override", True)
    config.ollama.model = model
    if config.agent.provider != "llama_cpp":
        return
    from agent.llm_backend import LlamaCppBackend
    resolved = LlamaCppBackend(config).resolve_model_path(model)
    if resolved:
        config.llama_cpp.model_path = resolved


def main():
    import argparse
    from agent.logging_utils import configure_logging

    # Determine log mode before parsing so logs are clean from the start
    _mode = "web" if "--web" in sys.argv or "--desktop" in sys.argv or "--serve" in sys.argv else "cli"
    configure_logging(mode=_mode)
    parser = argparse.ArgumentParser(
        description="ApexForge Swarm",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                           # interactive CLI
  python main.py --profile work            # named profile
  python main.py --web                     # web UI
  python main.py --serve                   # API server
  python main.py --desktop                 # desktop app (Comic UI)
  python main.py -p "ls /tmp"             # direct prompt, exit
        """
    )
    parser.add_argument("--web", action="store_true", help="Start FastAPI web UI")
    parser.add_argument("--serve", action="store_true", help="Start API server without the web UI root")
    parser.add_argument("--desktop", action="store_true", help="Start desktop app (Comic UI)")
    parser.add_argument("--profile", "-P", default="default", help="Profile name")
    parser.add_argument("--model", help="Override model")
    parser.add_argument("--resume", action="store_true", help="Resume last session")
    parser.add_argument("--session", help="Resume specific session ID")
    parser.add_argument("-p", "--prompt", help="Direct prompt — answer and exit")
    parser.add_argument("--parallel-prompt", action="append", default=[], help="Run multiple prompts concurrently; can be used more than once")
    parser.add_argument("--multi-agent", action="store_true", help="Use the multi-agent supervisor/worker flow")
    parser.add_argument("--template", help="Mission template (code_review, research, repo_audit, bug_investigation, feature_planning, data_analysis, document_processing)")
    parser.add_argument("--supervisor", help="Supervisor role override (used with --multi-agent or --template)")
    parser.add_argument("--worker", action="append", default=[], metavar="ROLE", help="Worker role; can be specified multiple times (used with --multi-agent)")
    parser.add_argument("--plain", action="store_true", help="Plain text output (no markdown)")
    args = parser.parse_args()

    from agent.config import Config
    config = Config.load(ROOT / "config.yaml")
    if args.model:
        _apply_model_override(config, args.model)

    selected_modes = sum(bool(flag) for flag in (args.web, args.serve, args.desktop))
    if selected_modes > 1:
        parser.error("Use only one of --web, --serve, or --desktop.")

    if args.web:
        from agent.web.app import run_web
        run_web(config)

    elif args.serve:
        from agent.web.app import run_web
        run_web(config, api_only=True)

    elif args.desktop:
        from agent.web.desktop import run_desktop
        run_desktop(config)

    elif args.prompt:
        from cli import run_direct_prompt, run_parallel_prompts
        use_multi = args.multi_agent or bool(args.template)
        if use_multi:
            run_parallel_prompts(
                config,
                [args.prompt],
                profile_name=args.profile,
                plain=args.plain,
                multi_agent=True,
                template=args.template or "",
                supervisor_role=args.supervisor or "",
                worker_roles=args.worker or [],
            )
        else:
            run_direct_prompt(config, args.prompt, profile_name=args.profile, plain=args.plain)

    elif args.parallel_prompt:
        from cli import run_parallel_prompts
        run_parallel_prompts(
            config,
            [prompt for prompt in args.parallel_prompt if prompt.strip()],
            profile_name=args.profile,
            plain=args.plain,
            multi_agent=args.multi_agent or bool(args.template),
            template=args.template or "",
            supervisor_role=args.supervisor or "",
            worker_roles=args.worker or [],
        )

    else:
        from cli import ensure_credentials, run_cli
        creds = ensure_credentials()
        run_cli(
            config,
            profile_name=args.profile,
            resume=args.resume,
            session_id=args.session,
            creds=creds,
        )


if __name__ == "__main__":
    main()
