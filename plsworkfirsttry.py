#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           OVERWRITE CODE  —  AI Folder Agent CLI            ║
╚══════════════════════════════════════════════════════════════╝

Requirements:
    pip install curl_cffi zendriver platformdirs requests rich

Usage:
    python overwrite_code.py
"""

from __future__ import annotations

import asyncio
import hashlib
import html as _html
import json
import os
import re
import secrets
import shutil
import sys
import time
from abc import abstractmethod
from functools import partialmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.rule import Rule
    from rich.markup import escape
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Install rich:  pip install rich", file=sys.stderr)
    sys.exit(1)

console = Console()

try:
    import curl_cffi
    from curl_cffi.requests import AsyncSession, Response as CurlResponse
    try:
        from curl_cffi import CurlMime
        _HAS_CURL_MIME = True
    except ImportError:
        _HAS_CURL_MIME = False
    HAS_CURL = True
except ImportError:
    HAS_CURL = False
    _HAS_CURL_MIME = False

try:
    import zendriver as nodriver
    from zendriver import cdp
    from zendriver.cdp.network import CookieParam
    HAS_NODRIVER = True
except ImportError:
    HAS_NODRIVER = False

try:
    from platformdirs import user_config_dir
    HAS_PLATFORMDIRS = True
except ImportError:
    HAS_PLATFORMDIRS = False

try:
    import brotli
    _HAS_BROTLI = True
except ImportError:
    _HAS_BROTLI = False

class G4FError(Exception): pass
class ModelNotFoundError(G4FError): pass
class MissingRequirementsError(G4FError): pass
class MissingAuthError(G4FError): pass
class ResponseStatusError(G4FError): pass
class CloudflareError(ResponseStatusError): pass
class RateLimitError(ResponseStatusError): pass

DEFAULT_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate" + (", br" if _HAS_BROTLI else ""),
    "accept-language": "en-US",
    "referer": "",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
}

COOKIES_DIR = str(Path.home() / ".overwrite_code" / "cookies")

AVAILABLE_MODELS: Dict[str, str] = {
    "gemini-2.5-pro":                        "0199f060-b306-7e1f-aeae-0ebb4e3f1122",
    "gemini-3-pro":                          "019a98f7-afcd-779f-8dcb-856cc3b3f078",
    "gemini-3-flash":                        "019b0ad8-856e-74fc-871c-86ccbb2b1d35",
    "gemini-2.5-flash":                      "0199f059-3877-7cfe-bc80-e01b1a4a83de",
    "gpt-5.1":                               "019a7ebf-0f3f-7518-8899-fca13e32d9dc",
    "gpt-5-high":                            "983bc566-b783-4d28-b24c-3c8b08eb1086",
    "gpt-4.1-2025-04-14":                    "14e9311c-94d2-40c2-8c54-273947e208b0",
    "o3-2025-04-16":                         "cb0f1e24-e8e9-4745-aabc-b926ffde7475",
    "o4-mini-2025-04-16":                    "f1102bbf-34ca-468f-a9fc-14bcf63f315b",
    "claude-opus-4-20250514":                "ee116d12-64d6-48a8-88e5-b2d06325cdd2",
    "claude-sonnet-4-20250514":              "ac44dd10-0666-451c-b824-386ccfea7bcc",
    "claude-sonnet-4-5-20250929":            "019a2d13-28a5-7205-908c-0a58de904617",
    "claude-opus-4-5-20251101":              "019adbec-8396-71cc-87d5-b47f8431a6a6",
    "claude-3-5-sonnet-20241022":            "f44e280a-7914-43ca-a25d-ecfcc5d48d09",
    "claude-haiku-4-5-20251001":             "0199e8e9-01ed-73e0-96ba-cf43b286bf10",
    "grok-4.1-thinking":                     "019a9389-a9d3-77a8-afbb-4fe4dd3d8630",
    "grok-4.1":                              "019a9389-a4d8-748d-9939-b4640198302e",
    "deepseek-v3.2-thinking":                "019adb32-bb7a-77eb-882f-b8e3aaa2b2fd",
    "deepseek-v3.2":                         "019adb32-b716-7591-9a2f-c6882973e340",
    "deepseek-v3-0324":                      "2f5253e4-75be-473c-bcfc-baeb3df0f8ad",
    "kimi-k2-thinking-turbo":                "019a59bc-8bb8-7933-92eb-fe143770c211",
    "qwen3-max-preview":                     "812c93cc-5f88-4cff-b9ca-c11a26599b0e",
    "qwq-32b":                               "885976d3-d178-48f5-a3f4-6e13e0718872",
    "llama-3.3-70b-instruct":                "dcbd7897-5a37-4a34-93f1-76a24c7bb028",
    "llama-4-maverick-17b-128e-instruct":    "b5ad3ab7-fc56-4ecd-8921-bd56b55c1159",
    "gemma-3-27b-it":                        "789e245f-eafe-4c72-b563-d135e93988fc",
    "claude-opus-4-6-thinking":              "019c2f86-74db-7cc3-baa5-6891bebb5999",
    "claude-opus-4-6":                       "019c2fac-13de-7550-a751-f5f593c77c72",
    "gemini-2.0-flash-001":                  "7a55108b-b997-4cff-a72f-5aa83beee918",
    "o3-mini":                               "c680645e-efac-4a81-b0af-da16902b2541",
    "mistral-large-3":                       "019acbac-df7c-73dc-9716-ebe040daaa4e",
}

DEFAULT_MODEL = "claude-opus-4-6-thinking"

class BrowserState:
    instance = None
    page = None
    lock: Optional[asyncio.Lock] = None
    impersonate: str = "chrome136"

    @classmethod
    def get_lock(cls) -> asyncio.Lock:
        if cls.lock is None:
            cls.lock = asyncio.Lock()
        return cls.lock

def _ensure_dir():
    Path(COOKIES_DIR).mkdir(parents=True, exist_ok=True)

def _get_cache_file() -> Path:
    _ensure_dir()
    return Path(COOKIES_DIR) / "auth_LMArena.json"

def uuid7() -> str:
    ts = int(time.time() * 1000)
    ra = secrets.randbits(12)
    rb = secrets.randbits(62)
    u = ts << 80
    u |= (0x7000 | ra) << 64
    u |= (0x8000000000000000 | rb)
    h = f"{u:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

def merge_cookies(cookies, response) -> dict:
    if cookies is None: cookies = {}
    if hasattr(response.cookies, "jar"):
        for c in response.cookies.jar:
            cookies[c.name] = c.value
    else:
        for k, v in response.cookies.items():
            cookies[k] = v
    return cookies

def _is_cloudflare(t: str) -> bool:
    return any(x in t for x in["Generated by cloudfront", "cf-spinner-please-wait",
                                  "Attention Required! | Cloudflare", "cf-cloudflare-status",
                                  "cf-please-wait", "Just a moment..."])

async def raise_for_status(response, message=None):
    if response.ok: return
    ct = response.headers.get("content-type", "")
    if message is None:
        if ct.startswith("application/json"):
            try:
                d = await response.json()
                err = d.get("error")
                message = err.get("message") if isinstance(err, dict) else d.get("message", d)
            except Exception:
                message = await response.text()
        else:
            message = (await response.text()).strip()
    s = response.status
    if s in (429, 402): raise RateLimitError(f"{s}: {message}")
    if s == 401: raise MissingAuthError(f"{s}: {message}")
    if s == 403 and _is_cloudflare(str(message)): raise CloudflareError(f"{s}: Cloudflare")
    if s == 403 and "recaptcha" in str(message).lower(): raise MissingAuthError(f"{s}: Bot detected")
    raise ResponseStatusError(f"{s}: {message}")

if HAS_CURL:
    class StreamResponse:
        def __init__(self, inner):
            self.inner = inner
        async def text(self): return await self.inner.atext()
        async def json(self, **kw): return json.loads(await self.inner.acontent(), **kw)
        def iter_lines(self): return self.inner.aiter_lines()
        async def __aenter__(self):
            inner = await self.inner
            self.inner = inner
            self.status = inner.status_code
            self.reason = inner.reason
            self.ok = inner.ok
            self.headers = inner.headers
            self.cookies = inner.cookies
            return self
        async def __aexit__(self, *a): await self.inner.aclose()

    class StreamSession(AsyncSession):
        def __init__(self, impersonate=None, **kw):
            if impersonate == "chrome": impersonate = BrowserState.impersonate
            super().__init__(impersonate=impersonate, **kw)
        def request(self, method, url, ssl=None, **kw):
            if _HAS_CURL_MIME and kw.get("data") and isinstance(kw.get("data"), CurlMime):
                kw["multipart"] = kw.pop("data")
            return StreamResponse(super().request(method, url, stream=True, verify=ssl, **kw))
        post = partialmethod(request, "POST")
else:
    class StreamResponse:
        def __init__(self, *a, **k): raise ImportError("curl_cffi missing")
    class StreamSession:
        def __init__(self, *a, **k): raise ImportError("curl_cffi missing")

def _cookie_params(cookies: dict, url=None, domain=None):
    if not HAS_NODRIVER: return []
    return[CookieParam.from_json({"name": k, "value": v, "url": url, "domain": domain})
            for k, v in cookies.items()]

async def _get_or_create_browser(proxy=None):
    if not HAS_NODRIVER:
        raise MissingRequirementsError("zendriver not installed")
    async with BrowserState.get_lock():
        if BrowserState.instance is not None:
            try:
                _ = BrowserState.instance.connection
                return BrowserState.instance
            except Exception:
                BrowserState.instance = None

        ud = user_config_dir("overwrite-code-nodriver") if HAS_PLATFORMDIRS else None
        exe = None
        try:
            from zendriver.core.config import find_executable
            exe = find_executable()
        except Exception:
            pass

        bargs =["--no-sandbox"]
        if proxy: bargs.append(f"--proxy-server={proxy}")

        console.print("[dim]Launching persistent browser...[/dim]")
        browser = await nodriver.start(
            user_data_dir=ud,
            browser_args=bargs,
            browser_executable_path=exe,
        )
        BrowserState.instance = browser
        return browser

async def get_args_from_nodriver(url, proxy=None, timeout=120, callback=None,
                                   cookies=None, user_data_dir=None, browser_args=None):
    browser = await _get_or_create_browser(proxy=proxy)
    if cookies is None: cookies = {}
    domain = urlparse(url).netloc
    if cookies:
        await browser.cookies.set_all(_cookie_params(cookies, url=url, domain=domain))
    page = await browser.get(url)
    ua = await page.evaluate("window.navigator.userAgent", return_by_value=True)
    for _ in range(timeout):
        if await page.evaluate("!!document.querySelector('body:not(.no-js)')"): break
        await asyncio.sleep(1)
    if callback: await callback(page)
    for c in await page.send(nodriver.cdp.network.get_cookies([url])):
        cookies[c.name] = c.value
    BrowserState.page = page
    return {
        "impersonate": "chrome",
        "cookies": cookies,
        "headers": {**DEFAULT_HEADERS, "user-agent": ua, "referer": f"{url.rstrip('/')}/"},
        "proxy": proxy,
    }

LMARENA_URL = "https://arena.ai"
CREATE_EVAL  = "https://arena.ai/nextjs-api/stream/create-evaluation"

_lm_args: dict = {}
_lm_grecaptcha: str = ""

async def _click_turnstile(page, el='document.getElementById("cf-turnstile")'):
    for _ in range(3):
        for idx in range(15):
            size = await page.js_dumps(f'{el}?.getBoundingClientRect()||{{}}')
            if "x" not in size: break
            await page.flash_point(size.get("x") + idx*3, size.get("y") + idx*3)
            await page.mouse_click(size.get("x") + idx*3, size.get("y") + idx*3)
            await asyncio.sleep(2)
        if "x" not in await page.js_dumps(f'{el}?.getBoundingClientRect()||{{}}'): break

async def _lm_init_browser(proxy=None, force=True):
    global _lm_args, _lm_grecaptcha
    cache = _get_cache_file()
    results =[]

    async def clear_cookies(browser, url):
        host = urlparse(url).hostname
        for c in await browser.cookies.get_all():
            dom = (c.domain or "").lstrip(".")
            if dom and (host == dom or host.endswith("."+dom)):
                if c.name == "cf_clearance": continue
                await browser.main_tab.send(
                    cdp.network.delete_cookies(name=c.name, domain=dom, path=c.path))

    async def callback(page):
        if force:
            await clear_cookies(page.browser, LMARENA_URL)
            await page.reload()
            import random
            for _ in range(random.randint(3, 7)):
                try:
                    await page.evaluate(f"window.scrollBy({random.randint(-100, 100)}, {random.randint(-400, 400)});")
                    await page.mouse_click(random.randint(100, 800), random.randint(100, 800))
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                except:
                    pass
        btn = await page.find("Accept Cookies")
        if btn: await btn.click()
        await asyncio.sleep(1)
        ta = await page.select('textarea[name="message"]')
        if ta: await ta.send_keys("Hello")
        await asyncio.sleep(1)
        try:
            el = await page.select('[style="display: grid;"]')
        except Exception:
            el = None
        if el:
            await _click_turnstile(page, 'document.querySelector(\'[style="display: grid;"]\')') 
        if not await page.evaluate('document.cookie.indexOf("arena-auth-prod-v1") >= 0'):
            await page.select('#cf-turnstile', 300)
            await asyncio.sleep(3)
            await _click_turnstile(page)
        while not await page.evaluate('document.cookie.indexOf("arena-auth-prod-v1") >= 0'):
            await asyncio.sleep(1)
        while not await page.evaluate("!!document.querySelector('textarea')"):
            await asyncio.sleep(1)
        cap = await page.evaluate(
            "window.grecaptcha.enterprise.execute('6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I', {action:'chat_submit'});",
            await_promise=True)
        results.append(cap)

    _lm_args = await get_args_from_nodriver(LMARENA_URL, proxy=proxy, callback=callback)
    with cache.open("w") as f: json.dump(_lm_args, f)
    _lm_grecaptcha = next(iter(results), "")

async def _lm_refresh_captcha(proxy=None):
    global _lm_args, _lm_grecaptcha
    results =[]

    async def callback(page):
        for _ in range(60):
            if await page.evaluate("!!(window.grecaptcha && window.grecaptcha.enterprise)"): break
            await asyncio.sleep(1)
        cap = await page.evaluate(
            """new Promise((resolve) => {
                window.grecaptcha.enterprise.ready(async () => {
                    try {
                        const t = await window.grecaptcha.enterprise.execute(
                            '6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I', {action:'chat_submit'});
                        resolve(t);
                    } catch(e) { resolve(null); }
                });
            });""", await_promise=True)
        if isinstance(cap, str): results.append(cap)

    if BrowserState.page:
        try:
            await callback(BrowserState.page)
            _lm_grecaptcha = next(iter(results), "")
            return
        except Exception:
            pass
    _lm_args = await get_args_from_nodriver(
        LMARENA_URL, proxy=proxy, callback=callback, cookies=_lm_args.get("cookies", {}))
    _lm_grecaptcha = next(iter(results), "")
    cache = _get_cache_file()
    with cache.open("w") as f: json.dump(_lm_args, f)

async def lm_chat_stream(model_name: str, messages: List[Dict], proxy=None, timeout=0):
    global _lm_args, _lm_grecaptcha

    if not _lm_args:
        cache = _get_cache_file()
        if cache.exists():
            try:
                with cache.open() as f: _lm_args = json.load(f)
            except Exception:
                pass

    if not _lm_args:
        yield ("status", "Authenticating with browser...")
        await _lm_init_browser(proxy=proxy)

    if HAS_NODRIVER:
        yield ("status", "Fetching fresh reCAPTCHA token...")
        await _lm_refresh_captcha(proxy=proxy)

    model_id = AVAILABLE_MODELS.get(model_name, AVAILABLE_MODELS[DEFAULT_MODEL])
    prompt = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            prompt = c if isinstance(c, str) else " ".join(
                x.get("text","") for x in c if isinstance(x,dict) and x.get("type")=="text")
            break

    eval_id = str(uuid7())
    data = {
        "id": eval_id,
        "mode": "direct",
        "modelAId": model_id,
        "userMessageId": str(uuid7()),
        "modelAMessageId": str(uuid7()),
        "userMessage": {"content": prompt, "experimental_attachments":[], "metadata": {}},
        "modality": "chat",
        "recaptchaV3Token": _lm_grecaptcha,
    }

    while True:
        try:
            async with StreamSession(**_lm_args, timeout=timeout) as session:
                async with session.post(CREATE_EVAL, json=data, proxy=proxy, timeout=timeout) as resp:
                    await raise_for_status(resp)
                    _lm_args["cookies"] = merge_cookies(_lm_args["cookies"], resp)
                    async for raw in resp.iter_lines():
                        line = raw.decode()
                        if line.startswith("a0:"):
                            chunk = json.loads(line[3:])
                            if chunk == "hasArenaError":
                                yield ("error", "LMArena hasArenaError")
                                return
                            if isinstance(chunk, str):
                                yield ("text", chunk)
                        elif line.startswith("ag:"):
                            chunk = json.loads(line[3:])
                            t = ""
                            if isinstance(chunk, dict):
                                t = chunk.get("token") or chunk.get("is_thinking") or chunk.get("status","")
                            elif isinstance(chunk, str):
                                t = chunk
                            if t: yield ("thinking", t)
                        elif line.startswith("a2:") and '"heartbeat"' in line:
                            continue
                        elif line.startswith("a2:"):
                            chunk = json.loads(line[3:])
                            imgs =[i.get("image") for i in chunk if isinstance(i,dict) and i.get("image")]
                            for img in imgs: yield ("image", img)
                        elif line.startswith("ad:"):
                            yield ("done", None)
                            cache = _get_cache_file()
                            with cache.open("w") as f: json.dump(_lm_args, f)
                            return
                        elif line.startswith("a3:"):
                            yield ("error", json.loads(line[3:]))
                            return
            return
            
        except (CloudflareError, MissingAuthError) as auth_error:
            yield ("status", f"Auth lost ({auth_error}). Forcing re-authentication...")
            while True:
                try:
                    await _lm_init_browser(proxy=proxy, force=True)
                    data["recaptchaV3Token"] = _lm_grecaptcha
                    yield ("status", "Re-authentication successful. Retrying message...")
                    break 
                except Exception as inner_e:
                    yield ("status", f"Re-auth failed: {inner_e}. Retrying in 5s...")
                    await asyncio.sleep(5)
                    
        except RateLimitError:
            yield ("error", "Rate limited - wait a moment")
            return
        except Exception as e:
            yield ("error", str(e))
            return

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

def read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[Error reading file: {e}]"

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
    actions =[]
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
        
        # Safety catch so the AI doesn't delete the root workspace folder
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
"""
        messages_to_send =[{"role": "system", "content": system_prompt}] + list(conversation_messages)
        last_msg = messages_to_send[-1].copy()
        last_msg["content"] += "\n\n" + enforcement
        messages_to_send[-1] = last_msg

        console.print()
        console.print(f"[bold bright_magenta]AI[/bold bright_magenta][dim]({model})[/dim]")
        
        if any(x in model.lower() for x in ["thinking", "o3", "o4", "qwq"]):
            console.print("[dim italic]  * This model features a thinking process *[/dim italic]")
            
        console.print(Rule(style="dim magenta"))
        console.print("[dim italic]Press Ctrl+C to stop generation[/dim italic]")

        thinking_buffer =[]
        response_buffer =[]
        thinking_shown = False
        status_text = ""

        def clear_status():
            nonlocal status_text
            if status_text:
                sys.stdout.write("\r" + " " * 80 + "\r")
                sys.stdout.flush()
                status_text = ""

        async def flush_thinking():
            nonlocal thinking_shown
            if thinking_buffer:
                t = "".join(thinking_buffer)
                short = t[:400].replace("\n", " ")
                if len(t) > 400: short += "..."
                console.print(Panel(
                    f"[dim italic]{escape(short)}[/dim italic]",
                    title="[dim]Thinking...[/dim]",
                    border_style="dim",
                    padding=(0, 1),
                ))
                thinking_buffer.clear()
                thinking_shown = True

        try:
            async for kind, content in lm_chat_stream(model, messages_to_send, timeout=0):
                if kind == "status":
                    clear_status()
                    sys.stdout.write(f"\r  WAIT: {content}")
                    sys.stdout.flush()
                    status_text = content
                elif kind == "thinking":
                    clear_status()
                    thinking_buffer.append(content)
                elif kind == "text":
                    clear_status()
                    if thinking_buffer:
                        await flush_thinking()
                    response_buffer.append(content)
                    print(content, end="", flush=True)
                elif kind == "image":
                    clear_status()
                    console.print(f"\n[cyan][Image: {content}][/cyan]")
                    response_buffer.append(f"[Image: {content}]")
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

        if thinking_buffer:
            await flush_thinking()

        console.print(Rule(style="dim magenta"))

        full_response = "".join(response_buffer)

        # Auto-close interrupted XML tags so partial files are still saved
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

    if HAS_NODRIVER:
        console.print()
        with console.status("[bold green]Opening browser & authenticating...[/bold green]"):
            try:
                await _lm_init_browser()
                console.print("[green]Browser ready & authenticated[/green]")
            except Exception as e:
                console.print(f"[yellow]Warning Browser init issue: {e}[/yellow]")
                console.print("[yellow]  Will retry on first message.[/yellow]")
    else:
        console.print("[yellow]Warning zendriver not installed - browser features disabled[/yellow]")
        console.print("[yellow]  pip install zendriver platformdirs[/yellow]")

    console.print()
    await chat_loop(folder_path, model)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass