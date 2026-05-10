import logging
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote_plus

from .core_helpers import ascii_json, resolve_file_path, shell_quote
from .logging_utils import log_event


class ToolExecutor:
    def __init__(self, tools: Dict[str, Any], logger_: logging.Logger):
        self.tools = tools
        self.logger = logger_

    def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        if name not in self.tools:
            return f"Error: unknown tool '{name}'"
        try:
            log_event(self.logger, logging.INFO, "tool_call_started", tool=name, args=args)
            result = str(self.tools[name].execute(**args))
            log_event(self.logger, logging.INFO, "tool_call_completed", tool=name, result_preview=result)
            return result
        except Exception as exc:
            log_event(self.logger, logging.ERROR, "tool_call_failed", tool=name, args=args, error=str(exc))
            return f"Tool error ({name}): {exc}"

    def execute_with_fallback(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        primary_result = self.call_tool(name, args)
        attempts = [{"name": name, "args": args, "result": primary_result, "primary": True}]
        if not self.is_tool_error(primary_result):
            return {"final_name": name, "final_result": primary_result, "attempts": attempts}

        for fallback in self.build_fallbacks(name, args):
            fb_name = fallback["name"]
            fb_args = fallback["args"]
            fb_result = self.call_tool(fb_name, fb_args)
            attempts.append({"name": fb_name, "args": fb_args, "result": fb_result, "primary": False})
            if not self.is_tool_error(fb_result):
                combined = (
                    f"Primary tool `{name}` failed.\n"
                    f"{primary_result}\n\n"
                    f"Fallback via `{fb_name}` succeeded:\n{fb_result}"
                )
                return {"final_name": name, "final_result": combined, "attempts": attempts}

        combined = "\n\n".join(
            (
                f"{'Primary' if item['primary'] else 'Fallback'} `{item['name']}` result:\n"
                f"{item['result']}"
            )
            for item in attempts
        )
        return {"final_name": name, "final_result": combined, "attempts": attempts}

    def is_tool_error(self, result: str) -> bool:
        text = (result or "").strip().lower()
        if not text:
            return False
        if text.startswith("error"):
            return True
        if text.startswith(("tool error", "http error", "url error", "search error")):
            return True
        if "not allowed in autoshell" in text:
            return True
        if "[stderr]\ntraceback" in text:
            return True
        return False

    def build_fallbacks(self, name: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        fallbacks: List[Dict[str, Any]] = []

        if name == "search_files":
            query = args.get("query", "")
            directory = args.get("directory", ".")
            file_pattern = args.get("file_pattern", "*")
            case_sensitive = bool(args.get("case_sensitive", False))
            grep_case = "" if case_sensitive else "-i "
            rg_case = "" if case_sensitive else "-i "
            shell_cmd = (
                "if command -v rg >/dev/null 2>&1; then "
                f"rg -n {rg_case}--glob {shell_quote(file_pattern)} {shell_quote(query)} {shell_quote(directory)}; "
                "else "
                f"find {shell_quote(directory)} -type f -name {shell_quote(file_pattern)} -exec grep -n --color=never {grep_case}{shell_quote(query)} {{}} +; "
                "fi"
            )
            py_code = f"""
from pathlib import Path
import re
query = {ascii_json(query)}
directory = Path({ascii_json(directory)})
pattern = {ascii_json(file_pattern)}
case_sensitive = {repr(case_sensitive)}
flags = 0 if case_sensitive else re.IGNORECASE
try:
    regex = re.compile(query, flags)
    matcher = lambda line: regex.search(line)
except re.error:
    needle = query if case_sensitive else query.lower()
    matcher = lambda line: needle in (line if case_sensitive else line.lower())
matches = []
for path in directory.rglob(pattern):
    if not path.is_file():
        continue
    try:
        for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if matcher(line):
                matches.append(f"{{path}}:{{idx}}:{{line}}")
                if len(matches) >= 100:
                    raise SystemExit
    except SystemExit:
        break
    except Exception:
        continue
print("\\n".join(matches) if matches else f"No matches found for '{{query}}' in {{directory}}/{{pattern}}")
""".strip()
            js_code = f"""
const fs = require("fs");
const path = require("path");

const query = {ascii_json(query)};
const directory = {ascii_json(directory)};
const pattern = {ascii_json(file_pattern)};
const caseSensitive = {str(case_sensitive).lower()};
const needle = caseSensitive ? query : query.toLowerCase();
let regex = null;
try {{
  regex = new RegExp(query, caseSensitive ? "" : "i");
}} catch (_) {{
  regex = null;
}}

function globToRegex(glob) {{
  const escaped = glob
    .replace(/[.+^${{}}()|[\\]\\\\]/g, "\\\\$&")
    .replace(/\\*/g, ".*")
    .replace(/\\?/g, ".");
  return new RegExp("^" + escaped + "$");
}}

const globRegex = globToRegex(pattern);
const matches = [];

function walk(dir) {{
  let entries;
  try {{
    entries = fs.readdirSync(dir, {{ withFileTypes: true }});
  }} catch (_) {{
    return;
  }}
  for (const entry of entries) {{
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {{
      walk(full);
      if (matches.length >= 100) return;
      continue;
    }}
    if (!entry.isFile()) continue;
    const normalized = full.split(path.sep).join("/");
    if (!globRegex.test(path.basename(normalized))) continue;
    try {{
      const lines = fs.readFileSync(full, "utf8").split(/\\r?\\n/);
      for (let i = 0; i < lines.length; i += 1) {{
        const line = lines[i];
        const ok = regex ? regex.test(line) : (caseSensitive ? line.includes(needle) : line.toLowerCase().includes(needle));
        if (ok) {{
          matches.push(`${{full}}:${{i + 1}}:${{line}}`);
          if (matches.length >= 100) return;
        }}
      }}
    }} catch (_) {{}}
  }}
}}

walk(directory);
console.log(matches.length ? matches.join("\\n") : `No matches found for '${{query}}' in ${{directory}}/${{pattern}}`);
""".strip()
            fallbacks.extend([
                {"name": "run_shell", "args": {"command": shell_cmd}},
                {"name": "run_python", "args": {"code": py_code}},
                {"name": "run_javascript", "args": {"code": js_code}},
            ])

        elif name == "list_directory":
            path = args.get("path", ".")
            shell_cmd = f"ls -la {shell_quote(path)}"
            py_code = f"""
from pathlib import Path
p = Path({ascii_json(path)}).expanduser()
if not p.exists():
    print(f"Error: path not found: {{p}}")
elif not p.is_dir():
    print(f"Error: not a directory: {{p}}")
else:
    entries = sorted(p.iterdir(), key=lambda item: item.name.lower())
    lines = [f"{{'📁' if item.is_dir() else '📄'}} {{item.name}}{{'/' if item.is_dir() else ''}}" for item in entries[:200]]
    if len(entries) > 200:
        lines.append(f"... and {{len(entries)-200}} more")
    print("\\n".join(lines) if lines else f"No entries in {{p}}")
""".strip()
            js_code = f"""
const fs = require("fs");
const path = require("path");
const dir = path.resolve({ascii_json(path)});
if (!fs.existsSync(dir)) {{
  console.log(`Error: path not found: ${{dir}}`);
}} else if (!fs.statSync(dir).isDirectory()) {{
  console.log(`Error: not a directory: ${{dir}}`);
}} else {{
  const entries = fs.readdirSync(dir, {{ withFileTypes: true }})
    .sort((a, b) => a.name.localeCompare(b.name))
    .slice(0, 200);
  const lines = entries.map(item => `${{item.isDirectory() ? "📁" : "📄"}} ${{item.name}}${{item.isDirectory() ? "/" : ""}}`);
  console.log(lines.length ? lines.join("\\n") : `No entries in ${{dir}}`);
}}
""".strip()
            fallbacks.extend([
                {"name": "run_shell", "args": {"command": shell_cmd}},
                {"name": "run_python", "args": {"code": py_code}},
                {"name": "run_javascript", "args": {"code": js_code}},
            ])

        elif name == "read_file":
            path = args.get("path", "")
            resolved = resolve_file_path(path) or path
            shell_cmd = (
                f"if [ -f {shell_quote(resolved)} ]; then "
                f"if [ $(wc -c < {shell_quote(resolved)}) -gt 500000 ]; then "
                f"sed -n '1,250p' {shell_quote(resolved)}; "
                f"else cat {shell_quote(resolved)}; fi; "
                "else "
                f"printf '%s\\n' 'Error: file not found: {resolved}'; "
                "fi"
            )
            py_code = f"""
from pathlib import Path
p = Path({ascii_json(resolved)}).expanduser()
if not p.exists():
    print(f"Error: file not found: {{p}}")
elif p.stat().st_size > 500000:
    print(p.read_text(encoding="utf-8", errors="replace")[:50000] + "\\n\\n[... truncated]")
else:
    print(p.read_text(encoding="utf-8", errors="replace"))
""".strip()
            js_code = f"""
const fs = require("fs");
const path = require("path");
const file = path.resolve({ascii_json(resolved)});
if (!fs.existsSync(file)) {{
  console.log(`Error: file not found: ${{file}}`);
}} else {{
  const text = fs.readFileSync(file, "utf8");
  console.log(text.length > 50000 ? text.slice(0, 50000) + "\\n\\n[... truncated]" : text);
}}
""".strip()
            fallbacks.extend([
                {"name": "run_shell", "args": {"command": shell_cmd}},
                {"name": "run_python", "args": {"code": py_code}},
                {"name": "run_javascript", "args": {"code": js_code}},
            ])

        elif name == "read_document":
            file_path = args.get("file_path", "")
            max_chars = int(args.get("max_chars", 10000))
            ext = Path(file_path).suffix.lower()
            text_exts = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".html", ".css", ".js", ".ts", ".tsx", ".jsx", ".xml"}
            if ext in text_exts:
                fallbacks.append({"name": "read_file", "args": {"path": file_path}})
            elif ext == ".docx":
                py_code = f"""
from zipfile import ZipFile
from xml.etree import ElementTree as ET
path = {ascii_json(file_path)}
max_chars = {max_chars}
with ZipFile(path) as zf:
    data = zf.read("word/document.xml")
root = ET.fromstring(data)
ns = {ascii_json({"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"})}
parts = [node.text for node in root.findall(".//w:t", ns) if node.text]
text = "\\n".join(parts)
print(text[:max_chars] + ("\\n\\n[... truncated]" if len(text) > max_chars else ""))
""".strip()
                fallbacks.append({"name": "run_python", "args": {"code": py_code}})
            elif ext == ".pdf":
                shell_cmd = (
                    f"if command -v pdftotext >/dev/null 2>&1; then "
                    f"pdftotext {shell_quote(file_path)} - | head -c {max_chars}; "
                    "else "
                    f"strings {shell_quote(file_path)} | head -c {max_chars}; "
                    "fi"
                )
                py_code = f"""
from pathlib import Path
path = Path({ascii_json(file_path)}).expanduser()
data = path.read_bytes()
text = data.decode("latin-1", errors="ignore")
print(text[:{max_chars}] + ("\\n\\n[... truncated]" if len(text) > {max_chars} else ""))
""".strip()
                fallbacks.extend([
                    {"name": "run_shell", "args": {"command": shell_cmd}},
                    {"name": "run_python", "args": {"code": py_code}},
                ])

        elif name == "fetch_url":
            url = args.get("url", "")
            max_chars = int(args.get("max_chars", 8000))
            shell_cmd = (
                f"curl -L --max-time 20 -A {shell_quote('Mozilla/5.0 ApexForge-Swarm/1.0')} "
                f"{shell_quote(url)} | head -c {max_chars}"
            )
            py_code = f"""
import urllib.request
url = {ascii_json(url)}
max_chars = {max_chars}
req = urllib.request.Request(url, headers={{"User-Agent": "Mozilla/5.0 ApexForge-Swarm/1.0"}})
with urllib.request.urlopen(req, timeout=30) as resp:
    text = resp.read().decode("utf-8", errors="replace")
print(text[:max_chars] + ("\\n\\n[... truncated]" if len(text) > max_chars else ""))
""".strip()
            js_code = f"""
const url = {ascii_json(url)};
const maxChars = {max_chars};
fetch(url, {{
  headers: {{ "User-Agent": "Mozilla/5.0 ApexForge-Swarm/1.0" }}
}})
  .then(resp => resp.text())
  .then(text => {{
    console.log(text.length > maxChars ? text.slice(0, maxChars) + "\\n\\n[... truncated]" : text);
  }})
  .catch(err => {{
    console.error(String(err));
    process.exit(1);
  }});
""".strip()
            fallbacks.extend([
                {"name": "run_shell", "args": {"command": shell_cmd}},
                {"name": "run_python", "args": {"code": py_code}},
                {"name": "run_javascript", "args": {"code": js_code}},
            ])

        elif name == "web_search":
            query = args.get("query", "")
            max_results = int(args.get("max_results", 5))
            ddg_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
            fallbacks.extend([
                {"name": "fetch_url", "args": {"url": ddg_url, "max_chars": max(6000, max_results * 1800)}},
                {"name": "run_shell", "args": {"command": f"curl -L --max-time 20 {shell_quote(ddg_url)} | head -c 12000"}},
            ])

        elif name == "edit_file":
            path = args.get("path", "")
            action = args.get("action", "")
            content = args.get("content")
            find = args.get("find")
            replace = args.get("replace")
            py_code = f"""
from pathlib import Path
path = Path({ascii_json(path)}).expanduser()
action = {ascii_json(action)}
content = {ascii_json(content)}
find = {ascii_json(find)}
replace = {ascii_json(replace)}
if not path.exists():
    raise SystemExit(f"Error: file not found: {{path}}")
data = path.read_text(encoding="utf-8")
if action == "append":
    if content is None:
        raise SystemExit("Error: content required for append")
    path.write_text(data + content, encoding="utf-8")
    print(f"Appended to {{path}}")
elif action == "prepend":
    if content is None:
        raise SystemExit("Error: content required for prepend")
    path.write_text(content + data, encoding="utf-8")
    print(f"Prepended to {{path}}")
elif action == "replace":
    if find is None or replace is None:
        raise SystemExit("Error: find and replace required for action 'replace'")
    path.write_text(data.replace(find, replace), encoding="utf-8")
    print(f"Replaced occurrences in {{path}}")
else:
    raise SystemExit(f"Error: invalid action '{{action}}'")
""".strip()
            js_code = f"""
const fs = require("fs");
const path = require("path");
const file = path.resolve({ascii_json(path)});
const action = {ascii_json(action)};
const content = {ascii_json(content)};
const find = {ascii_json(find)};
const replace = {ascii_json(replace)};
if (!fs.existsSync(file)) {{
  console.log(`Error: file not found: ${{file}}`);
  process.exit(1);
}}
let data = fs.readFileSync(file, "utf8");
if (action === "append") {{
  if (content === null) {{
    console.log("Error: content required for append");
    process.exit(1);
  }}
  fs.writeFileSync(file, data + content, "utf8");
  console.log(`Appended to ${{file}}`);
}} else if (action === "prepend") {{
  if (content === null) {{
    console.log("Error: content required for prepend");
    process.exit(1);
  }}
  fs.writeFileSync(file, content + data, "utf8");
  console.log(`Prepended to ${{file}}`);
}} else if (action === "replace") {{
  if (find === null || replace === null) {{
    console.log("Error: find and replace required for action 'replace'");
    process.exit(1);
  }}
  fs.writeFileSync(file, data.split(find).join(replace), "utf8");
  console.log(`Replaced occurrences in ${{file}}`);
}} else {{
  console.log(`Error: invalid action '${{action}}'`);
  process.exit(1);
}}
""".strip()
            fallbacks.extend([
                {"name": "run_python", "args": {"code": py_code}},
                {"name": "run_javascript", "args": {"code": js_code}},
            ])

        return fallbacks
