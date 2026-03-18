#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           OVERWRITE CODE  —  AI Folder Agent CLI            ║
╚══════════════════════════════════════════════════════════════╝

Requirements:
    pip install requests rich

Usage:
    python overwrite_code.py
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
    from rich.table import Table
    from rich.rule import Rule
    from rich.markup import escape
    import requests
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Install requirements: pip install requests rich", file=sys.stderr)
    sys.exit(1)

console = Console()

AVAILABLE_MODELS: Dict[str, str] = {
    "claude-opus-4-6": "claude-opus-4-6",
}

DEFAULT_MODEL = "claude-opus-4-6"

async def lm_chat_stream(model_name: str, messages: List[Dict], proxy=None, timeout=0):
    url = "https://overwrite-code-backend.onrender.com/api/chat"
    prompt_text = ""
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
        prompt_text += f"[{role}]\n{content}\n\n"
        
    payload = {
        "prompt": prompt_text.strip(),
        "max_tokens": 150000
    }
    
    try:
        response = await asyncio.to_thread(requests.post, url, json=payload, stream=True)
        if response.status_code != 200:
            yield ("error", f"HTTP {response.status_code}: {response.text}")
            return
            
        for line in response.iter_lines():
            if not line:
                continue
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data_str = line[6:]
                if data_str.strip() == '[DONE]':
                    yield ("done", None)
                    break
                try:
                    data = json.loads(data_str)
                    if data.get("type") == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield ("text", delta.get("text", ""))
                    elif data.get("type") == "error":
                        yield ("error", data.get("error", "Unknown error"))
                        break
                except Exception:
                    pass
        yield ("done", None)
    except Exception as e:
        yield ("error", str(e))

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
        
        if content.strip().startswith("```"):
            lines = content.strip().split("\n")
            if lines[0].startswith("```"): lines.pop(0)
            if lines and lines[-1].startswith("```"): lines.pop(-1)
            content = "\n".join(lines) + "\n"
            
        result = write_file(path, content)
        return result
    elif t == "delete_path":
        path = resolve_path(folder_path, action["path"])
        if Path(path).resolve() == Path(folder_path).resolve():
            return "[Error: Cannot delete the root workspace folder!]"
            
        return delete_item(path)
    return ""

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
    "   ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
    "(150k token limit per msg btw)"
]

def print_banner():
    console.print()
    for i, line in enumerate(BANNER_LINES):
        if i < 6:
            colors =["bold red", "bold red", "bold bright_red", "bold red", "bold bright_red", "bold red"]
            col = colors[i % len(colors)]
        else:
            colors2 =["bold yellow", "bold bright_yellow", "bold yellow", "bold bright_yellow", "bold yellow", "bold bright_yellow"]
            col = colors2[(i-7) % len(colors2)]
        console.print(f"[{col}]{line}[/{col}]")
    console.print()
    console.print()

def settings_menu(current_model: str, folder_path: str) -> tuple[str, str]:
    console.print()
    console.print(Rule("[bold cyan]SETTINGS[/bold cyan]", style="cyan"))
    console.print()

    table = Table(title="Available Models", border_style="dim", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Model", style="cyan")
    table.add_column("", style="green")
    model_list = list(AVAILABLE_MODELS.keys())
    for i, m in enumerate(model_list, 1):
        marker = "< current" if m == current_model else ""
        table.add_row(str(i), m, marker)
    console.print(table)

    choice = Prompt.ask("\n[cyan]Enter model number or name (Enter to keep current)[/cyan]", default="").strip()
    if choice:
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(model_list):
                current_model = model_list[idx]
        elif choice in AVAILABLE_MODELS:
            current_model = choice
        else:
            console.print("[yellow]Model not found, keeping current.[/yellow]")

    new_folder = Prompt.ask("[cyan]Folder path (Enter to keep current)[/cyan]", default="").strip()
    if new_folder and Path(new_folder).exists():
        folder_path = str(Path(new_folder).resolve())
    elif new_folder:
        console.print("[yellow]Path not found, keeping current.[/yellow]")

    console.print()
    console.print(f"[green]OK Model:[/green] [bold]{current_model}[/bold]")
    console.print(f"[green]OK Folder:[/green] [bold]{folder_path}[/bold]")
    console.print(Rule(style="dim"))
    return current_model, folder_path

async def chat_loop(folder_path: str, model: str = DEFAULT_MODEL):
    conversation_messages: List[Dict] =[]
    ai_memory = ""

    console.print(Rule("[bold green]Session started[/bold green]", style="green"))
    console.print(f"[green]Model:[/green][bold cyan]{model}[/bold cyan]")
    console.print(f"[green]Folder:[/green][bold]{folder_path}[/bold]")
    console.print()
    console.print("[dim]Type your message. Commands:[/dim]")
    console.print("[dim]  settings  -> change model / folder[/dim]")
    console.print("[dim]  clear     -> clear conversation[/dim]")
    console.print("[dim]  tree      -> show folder tree[/dim]")
    console.print("[dim]  exit/quit -> quit[/dim]")
    console.print(Rule(style="dim"))
    console.print()

    system_prompt = "You are an expert autonomous AI file editor. You ONLY use XML tags to edit and delete files and folders."

    while True:
        try:
            user_input = Prompt.ask("[bold bright_white]You[/bold bright_white]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye![/dim]")
            break

        if not user_input:
            continue

        lw = user_input.lower()
        if lw in ("exit", "quit", "q"):
            console.print("\n[dim]Bye![/dim]")
            break
        if lw == "clear":
            conversation_messages.clear()
            ai_memory = ""
            console.print("[dim]Conversation cleared.[/dim]")
            continue
        if lw == "tree":
            console.print(Panel(list_folder(folder_path), title="Folder Tree", border_style="dim"))
            continue
        if lw == "settings":
            model, folder_path = settings_menu(model, folder_path)
            continue

        conversation_messages.append({"role": "user", "content": user_input})

        tree = list_folder(folder_path)
        contents = get_all_file_contents(folder_path)

        enforcement = f"""[SYSTEM CONTEXT & STRICT RULES]
CURRENT FOLDER STRUCTURE:
{tree}

CURRENT FILE CONTENTS:
{contents}

CRITICAL REMINDER: 
1. DO NOT make a plan. DO NOT ask for confirmation. JUST EXECUTE the requested file/folder changes.
2. Use ONLY <write_file path="...">...</write_file> or <delete path="..." />. (The delete tag works on both files AND folders).
3. NEVER wrap XML tags in markdown (```). Do not output XML tags as examples.
4. You can use <memory>your notes</memory> to remind yourself of what you want to change in the next response. Do NOT remember code, only ideas.
"""
        if ai_memory:
            enforcement += f"\n[MEMORY FROM PREVIOUS TURN]\n{ai_memory}\n"

        messages_to_send =[{"role": "system", "content": system_prompt}] + list(conversation_messages)
        last_msg = messages_to_send[-1].copy()
        last_msg["content"] += "\n\n" + enforcement
        messages_to_send[-1] = last_msg

        console.print()
        console.print(f"[bold bright_magenta]AI[/bold bright_magenta][dim]({model})[/dim]")
            
        console.print(Rule(style="dim magenta"))
        console.print("[dim italic]Press Ctrl+C to stop generation[/dim italic]")

        response_buffer =[]
        status_text = ""

        def clear_status():
            nonlocal status_text
            if status_text:
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                status_text = ""

        try:
            async for kind, content in lm_chat_stream(model, messages_to_send, timeout=0):
                if kind == "status":
                    clear_status()
                    sys.stdout.write(f"\r  WAIT: {content}")
                    sys.stdout.flush()
                    status_text = content
                elif kind == "text":
                    clear_status()
                    response_buffer.append(content)
                    print(content, end="", flush=True)
                elif kind == "done":
                    clear_status()
                    print()
                    break
                elif kind == "error":
                    clear_status()
                    console.print(f"\n[red]Error: {content}[/red]")
                    break

        except KeyboardInterrupt:
            clear_status()
            console.print("\n[bold yellow]  Generation stopped by user! (Ctrl+C)[/bold yellow]")
        except Exception as e:
            clear_status()
            console.print(f"\n[red]Stream error: {e}[/red]")

        console.print(Rule(style="dim magenta"))

        full_response = "".join(response_buffer)

        mem_match = re.search(r'<memory>(.*?)</memory>', full_response, re.DOTALL | re.IGNORECASE)
        if mem_match:
            ai_memory = mem_match.group(1).strip()
            console.print(f"[dim]Memory saved for next turn.[/dim]")
        else:
            ai_memory = ""

        open_count = len(re.findall(r'<(write_file|file|write)\s+path=', full_response, re.IGNORECASE))
        close_count = len(re.findall(r'</(write_file|file|write)>', full_response, re.IGNORECASE))
        if open_count > close_count:
            full_response += "\n</write_file>"
            console.print("[dim]Auto-closed interrupted file write to save partial content.[/dim]")

        actions = extract_actions(full_response)
        if actions:
            console.print()
            console.print(Rule("[cyan]AI Executed Actions[/cyan]", style="cyan"))
            for action in actions:
                console.print(f"[cyan]> {action['type']}[/cyan]", end=" ")
                
                if action["type"] == "write_file":
                    path = resolve_path(folder_path, action["path"])
                    console.print(f"[dim]{path}[/dim]")
                    preview = action["content"][:200].replace("\n", "\n")
                    console.print(Panel(
                        f"[dim]{escape(preview)}{'...' if len(action['content'])>200 else ''}[/dim]",
                        title=f"[yellow]Write: {action['path']}[/yellow]",
                        border_style="yellow",
                    ))
                elif action["type"] == "delete_path":
                    path = resolve_path(folder_path, action["path"])
                    console.print(f"[dim]{path}[/dim]")
                
                execute_action(action, folder_path)
            
            console.print(Rule(style="dim cyan"))

        conversation_messages.append({"role": "assistant", "content": full_response})
        console.print()

async def main():
    print_banner()

    while True:
        try:
            folder_raw = Prompt.ask(
                "[bold cyan]Enter project folder path[/bold cyan]"
            ).strip().strip('"').strip("'")
            folder_path = str(Path(folder_raw).expanduser().resolve())
            if Path(folder_path).is_dir():
                break
            console.print(f"[red]  X Not a valid directory: {folder_path}[/red]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Interrupted.[/dim]")
            return

    console.print(f"\n[green]OK Folder:[/green][bold]{folder_path}[/bold]")

    console.print()
    console.print(Panel(
        list_folder(folder_path, max_depth=2),
        title=f"[bold][DIR] {folder_path}[/bold]",
        border_style="dim",
        padding=(0, 1),
    ))

    console.print()
    console.print(f"[dim]Default model:[bold]{DEFAULT_MODEL}[/bold]  (type 'settings' to change)[/dim]")
    model = DEFAULT_MODEL

    console.print()
    await chat_loop(folder_path, model)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
