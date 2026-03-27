#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           OVERWRITE CODE  —  AI Folder Agent CLI            ║
╚══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich.markup import escape
    import requests
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Install requirements: pip install requests rich", file=sys.stderr)
    sys.exit(1)

console = Console()

# =====================================================================
# 1. NEW PROXY BACKEND CONNECTION
# =====================================================================
async def lm_chat_stream(messages: List[Dict], timeout=0):
    """Connects to your Anthropic-compatible Render proxy using SSE Streaming."""
    url = "https://claude-oppusy.onrender.com/v1/messages"
    
    system_text = ""
    anthropic_msgs = []
    
    for m in messages:
        if m["role"] == "system":
            system_text += m["content"] + "\n\n"
        else:
            anthropic_msgs.append({"role": m["role"], "content": m["content"]})
            
    payload = {
        "model": "claude-3-7-sonnet-20250219", 
        "messages": anthropic_msgs,
        "system": system_text.strip(),
        "stream": True
    }
        
    try:
        response = await asyncio.to_thread(requests.post, url, json=payload, stream=True)
        
        if response.status_code != 200:
            yield ("error", f"HTTP {response.status_code}: {response.text}")
            return
            
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]": break
                try:
                    event = json.loads(data_str)
                    if event.get("type") == "content_block_delta":
                        text = event["delta"].get("text", "")
                        if text: yield ("text", text)
                except json.JSONDecodeError:
                    pass
                    
        yield ("done", None)
    except Exception as e:
        yield ("error", str(e))


# =====================================================================
# 2. FILE SYSTEM TOOLS
# =====================================================================
def list_folder(path: str, max_depth: int = 3, _depth: int = 0) -> str:
    p = Path(path)
    if not p.exists(): return f"[Path does not exist: {path}]"
    lines =[]
    indent = "  " * _depth
    try:
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
    except PermissionError:
        return f"{indent}[Permission denied]"
    for item in items[:60]:
        if item.is_dir():
            if item.name in (".git", "node_modules", "venv", ".venv", "__pycache__", ".idea"): continue
            lines.append(f"{indent}[DIR] {item.name}/")
            if _depth < max_depth - 1:
                lines.append(list_folder(str(item), max_depth, _depth + 1))
        else:
            size = ""
            try:
                s = item.stat().st_size
                size = f" ({s:,} B)" if s < 10000 else f" ({s//1024:,} KB)"
            except Exception:
                pass
            lines.append(f"{indent}[FILE] {item.name}{size}")
    if len(list(p.iterdir())) > 60:
        lines.append(f"{indent}... (truncated)")
    return "\n".join(lines)

def get_all_file_contents(folder_path: str, max_files=40, max_chars=80000) -> str:
    skip_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__", "build", "dist", ".idea"}
    output =[]
    total_chars = 0
    
    for root, dirs, files in os.walk(folder_path):
        dirs[:] =[d for d in dirs if d not in skip_dirs and not d.startswith('.')]
        for file in files:
            if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pyc', '.exe', '.dll', '.bin', '.zip')):
                continue
                
            if total_chars > max_chars or len(output) > (max_files * 4): 
                output.append("\n[... Remaining files truncated due to context size limits ...]")
                return "\n".join(output)
            
            file_path = Path(root) / file
            try:
                content = file_path.read_text(encoding="utf-8")
                rel_path = file_path.relative_to(folder_path)
                output.append(f"\n--- FILE: {rel_path} ---")
                output.append(content)
                output.append("-" * 40)
                total_chars += len(content)
            except UnicodeDecodeError:
                pass
            except Exception:
                pass
    
    return "\n".join(output) if output else "[No text files found in directory]"

def write_file(path: str, content: str) -> str:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return f"Written: {path}"
    except Exception as e:
        return f"[Error writing file: {e}]"

def delete_item(path: str) -> str:
    try:
        p = Path(path)
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
                return f"Deleted directory: {path}"
            else:
                p.unlink()
                return f"Deleted file: {path}"
        return f"Not found: {path}"
    except Exception as e:
        return f"[Error deleting: {e}]"

def resolve_path(base: str, path: str) -> str:
    p = Path(path)
    if p.is_absolute(): return str(p)
    return str(Path(base) / p)

ACTION_PATTERNS = {
    "write_file":   re.compile(r'<(write_file|file|write)\s+path=["\']([^"\']+)["\']\s*>([\s\S]*?)</\1>', re.DOTALL | re.IGNORECASE),
    "delete_path":  re.compile(r'<(delete_file|delete_folder|delete_dir|delete|rm)\s+path=["\']([^"\']+)["\']\s*/>', re.IGNORECASE),
}

def extract_actions(text: str) -> List[Dict]:
    actions = []
    for af in ACTION_PATTERNS["write_file"].finditer(text):
        actions.append({"type": "write_file", "path": af.group(2), "content": af.group(3), "pos": af.start()})
    for af in ACTION_PATTERNS["delete_path"].finditer(text):
        actions.append({"type": "delete_path", "path": af.group(2), "pos": af.start()})
    actions.sort(key=lambda x: x["pos"])
    return actions

def execute_action(action: Dict, folder_path: str) -> str:
    t = action["type"]
    if t == "write_file":
        path = resolve_path(folder_path, action["path"])
        content = action["content"]
        if content.startswith("\n"): content = content[1:]
        
        # Clean stray markdown markers from continuation boundaries
        content = re.sub(r'^```[a-zA-Z]*\n', '', content)
        content = re.sub(r'\n```$', '', content)
            
        return write_file(path, content)
    elif t == "delete_path":
        path = resolve_path(folder_path, action["path"])
        if Path(path).resolve() == Path(folder_path).resolve():
            return "[Error: Cannot delete the root workspace folder!]"
        return delete_item(path)
    return ""

# =====================================================================
# 3. UI AND CHAT LOOP (WITH AUTO-CONTINUE)
# =====================================================================
BANNER_LINES =[
    "  ██████╗ ██╗   ██╗███████╗██████╗ ██╗    ██╗██████╗ ██╗████████╗███████╗",
    "  ██╔══██╗██║   ██║██╔════╝██╔══██╗██║    ██║██╔══██╗██║╚══██╔══╝██╔════╝",
    "  ██║  ██║██║   ██║█████╗  ██████╔╝██║ █╗ ██║██████╔╝██║   ██║   █████╗  ",
    "  ██║  ██║╚██╗ ██╔╝██╔══╝  ██╔══██╗██║███╗██║██╔══██╗██║   ██║   ██╔══╝  ",
    "  ██████╔╝ ╚████╔╝ ███████╗██║  ██║╚███╔███╔╝██║  ██║██║   ██║   ███████╗",
    "  ╚═════╝   ╚═══╝  ╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝   ╚═╝   ╚══════╝",
    "",
    "   ██████╗ ██████╗ ██████╗ ███████╗",
    "  ██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    "  ██║     ██║   ██║██║  ██║█████╗  ",
    "  ██║     ██║   ██║██║  ██║██╔══╝  ",
    "  ╚██████╗╚██████╔╝██████╔╝███████╗",
    "   ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝"
]

def print_banner():
    console.print()
    for i, line in enumerate(BANNER_LINES):
        col = "bold red" if i < 6 and i % 2 == 0 else "bold bright_red" if i < 6 else "bold yellow" if i % 2 == 0 else "bold bright_yellow"
        console.print(f"[{col}]{line}[/{col}]")
    console.print()

def settings_menu(folder_path: str) -> str:
    console.print(Rule("[bold cyan]SETTINGS[/bold cyan]", style="cyan"))
    new_folder = Prompt.ask("[cyan]Folder path (Enter to keep current)[/cyan]", default="").strip()
    if new_folder and Path(new_folder).exists():
        folder_path = str(Path(new_folder).resolve())
    console.print(f"[green]OK Folder:[/green][bold]{folder_path}[/bold]\n")
    return folder_path

async def chat_loop(folder_path: str):
    conversation_messages: List[Dict] =[]
    ai_memory = ""

    console.print(Rule("[bold green]Session started[/bold green]", style="green"))
    console.print(f"[green]Folder:[/green][bold]{folder_path}[/bold]")
    console.print("[dim]Type your message. Commands: settings, clear, tree, exit[/dim]")
    console.print(Rule(style="dim"))

    system_prompt = "You are an expert autonomous AI file editor. You ONLY use XML tags to edit and delete files and folders."

    while True:
        console.print()
        try:
            user_input = Prompt.ask("[bold bright_white]You[/bold bright_white]").strip()
        except (KeyboardInterrupt, EOFError): break
        if not user_input: continue
        
        lw = user_input.lower()
        if lw in ("exit", "quit", "q"): break
        if lw == "clear":
            conversation_messages.clear()
            ai_memory = ""
            console.print("[dim]Conversation cleared.[/dim]")
            continue
        if lw == "tree":
            console.print(Panel(list_folder(folder_path), title="Folder Tree", border_style="dim"))
            continue
        if lw == "settings":
            folder_path = settings_menu(folder_path)
            continue

        conversation_messages.append({"role": "user", "content": user_input})

        enforcement = f"""[SYSTEM CONTEXT & STRICT RULES]
CURRENT FOLDER STRUCTURE:
{list_folder(folder_path)}

CURRENT FILE CONTENTS:
{get_all_file_contents(folder_path)}

CRITICAL REMINDER: 
1. DO NOT make a plan. DO NOT ask for confirmation. JUST EXECUTE the requested file/folder changes.
2. Use ONLY <write_file path="...">...</write_file> or <delete path="..." />.
3. NEVER wrap XML tags in markdown (```).
4. You can use <memory>your notes</memory> to remind yourself of ideas.
"""
        if ai_memory: enforcement += f"\n[MEMORY]\n{ai_memory}\n"

        messages_to_send =[{"role": "system", "content": system_prompt}] + list(conversation_messages)
        messages_to_send[-1]["content"] += "\n\n" + enforcement

        console.print(f"\n[bold bright_magenta]AI[/bold bright_magenta] [dim](Opus 4.6)[/dim]")
        console.print(Rule(style="dim magenta"))

        # STATE FOR CONTINUATION LOGIC
        full_response = ""
        current_messages = messages_to_send.copy()
        
        display_state = {'buffer': '', 'in_tag': False, 'filename': '', 'lines': 0}
        continuation_count = 0
        max_continuations = 5

        # AUTO-CONTINUE LOOP
        while continuation_count <= max_continuations:
            chunk_response = ""
            try:
                async for kind, content in lm_chat_stream(current_messages, timeout=0):
                    if kind == "text":
                        # If AI hallucinates markdown on a continuation, strip it silently
                        if continuation_count > 0 and len(chunk_response) < 10 and "```" in content:
                            content = content.replace("```python", "").replace("```", "")
                            
                        chunk_response += content
                        display_state['buffer'] += content
                        
                        while True:
                            if not display_state['in_tag']:
                                match = re.search(r'<(write_file|file|write)\s+path=["\']([^"\']+)["\']\s*>', display_state['buffer'], re.IGNORECASE)
                                if match:
                                    sys.stdout.write(display_state['buffer'][:match.start()])
                                    sys.stdout.flush()
                                    display_state['in_tag'] = True
                                    display_state['filename'] = match.group(2)
                                    display_state['lines'] = 0
                                    sys.stdout.write(f"\n\033[96m⚙️  Writing {display_state['filename']}...\033[0m\n")
                                    display_state['buffer'] = display_state['buffer'][match.end():]
                                else:
                                    if len(display_state['buffer']) > 20:
                                        sys.stdout.write(display_state['buffer'][:-20])
                                        sys.stdout.flush()
                                        display_state['buffer'] = display_state['buffer'][-20:]
                                    break
                            else:
                                match = re.search(r'</(write_file|file|write)>', display_state['buffer'], re.IGNORECASE)
                                if match:
                                    file_chunk = display_state['buffer'][:match.start()]
                                    display_state['lines'] += file_chunk.count('\n')
                                    sys.stdout.write(f"\r\033[K  └─> \033[92m✅ Saved {display_state['lines']} lines.\033[0m\n")
                                    sys.stdout.flush()
                                    display_state['in_tag'] = False
                                    display_state['buffer'] = display_state['buffer'][match.end():]
                                else:
                                    if len(display_state['buffer']) > 20:
                                        file_chunk = display_state['buffer'][:-20]
                                        display_state['lines'] += file_chunk.count('\n')
                                        display_state['buffer'] = display_state['buffer'][-20:]
                                        sys.stdout.write(f"\r\033[K  └─> ✍️  Generating... {display_state['lines']} lines")
                                        sys.stdout.flush()
                                    break
                                    
                    elif kind == "error":
                        console.print(f"\n[red]Error: {content}[/red]")
                        break
            except KeyboardInterrupt:
                console.print("\n[bold yellow]Generation stopped! (Ctrl+C)[/bold yellow]")
                break
                
            full_response += chunk_response
            
            # Check for Interruption
            open_tags = list(re.finditer(r'<(write_file|file|write)\s+path=["\']([^"\']+)["\']\s*>', full_response, re.IGNORECASE))
            close_tags = list(re.finditer(r'</(write_file|file|write)>', full_response, re.IGNORECASE))
            
            if len(open_tags) > len(close_tags):
                continuation_count += 1
                filename = open_tags[-1].group(2)
                sys.stdout.write(f"\r\033[K  └─> \033[93m⚠️ Limit reached. Auto-continuing {filename}... ({continuation_count}/{max_continuations})\033[0m")
                sys.stdout.flush()
                
                # Append context to push it forward
                current_messages.append({"role": "assistant", "content": chunk_response})
                current_messages.append({"role": "user", "content": f"CRITICAL: You hit the output limit while writing '{filename}'. Please continue writing the file content EXACTLY where you left off. DO NOT write any conversational text, DO NOT output a new <write_file> tag, and DO NOT use markdown like ```python. Just output the exact remaining raw characters of the code and finish with </write_file>."})
            else:
                break # Finished writing all files!

        # Flush remaining text
        if display_state['buffer'] and not display_state['in_tag']:
            sys.stdout.write(display_state['buffer'])
        elif display_state['in_tag']:
            sys.stdout.write(f"\r\033[K  └─> \033[93m⚠️ Interrupted at {display_state['lines']} lines.\033[0m\n")
            full_response += "\n</write_file>"
            
        sys.stdout.flush()
        print()
        console.print(Rule(style="dim magenta"))

        # Save Memory & Execute Files
        mem_match = re.search(r'<memory>(.*?)</memory>', full_response, re.DOTALL | re.IGNORECASE)
        ai_memory = mem_match.group(1).strip() if mem_match else ""

        actions = extract_actions(full_response)
        if actions:
            console.print("[dim cyan]Executing changes...[/dim cyan]")
            for action in actions:
                result = execute_action(action, folder_path)
                if result: console.print(f"  [green]✔ {result}[/green]")
            console.print()

        conversation_messages.append({"role": "assistant", "content": full_response})

async def main():
    print_banner()
    while True:
        try:
            folder_raw = Prompt.ask("[bold cyan]Enter project folder path[/bold cyan]").strip().strip('"').strip("'")
            folder_path = str(Path(folder_raw).expanduser().resolve())
            if Path(folder_path).is_dir(): break
            console.print(f"[red]  X Not a valid directory[/red]")
        except (KeyboardInterrupt, EOFError): return

    console.print(f"\n[green]OK Folder:[/green][bold]{folder_path}[/bold]\n")
    await chat_loop(folder_path)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
