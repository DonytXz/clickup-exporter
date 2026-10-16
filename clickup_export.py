#!/usr/bin/env python3
"""
ClickUp Story & Subtasks Exporter
--------------------------------
Exports a ClickUp story, its subtasks, and its prerequisite tickets ("blocked by")
to a local folder with all content and embedded images.

Formats supported:
  - Markdown (.md) with a local 'images/' directory (default, recommended)
  - Apple RTFD / RTF (.rtfd / .rtf) using macOS built-in `textutil` CLI
  - Both (--format all / --both)

SDD (Spec-Driven Development) Mode:
  - Supports --sdd for structured specs workflow
  - Exports files into raw-export/ and generates TRANSFORM_TO_SDD.md for AI agents
  - Does NOT output requirements.md, design.md, or tasks.md directly, allowing the
    AI agent to transform the exported ClickUp content into formal SDD artifacts.

Usage:
  python3 clickup_export.py <TASK_URL_OR_ID> [options]

Examples:
  python3 clickup_export.py https://app.clickup.com/t/86a1b2c3d
  python3 clickup_export.py https://app.clickup.com/t/12345678/PROJ-101 --output ~/Downloads
  python3 clickup_export.py PROJ-101 --format both
  python3 clickup_export.py PROJ-101 --sdd
  python3 clickup_export.py PROJ-101 --sdd --no-tracking --workspace
"""

import os
import sys
import re
import json
import argparse
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import unicodedata
from pathlib import Path


DEFAULT_AGENTS_MD = Path(__file__).resolve().parent / "templates" / "AGENTS.md"

DEFAULT_CONFIG = {
    "company_name": "Generic",
    "default_output_dir": ".",
    "default_format": "md",
    "task_conventions": {
        "frontend_prefixes": ["FE", "FRONTEND", "UI"],
        "backend_prefixes": ["BE", "BACKEND", "DB", "EP", "API"]
    },
    "git_conventions": {
        "branch_prefix": "feature",
        "commit_type": "feat"
    },
    "agents_guide": {
        "include": True,
        "template_path": str(DEFAULT_AGENTS_MD)
    },
    "sdd": {
        "enabled": False,
        "tracking": True,
        "specs_dir": None,
        "generate_workspace": False
    }
}


def load_config(config_path: str = None) -> dict:
    """
    Loads configuration from a JSON file if present, merged with defaults.
    Checks:
      1. Explicit config_path (if supplied)
      2. config.json in current directory
      3. clickup_config.json in current directory
      4. config.json in script directory
    """
    import copy
    config = copy.deepcopy(DEFAULT_CONFIG)
    candidate_paths = []
    if config_path:
        candidate_paths.append(Path(config_path))
    else:
        candidate_paths.append(Path("config.json"))
        candidate_paths.append(Path("clickup_config.json"))
        candidate_paths.append(Path(__file__).resolve().parent / "config.json")

    for path in candidate_paths:
        if path.exists() and path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    for k, v in user_cfg.items():
                        if isinstance(v, dict) and isinstance(config.get(k), dict):
                            config[k].update(v)
                        else:
                            config[k] = v
                break
            except Exception as e:
                print(f"  [Warning] Could not parse config at {path}: {e}", file=sys.stderr)

    return config


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe filesystem folder/file names."""
    if not name:
        return "untitled"
    cleaned = re.sub(r'[/\\:*?"<>|]', '-', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('. ')
    return cleaned[:150] or "untitled"


def parse_clickup_input(url_or_id: str) -> tuple:
    """
    Extracts (task_id, team_id) from ClickUp URLs (2.0 and 3.0) or raw task strings.
    Supports standard IDs, custom IDs, query params (?pr=..., ?p=..., ?task=...), and list view URLs.
    """
    raw = url_or_id.strip().strip("'\"")
    team_id = None
    task_id = raw

    if "clickup.com" in raw:
        parsed = urllib.parse.urlparse(raw)
        
        # 1. Check query parameters first (?pr=..., ?p=..., ?task=..., ?t=...)
        qs = urllib.parse.parse_qs(parsed.query)
        for q_key in ["pr", "p", "task", "t"]:
            if q_key in qs and qs[q_key]:
                task_id = qs[q_key][0]
                break

        # 2. Check path segments
        parts = [p for p in parsed.path.split('/') if p]
        if "t" in parts:
            t_idx = parts.index("t")
            subparts = parts[t_idx + 1:]
            if len(subparts) == 1:
                if task_id == raw:
                    task_id = subparts[0]
            elif len(subparts) >= 2:
                team_id = subparts[0]
                if task_id == raw:
                    task_id = subparts[1]
        elif parts:
            # ClickUp 3.0 workspace prefix: /36623333/v/li/...
            if parts[0].isdigit():
                team_id = parts[0]
            if task_id == raw and len(parts) > 1:
                task_id = parts[-1]

    task_id = task_id.strip("#/ ")
    return task_id, team_id


class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self, token: str):
        cleaned_token = token.strip().strip("'\"")
        if cleaned_token.lower().startswith("bearer "):
            cleaned_token = cleaned_token[7:].strip()
        self.token = cleaned_token
        self.authorized_teams = []
        self.active_team_id = None

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json",
                "User-Agent": "ClickUpExporter/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("err") or err_json.get("error") or err_body
            except Exception:
                err_msg = err_body
            raise RuntimeError(f"HTTP {e.code} ({e.reason}): {err_msg}")
        except Exception as e:
            raise RuntimeError(f"Network error requesting '{url}': {e}")

    def load_authorized_teams(self) -> list:
        """Fetch all teams (workspaces) accessible by this personal token."""
        try:
            data = self._get("team")
            teams = data.get("teams", [])
            self.authorized_teams = teams
            return teams
        except Exception as e:
            print(f"  [Warning] Failed to fetch authorized teams: {e}", file=sys.stderr)
            return []

    def get_task(self, task_id: str, hint_team_id: str = None) -> dict:
        """
        Fetch task details with automatic resolution for standard IDs,
        Custom Task IDs (e.g. PROJ-101), and workspace authorization.
        """
        if not self.authorized_teams:
            self.load_authorized_teams()

        team_ids_to_try = []
        if hint_team_id:
            team_ids_to_try.append(str(hint_team_id))
        for t in self.authorized_teams:
            tid = str(t.get("id"))
            if tid not in team_ids_to_try:
                team_ids_to_try.append(tid)

        last_error = None
        is_custom_id_format = bool(re.search(r'^[A-Za-z0-9]+-[0-9]+$', task_id))

        # Strategy 1: Standard task ID lookup (if not explicitly custom-format)
        if not is_custom_id_format:
            try:
                data = self._get(
                    f"task/{task_id}",
                    {"include_subtasks": "true", "include_markdown_description": "true"}
                )
                if "team_id" in data:
                    self.active_team_id = str(data["team_id"])
                return data
            except RuntimeError as e:
                last_error = e

        # Strategy 2: Custom Task ID lookup across accessible teams
        for tid in team_ids_to_try:
            try:
                data = self._get(
                    f"task/{task_id}",
                    {
                        "custom_task_ids": "true",
                        "team_id": tid,
                        "include_subtasks": "true",
                        "include_markdown_description": "true"
                    }
                )
                self.active_team_id = tid
                return data
            except RuntimeError as e:
                last_error = e
                continue

        # Strategy 3: Fallback standard lookup even if it had hyphens
        if is_custom_id_format:
            try:
                data = self._get(
                    f"task/{task_id}",
                    {"include_subtasks": "true", "include_markdown_description": "true"}
                )
                if "team_id" in data:
                    self.active_team_id = str(data["team_id"])
                return data
            except RuntimeError as e:
                last_error = e

        # Diagnostics for OAUTH_027 error
        workspaces_list = "\n".join([f"  • {t.get('name', 'Workspace')} (Workspace ID: {t.get('id')})" for t in self.authorized_teams])
        error_explanation = (
            f"\n❌ ClickUp could not find or authorize task '{task_id}'.\n"
            f"API response: {last_error}\n\n"
            f"🔍 What caused this ('Team not authorized' / OAUTH_027):\n"
            f"1. Workspace Scope:\n"
            f"   Your API Token is currently authorized for:\n"
            f"{workspaces_list or '   (No workspaces found for this token)'}\n\n"
            f"2. How to fix:\n"
            f"   - If this task belongs to a DIFFERENT workspace, switch to that workspace in ClickUp\n"
            f"     and generate a Personal API Token from that workspace:\n"
            f"     Settings ➔ Apps ➔ ClickUp API ➔ Generate Personal API Token.\n"
            f"   - If you copied the link from a List/Table view URL, copy the direct task link instead:\n"
            f"     Open the task ➔ click 'Share' or '...' ➔ 'Copy link' (format: https://app.clickup.com/t/YOUR_TASK_ID)."
        )
        raise RuntimeError(error_explanation)

    def download_file(self, url: str, dest_path: Path):
        """Download remote asset/image to local path."""
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": self.token,
                "User-Agent": "ClickUpExporter/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(resp.read())
        except Exception:
            # Fallback without Authorization header for presigned S3 URLs
            with urllib.request.urlopen(url, timeout=30) as resp:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(resp.read())


def simple_md_to_html(md_text: str) -> str:
    """Lightweight Markdown-to-HTML converter for textutil conversion."""
    lines = md_text.split('\n')
    html_lines = []
    in_ul = False
    in_ol = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            html_lines.append("<br>")
            continue

        # Horizontal rule
        if line in ("---", "***", "___", "* * *"):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            html_lines.append("<hr style='border: none; border-top: 1px solid #cbd5e1; margin: 16px 0;'>")
            continue

        # Blockquote
        if line.startswith(">"):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            bq_content = line.lstrip("> ")
            bq_content = re.sub(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*', '', bq_content)
            bq_content = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', bq_content)
            bq_content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', bq_content)
            bq_content = re.sub(r'`(.*?)`', r'<code>\1</code>', bq_content)
            html_lines.append(f"<blockquote style='border-left: 4px solid #2563eb; padding: 6px 12px; color: #334155; margin: 8px 0; background: #f8fafc;'>{bq_content}</blockquote>")
            continue

        # Table rows
        if line.startswith("|") and line.endswith("|"):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if "---" in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            cells_html = []
            for c in cells:
                c = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', c)
                c = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', c)
                c = re.sub(r'`(.*?)`', r'<code>\1</code>', c)
                cells_html.append(f"<td style='border: 1px solid #cbd5e1; padding: 6px 10px;'>{c}</td>")
            html_lines.append(f"<table style='border-collapse: collapse; margin: 8px 0; width: 100%;'><tr>{''.join(cells_html)}</tr></table>")
            continue

        # Headers
        header_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if header_match:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            level = len(header_match.group(1))
            html_lines.append(f"<h{level}>{header_match.group(2)}</h{level}>")
            continue

        # Unordered list
        if line.startswith("- ") or line.startswith("* "):
            if not in_ul:
                if in_ol:
                    html_lines.append("</ol>")
                    in_ol = False
                html_lines.append("<ul>")
                in_ul = True
            content = line[2:]
            html_lines.append(f"<li>{content}</li>")
            continue

        # Ordered list
        ol_match = re.match(r'^\d+\.\s+(.*)', line)
        if ol_match:
            if not in_ol:
                if in_ul:
                    html_lines.append("</ul>")
                    in_ul = False
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{ol_match.group(1)}</li>")
            continue

        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

        # Images
        line = re.sub(r'!\[(.*?)\]\((.*?)\)', r'<p><img src="\2" alt="\1" style="max-width:100%;"></p>', line)
        # Links
        line = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', line)
        # Bold
        line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        # Italic
        line = re.sub(r'\*(.*?)\*', r'<i>\1</i>', line)
        # Code
        line = re.sub(r'`(.*?)`', r'<code>\1</code>', line)

        html_lines.append(f"<p>{line}</p>")

    if in_ul:
        html_lines.append("</ul>")
    if in_ol:
        html_lines.append("</ol>")

    body = "\n".join(html_lines)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #1e1e1e; }}
h1, h2, h3, h4 {{ color: #0f172a; margin-top: 1.2em; margin-bottom: 0.4em; }}
img {{ max-width: 100%; border-radius: 4px; margin: 10px 0; }}
code {{ background-color: #f1f5f9; padding: 2px 4px; border-radius: 4px; }}
blockquote {{ border-left: 4px solid #2563eb; padding: 6px 12px; color: #334155; margin: 8px 0; background: #f8fafc; }}
table {{ border-collapse: collapse; margin: 8px 0; width: 100%; }}
td, th {{ border: 1px solid #cbd5e1; padding: 6px 10px; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def to_kebab_case(text: str) -> str:
    """Convert human-readable title into a clean kebab-case string for git branches."""
    if not text:
        return "branch"
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", norm)
    words = [w.lower() for w in cleaned.split() if w]
    return "-".join(words[:8]) or "branch"


def generate_task_header(task: dict, role: str = "story", parent_task: dict = None, subtasks: list = None, config: dict = None) -> str:
    """
    Generates a structured metadata header for the ticket.
    role: 'story', 'subtask', or 'prerequisite'
    """
    cfg = config or DEFAULT_CONFIG
    git_cfg = cfg.get("git_conventions", {})
    task_cfg = cfg.get("task_conventions", {})

    branch_prefix = git_cfg.get("branch_prefix", "feature")
    commit_type = git_cfg.get("commit_type", "feat")
    fe_prefixes = [p.upper() for p in task_cfg.get("frontend_prefixes", ["FE", "FRONTEND", "UI"])]
    be_prefixes = [p.upper() for p in task_cfg.get("backend_prefixes", ["BE", "BACKEND", "DB", "EP", "API"])]

    custom_id = task.get("custom_id")
    internal_id = task.get("id", "")
    display_id = custom_id if custom_id else internal_id
    url = task.get("url", f"https://app.clickup.com/t/{internal_id}")
    name = task.get("name", f"Task-{internal_id}")
    status = task.get("status", {})
    status_str = status.get("status", "open") if isinstance(status, dict) else str(status)

    title_prefix = "PREVIUS TICKET NEEDED " if role == "prerequisite" else ""
    lines = []
    lines.append(f"# {title_prefix}{name}\n")
    lines.append("> [!NOTE]")
    lines.append(f"> **ClickUp Ticket:** [`{display_id}`]({url}) | **Estado:** `{status_str.upper()}`")

    if role == "story":
        slug = to_kebab_case(name)
        branch_name = f"{branch_prefix}/{display_id}-{slug}"
        lines.append(f"> **Rol:** 🌟 **Historia / Ticket Principal**")
        lines.append(f"> 📌 **Regla Git por defecto:** Es en este ticket donde se debe crear la **Rama** y el **Pull Request**.")
        lines.append(f"> - **Rama recomendada:** `{branch_name}`")
        lines.append(f"> - **Commit sugerido:** `{commit_type} : {display_id} - {name}`")
        if subtasks:
            lines.append(f">\n> **Subtareas vinculadas ({len(subtasks)}):**")
            for sub in subtasks:
                sub_cid = sub.get("custom_id") or sub.get("id")
                sub_url = sub.get("url", f"https://app.clickup.com/t/{sub.get('id')}")
                sub_name = sub.get("name", "Subtask")
                lines.append(f"> - [`{sub_cid}`]({sub_url}) - {sub_name}")

    elif role == "subtask":
        upper_name = name.upper()
        is_fe = any(upper_name.startswith(p) or f"[{p}]" in upper_name or f"({p})" in upper_name for p in fe_prefixes)
        is_be = any(upper_name.startswith(p) or f"[{p}]" in upper_name or f"({p})" in upper_name for p in be_prefixes)

        parent_cid = parent_task.get("custom_id") or parent_task.get("id", "PARENT") if parent_task else "PARENT"
        parent_url = parent_task.get("url", "#") if parent_task else "#"
        parent_name = parent_task.get("name", "Historia Principal") if parent_task else "Historia Principal"

        lines.append(f"> **Pertenece a la Historia Principal:** [`{parent_cid}`]({parent_url}) - {parent_name}")

        if is_fe:
            short_sub_id = re.sub(r'^[A-Za-z0-9]+-', '', display_id)
            lines.append(f"> **Ámbito:** 🎨 **Frontend (Alcance directo de implementación)**")
            lines.append(f"> 📌 **Recomendación por defecto (Ramas y PR):**")
            lines.append(f"> Por defecto, **NO crear una rama ni PR individual para esta subtarea**. Trabajar e integrar los cambios en la rama de la **Historia Principal** (`{branch_prefix}/{parent_cid}-...`).")
            lines.append(f"> - **Commit sugerido:** `{commit_type} : {parent_cid}_({short_sub_id}) - {name}` o `{commit_type} : {parent_cid} - {name}`")
            lines.append(f"> - **Vincular en PR:** En el PR de la Historia Principal, agregar este ticket (`{display_id}`) bajo `## Tickets relacionados`.")
        elif is_be:
            lines.append(f"> **Ámbito:** ℹ️ **Backend (Solo Contexto y Especificación Técnica)**")
            lines.append(f"> Utilizar este documento para consultar DTOs, endpoints, parámetros y queries de base de datos.")
            lines.append(f"> **NO modificar código de backend** a menos que se indique explícitamente.")
        else:
            lines.append(f"> **Ámbito:** 📋 Subtarea técnica general")

    elif role == "prerequisite":
        parent_cid = parent_task.get("custom_id") or parent_task.get("id", "PARENT") if parent_task else "PARENT"
        lines.append(f"> **Tipo:** ⚠️ **Ticket Bloqueante / Prerrequisito** para [`{parent_cid}`]")
        lines.append(f"> Debe ser considerado como contexto previo necesario antes de iniciar la historia.")

    lines.append("\n---\n")
    return "\n".join(lines)


def process_task_content(client: ClickUpClient, task: dict, images_dir: Path, image_counter: list,
                         role: str = "story", parent_task: dict = None, subtasks: list = None,
                         config: dict = None) -> tuple:
    raw_md = task.get("markdown_description") or task.get("description") or task.get("text_content") or ""
    downloaded_images = []

    # Handle ClickUp attachments and replace remote URLs with local image references
    attachments = task.get("attachments", [])
    attachments_by_url = {}
    for att in attachments:
        url = att.get("url")
        if url:
            attachments_by_url[url] = att

    def image_sub(match):
        alt = match.group(1) or "image"
        img_url = match.group(2)
        
        # Determine extension
        parsed = urllib.parse.urlparse(img_url)
        ext = os.path.splitext(parsed.path)[1].lower()
        if not ext or len(ext) > 5:
            ext = ".png"

        image_counter[0] += 1
        img_filename = f"image_{image_counter[0]}{ext}"
        local_img_path = images_dir / img_filename
        rel_img_path = f"images/{img_filename}"

        try:
            client.download_file(img_url, local_img_path)
            downloaded_images.append((local_img_path, img_url))
            return f"![{alt}]({rel_img_path})"
        except Exception as e:
            print(f"      [Warning] Failed to download image {img_url}: {e}", file=sys.stderr)
            return match.group(0)

    # Markdown images: ![alt](url)
    processed_md = re.sub(r'!\[(.*?)\]\((https?://[^\s\)]+)\)', image_sub, raw_md)

    # HTML img tags: <img src="url" ...>
    def html_img_sub(match):
        img_url = match.group(1)
        image_counter[0] += 1
        img_filename = f"image_{image_counter[0]}.png"
        local_img_path = images_dir / img_filename
        rel_img_path = f"images/{img_filename}"
        try:
            client.download_file(img_url, local_img_path)
            downloaded_images.append((local_img_path, img_url))
            return f"![image]({rel_img_path})"
        except Exception:
            return match.group(0)

    processed_md = re.sub(r'<img[^>]+src=["\'](https?://[^"\']+)["\'][^>]*>', html_img_sub, processed_md)

    # Unreferenced attachments (e.g. uploaded files not inline)
    unreferenced = []
    for att in attachments:
        att_url = att.get("url")
        att_title = att.get("title", "Attachment")
        if att_url and not any(att_url in dl[1] for dl in downloaded_images):
            unreferenced.append(f"- [{att_title}]({att_url})")
    
    if unreferenced:
        processed_md += "\n\n---\n\n## 📎 Adjuntos adicionales (Task Attachments)\n\n" + "\n\n".join(unreferenced) + "\n"

    header = generate_task_header(task, role=role, parent_task=parent_task, subtasks=subtasks, config=config)
    full_md = header + processed_md

    return full_md, downloaded_images


def convert_to_rtfd_if_possible(md_content: str, rtf_base_path: Path, temp_dir: Path, has_images: bool, display_prefix: str = ""):
    """Converts markdown content to .rtfd (if images) or .rtf using macOS textutil."""
    html_content = simple_md_to_html(md_content)
    temp_html = temp_dir / f"_temp_{rtf_base_path.stem}.html"
    temp_html.write_text(html_content, encoding="utf-8")

    out_format = "rtfd" if has_images else "rtf"
    target_output = rtf_base_path.with_suffix(f".{out_format}")

    cmd = [
        "textutil",
        "-convert", out_format,
        str(temp_html),
        "-output", str(target_output)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"        -> Saved Rich Text: {display_prefix}{target_output.name}")
    except Exception as e:
        print(f"        [Warning] textutil conversion failed for {rtf_base_path.stem}: {e}", file=sys.stderr)
    finally:
        if temp_html.exists():
            temp_html.unlink()


def generate_transform_to_sdd_directive(
    story_filename: str,
    fe_files: list,
    be_files: list,
    prereq_files: list,
    has_agents: bool,
    specs_folder: Path
) -> str:
    """
    Generates the TRANSFORM_TO_SDD.md prompt for AI coding assistants.
    The directive guides the agent to read raw-export/ and generate:
    - requirements.md (EARS syntax)
    - design.md (DDD Hexagonal architecture + backend contracts)
    - tasks.md (Atomic execution checklist)
    """
    fe_items = "\n".join(f"- `raw-export/{f}`" for f in fe_files) if fe_files else "- *(No Frontend subtasks detected)*"
    be_items = "\n".join(f"- `raw-export/{f}`" for f in be_files) if be_files else "- *(No Backend subtasks detected)*"

    prereq_section = ""
    if prereq_files:
        prereq_items = "\n".join(f"- `raw-export/{f}`" for f in prereq_files)
        prereq_section = f"\n### Prerrequisitos y Dependencias Bloqueantes:\n{prereq_items}\n"

    agents_line = "- **Reglas de Arquitectura y Gobernanza:** `raw-export/AGENTS.md`\n" if has_agents else ""

    return f"""# Directiva de Transformación a Spec-Driven Development (SDD)

Actúa como un Arquitecto de Software y Tech Lead experto en Domain-Driven Design (DDD) y Frontend (Angular).
Tu objetivo es analizar los archivos exportados de ClickUp ubicados en `raw-export/` y transformarlos en los 3 artefactos formales de SDD:

## Archivos de Entrada Disponibles:
- **Historia Principal:** `raw-export/{story_filename}`

### Subtareas Frontend (Alcance de Implementación UI):
{fe_items}

### Subtareas Backend (Referencia de Contratos API, DTOs y Endpoints):
{be_items}
{prereq_section}
{agents_line}
---

## Artefactos a Generar en la Raíz de las Especificaciones:

### 1. `requirements.md`
- Sintetiza la User Story (Rol, Necesidad, Beneficio).
- Define los límites del Alcance ("Incluye" y "No incluye").
- Formula cada requerimiento y regla de validación en sintaxis EARS:
  - *WHEN <condición/evento> THE SYSTEM SHALL <respuesta del sistema>*.
- Identifica casos borde, validaciones de unicidad y flujos alternativos.

### 2. `design.md`
- Diseña la solución Frontend siguiendo estrictamente la Arquitectura Hexagonal y DDD de `AGENTS.md`:
  - **Dominio:** Entidades y Puertos (interfaces de repositorios).
  - **Infraestructura:** Adaptador HTTP consumiendo los endpoints documentados en los archivos `BE - ...` (incluyendo DTOs y manejo de errores HTTP 400 y 409).
  - **Aplicación:** Casos de uso (`Get...UseCase`, `Create...UseCase`, etc.).
  - **Presentación:** Componentes Container/Presentational con Signals de Angular y Reactive Forms.
- **Regla Estricta:** NO diseñar pruebas unitarias dentro de `/core`.

### 3. `tasks.md`
- Desglosa la implementación en una lista de tareas atómicas y secuenciales con checkboxes `[ ]`:
  - Fase 1: Modelos de Dominio y Puertos.
  - Fase 2: Adaptadores de Infraestructura y pruebas unitarias (`*.spec.ts`).
  - Fase 3: Casos de Uso y pruebas unitarias.
  - Fase 4: Componentes de UI (Formulario, Tabla y Pestaña principal).
  - Fase 5: Suite de pruebas unitarias y prueba E2E simplificada.

---

> [!IMPORTANT]
> Procede a generar `requirements.md`, `design.md` y `tasks.md` directamente en la raíz de esta carpeta de especificaciones (`{specs_folder.resolve()}`), dejando `raw-export/` intacto como fuente de verdad.
"""


def generate_code_workspace_file(project_dir: Path, specs_dir: Path, workspace_file_path: Path):
    """Generates a Multi-Root .code-workspace file linking code repository and specs."""
    workspace_data = {
        "folders": [
            {
                "name": f"💻 Código Fuente ({project_dir.name})",
                "path": str(project_dir.resolve())
            },
            {
                "name": "📋 Especificaciones SDD",
                "path": str(specs_dir.resolve())
            }
        ],
        "settings": {
            "git.autorefresh": True
        }
    }
    with open(workspace_file_path, "w", encoding="utf-8") as f:
        json.dump(workspace_data, f, indent=2, ensure_ascii=False)


def export_clickup_story(
    task_id_or_url: str,
    output_parent: Path,
    token: str,
    export_format: str = "md",
    agents_file: str = None,
    no_agents: bool = False,
    sdd_mode: bool = False,
    tracking: bool = True,
    specs_dir: str = None,
    workspace: bool = False,
    config: dict = None
):
    cfg = config or DEFAULT_CONFIG
    client = ClickUpClient(token)
    
    # Normalize format
    if export_format in ("md", "markdown"):
        mode = "md"
    elif export_format in ("rtf", "rtfd"):
        mode = "rtf"
    elif export_format in ("both", "all"):
        mode = "both"
    else:
        mode = "md"

    # [1/5] Resolving task ID
    print("\n" + "=" * 60)
    print("🚀 ClickUp Story & Subtasks Exporter")
    if sdd_mode:
        print("📐 Mode: Spec-Driven Development (SDD)")
        print(f"   Tracking: {'Enabled (Project specs/)' if tracking else 'Disabled (Isolated directory)'}")
    print("=" * 60)
    task_id, hint_team = parse_clickup_input(task_id_or_url)
    print(f"\n[1/5] Resolving task: '{task_id}' (Workspace hint: {hint_team or 'None'})...")

    # Fetch main task
    main_task = client.get_task(task_id, hint_team_id=hint_team)
    task_id = main_task.get("id", task_id)
    story_title = main_task.get("name", f"Task-{task_id}")

    # [2/5] Creating export directory
    print(f"\n[2/5] Preparing destination folder for '{story_title}'...")
    folder_name = sanitize_filename(story_title)

    workspace_file_path = None
    if sdd_mode:
        if tracking:
            # Mode 1: Tracking inside project specs/
            specs_parent = output_parent if output_parent.name == "specs" else output_parent / "specs"
        else:
            # Mode 2: Isolated specs
            if specs_dir:
                sd = Path(os.path.expanduser(specs_dir))
                specs_parent = sd if sd.name == "specs" else sd / "specs"
            else:
                proj_name = Path.cwd().name
                specs_parent = Path.cwd().parent / f"{proj_name}-specs" / "specs"

        export_folder = specs_parent / folder_name
        export_folder.mkdir(parents=True, exist_ok=True)
        raw_export_dir = export_folder / "raw-export"
        raw_export_dir.mkdir(parents=True, exist_ok=True)
        target_content_dir = raw_export_dir
    else:
        export_folder = output_parent / folder_name
        export_folder.mkdir(parents=True, exist_ok=True)
        raw_export_dir = None
        target_content_dir = export_folder

    # Configure directory structure based on mode:
    # 1. mode == 'md' (default): Markdown files & images/ placed directly on root of target_content_dir
    # 2. mode == 'rtf': RTF files placed directly on root of target_content_dir, temp md cleaned up
    # 3. mode == 'both': Both md/ and rtf/ subdirectories created
    if mode == "both":
        md_dir = target_content_dir / "md"
        rtf_dir = target_content_dir / "rtf"
        images_dir = md_dir / "images"
        md_dir.mkdir(parents=True, exist_ok=True)
        rtf_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
    elif mode == "rtf":
        md_dir = target_content_dir / "_temp_work"
        rtf_dir = target_content_dir  # Directly on root of target_content_dir
        images_dir = md_dir / "images"
        md_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
    else:  # mode == 'md' (default)
        md_dir = target_content_dir
        rtf_dir = None
        images_dir = target_content_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

    print(f"      Target folder: {export_folder}")
    if sdd_mode:
        print(f"      - SDD Mode Active: Raw export files placed in {raw_export_dir.name}/")
    if mode == "md":
        print(f"      - Mode: Markdown default (files placed directly at content root)")
    elif mode == "rtf":
        print(f"      - Mode: RTF only (files placed directly at content root)")
    elif mode == "both":
        print(f"      - Mode: Both (Markdown in md/, Rich Text in rtf/)")

    image_counter = [0]
    subtasks = main_task.get("subtasks", [])

    rtf_prefix = "rtf/" if mode == "both" else ""
    sdd_prefix = "raw-export/" if sdd_mode else ""

    main_story_file_name = None
    fe_files = []
    be_files = []
    prereq_files = []

    # --- 1. Process Main Story ---
    print(f"\n[3/5] Processing Main Story: '{story_title}'...")
    main_md, main_imgs = process_task_content(
        client, main_task, images_dir, image_counter,
        role="story", subtasks=subtasks, config=cfg
    )

    if mode in ("md", "both"):
        main_md_file = md_dir / f"{sanitize_filename(story_title)}.md"
        with open(main_md_file, "w", encoding="utf-8") as f:
            f.write(main_md)
        main_story_file_name = main_md_file.name
        prefix = f"{sdd_prefix}md/" if mode == "both" else sdd_prefix
        print(f"  -> Saved Markdown: {prefix}{main_md_file.name}")

    if mode in ("rtf", "both") and rtf_dir:
        rtf_base = rtf_dir / sanitize_filename(story_title)
        convert_to_rtfd_if_possible(main_md, rtf_base, md_dir, bool(main_imgs), display_prefix=f"{sdd_prefix}{rtf_prefix}")

    # --- 2. Process Prerequisites ("Blocked By" / depends_on) ---
    print("\n[4/5] Inspecting Dependencies ('Blocked By' / Prerequisites)...")
    dependencies = main_task.get("dependencies", [])
    prereq_ids = []

    for dep in dependencies:
        dep_task_id = dep.get("task_id")
        depends_on = dep.get("depends_on")
        if depends_on and (dep_task_id == main_task.get("id") or dep_task_id == task_id):
            prereq_ids.append(depends_on)
        elif depends_on and depends_on != main_task.get("id"):
            prereq_ids.append(depends_on)

    prereq_ids = list(dict.fromkeys(prereq_ids))

    if prereq_ids:
        print(f"      Found {len(prereq_ids)} prerequisite ticket(s). Fetching details...")
        for p_id in prereq_ids:
            try:
                p_task = client.get_task(p_id, hint_team_id=client.active_team_id)
                p_title = p_task.get("name", f"Prereq-{p_id}")
                filename_base = f"PREVIUS TICKET NEEDED {sanitize_filename(p_title)}"
                print(f"      - Prerequisite: '{p_title}'")

                p_md, p_imgs = process_task_content(
                    client, p_task, images_dir, image_counter,
                    role="prerequisite", parent_task=main_task, config=cfg
                )

                if mode in ("md", "both"):
                    p_md_file = md_dir / f"{filename_base}.md"
                    with open(p_md_file, "w", encoding="utf-8") as f:
                        f.write(p_md)
                    prereq_files.append(p_md_file.name)
                    prefix = f"{sdd_prefix}md/" if mode == "both" else sdd_prefix
                    print(f"        -> Saved Markdown: {prefix}{p_md_file.name}")

                if mode in ("rtf", "both") and rtf_dir:
                    p_rtf_base = rtf_dir / filename_base
                    convert_to_rtfd_if_possible(p_md, p_rtf_base, md_dir, bool(p_imgs), display_prefix=f"{sdd_prefix}{rtf_prefix}")

            except Exception as e:
                print(f"      [Warning] Failed to fetch prerequisite {p_id}: {e}", file=sys.stderr)
    else:
        print("      No 'Blocked By' prerequisite tickets detected.")

    # --- 3. Process Subtasks ---
    print(f"\n[5/5] Processing {len(subtasks)} Subtask(s)...")

    task_cfg = cfg.get("task_conventions", {})
    fe_prefixes = [p.upper() for p in task_cfg.get("frontend_prefixes", ["FE", "FRONTEND", "UI"])]
    be_prefixes = [p.upper() for p in task_cfg.get("backend_prefixes", ["BE", "BACKEND", "DB", "EP", "API"])]

    for idx, sub in enumerate(subtasks, 1):
        sub_id = sub.get("id")
        sub_name = sub.get("name", f"Subtask-{sub_id}")
        print(f"      [{idx}/{len(subtasks)}] Subtask: '{sub_name}'")

        try:
            sub_full = client.get_task(sub_id, hint_team_id=client.active_team_id)
            sub_md, sub_imgs = process_task_content(
                client, sub_full, images_dir, image_counter,
                role="subtask", parent_task=main_task, config=cfg
            )

            upper_name = sub_name.upper()
            is_fe = any(upper_name.startswith(p) or f"[{p}]" in upper_name or f"({p})" in upper_name for p in fe_prefixes)
            is_be = any(upper_name.startswith(p) or f"[{p}]" in upper_name or f"({p})" in upper_name for p in be_prefixes)

            if mode in ("md", "both"):
                sub_md_file = md_dir / f"{sanitize_filename(sub_name)}.md"
                with open(sub_md_file, "w", encoding="utf-8") as f:
                    f.write(sub_md)

                if is_be:
                    be_files.append(sub_md_file.name)
                elif is_fe:
                    fe_files.append(sub_md_file.name)
                else:
                    fe_files.append(sub_md_file.name)

                prefix = f"{sdd_prefix}md/" if mode == "both" else sdd_prefix
                print(f"        -> Saved Markdown: {prefix}{sub_md_file.name}")

            if mode in ("rtf", "both") and rtf_dir:
                sub_rtf_base = rtf_dir / sanitize_filename(sub_name)
                convert_to_rtfd_if_possible(sub_md, sub_rtf_base, md_dir, bool(sub_imgs), display_prefix=f"{sdd_prefix}{rtf_prefix}")

        except Exception as e:
            print(f"      [Warning] Failed to fetch subtask {sub_id}: {e}", file=sys.stderr)

    # Clean up empty images folder if no images were found
    if images_dir.exists() and not any(images_dir.iterdir()):
        try:
            images_dir.rmdir()
        except Exception:
            pass

    # If only RTF was requested, remove the temporary working directory
    if mode == "rtf" and md_dir.exists():
        import shutil
        shutil.rmtree(md_dir, ignore_errors=True)

    # In 'both' mode, create convenience symlink at root of content folder for images
    if mode == "both" and images_dir.exists() and any(images_dir.iterdir()):
        top_images = target_content_dir / "images"
        if not top_images.exists():
            try:
                top_images.symlink_to(Path("md") / "images")
            except Exception:
                pass

    # Include AGENTS.md guide if enabled
    agents_guide_cfg = cfg.get("agents_guide", {})
    should_include_agents = not no_agents and agents_guide_cfg.get("include", True)

    has_agents_copied = False
    if should_include_agents:
        template_target = agents_file or agents_guide_cfg.get("template_path") or str(DEFAULT_AGENTS_MD)
        candidate_agents = Path(template_target)
        if candidate_agents.exists():
            import shutil
            dest_agents = target_content_dir / "AGENTS.md"
            shutil.copy2(candidate_agents, dest_agents)
            has_agents_copied = True
            loc_label = f"{sdd_prefix}AGENTS.md"
            print(f"  -> Included AGENTS.md at {loc_label}")

    # SDD Post-processing: Generate TRANSFORM_TO_SDD.md & Optional Workspace
    if sdd_mode:
        transform_prompt = generate_transform_to_sdd_directive(
            story_filename=main_story_file_name or f"{sanitize_filename(story_title)}.md",
            fe_files=fe_files,
            be_files=be_files,
            prereq_files=prereq_files,
            has_agents=has_agents_copied,
            specs_folder=export_folder
        )
        directive_file = export_folder / "TRANSFORM_TO_SDD.md"
        with open(directive_file, "w", encoding="utf-8") as f:
            f.write(transform_prompt)
        print(f"  -> Generated SDD AI Directive: {directive_file.name}")

        if workspace:
            proj_root = Path.cwd()
            ws_path = proj_root / f"{proj_root.name}.code-workspace"
            generate_code_workspace_file(proj_root, export_folder, ws_path)
            workspace_file_path = ws_path
            print(f"  -> Generated Multi-Root Workspace: {ws_path.name}")

    print("\n" + "=" * 60)
    print("✅ Export completed successfully!")
    if sdd_mode:
        print(f"📁 SDD Specs Folder:    {export_folder.resolve()}")
        print(f"   📦 Raw Export:        {raw_export_dir.resolve()}")
        print(f"   📋 SDD AI Directive:  {export_folder / 'TRANSFORM_TO_SDD.md'}")
        if (target_content_dir / "AGENTS.md").exists():
            print(f"   🤖 Architecture Guide: {target_content_dir / 'AGENTS.md'}")
        if workspace_file_path:
            print(f"   💻 IDE Workspace:     {workspace_file_path.resolve()}")
        print("\n💡 SDD Workflow Note:")
        print("   The raw ClickUp content has been exported to 'raw-export/'.")
        print("   SDD markdown files (requirements.md, design.md, tasks.md) are not included")
        print("   allowing your AI agent to transform the exported files into formal SDD.")
        print("   👉 Provide TRANSFORM_TO_SDD.md to your AI agent (Cursor / Antigravity / Claude Code) to begin.")
    else:
        print(f"📁 Destination Folder: {export_folder.resolve()}")
        if (export_folder / "AGENTS.md").exists():
            print(f"   🤖 Workspace Guide:   {export_folder / 'AGENTS.md'}")
        if mode == "md":
            print(f"   📄 Markdown files:    Placed directly at root ({export_folder})")
            if (export_folder / "images").exists():
                print(f"   🖼️  Images directory:   {export_folder / 'images'}")
        elif mode == "rtf":
            print(f"   📝 Rich Text files:   Placed directly at root ({export_folder})")
        elif mode == "both":
            print(f"   📄 Markdown files:    {export_folder / 'md'}")
            print(f"   📝 Rich Text files:   {export_folder / 'rtf'}")
    print("=" * 60)


def resolve_token(cli_token: str) -> str:
    """
    Resolves the ClickUp API token in order of priority:
      1. --token CLI argument
      2. CLICKUP_API_TOKEN environment variable
      3. ~/.clickup_token configuration file
      4. .env file in the current working directory
      5. Interactive user prompt (with option to persist to ~/.clickup_token)
    """
    if cli_token and cli_token.strip():
        return cli_token.strip()

    env_token = os.environ.get("CLICKUP_API_TOKEN", "").strip()
    if env_token:
        return env_token

    token_file = Path.home() / ".clickup_token"
    if token_file.exists():
        try:
            saved_tok = token_file.read_text(encoding="utf-8").strip()
            if saved_tok:
                return saved_tok
        except Exception:
            pass

    dot_env = Path(".env")
    if dot_env.exists():
        try:
            for line in dot_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("CLICKUP_API_TOKEN="):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        return val
        except Exception:
            pass

    print("\nClickUp Personal API Token is required.")
    token = input("Enter your ClickUp API Token (pk_...): ").strip()
    if not token:
        print("Error: No API token provided. Exiting.", file=sys.stderr)
        sys.exit(1)

    try:
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)
        print(f"  [Saved token to {token_file} for future runs]")
    except Exception:
        pass

    return token


def stage_from_export(
    export_source: Path,
    output_parent: Path,
    sdd_mode: bool = True,
    tracking: bool = True,
    specs_dir: str = None,
    workspace: bool = False,
    config: dict = None
) -> Path:
    """
    Stages an existing exported folder into an SDD-ready folder with raw-export/
    and TRANSFORM_TO_SDD.md without making any ClickUp API calls.
    """
    cfg = config or DEFAULT_CONFIG
    export_source = Path(export_source).resolve()
    if not export_source.exists() or not export_source.is_dir():
        raise FileNotFoundError(f"Export source directory not found: {export_source}")

    md_files = list(export_source.glob("*.md"))
    if not md_files:
        raise ValueError(f"No markdown (.md) files found in {export_source}")

    task_cfg = cfg.get("task_conventions", {})
    fe_prefixes = [p.upper() for p in task_cfg.get("frontend_prefixes", ["FE", "FRONTEND", "UI"])]
    be_prefixes = [p.upper() for p in task_cfg.get("backend_prefixes", ["BE", "BACKEND", "DB", "EP", "API"])]

    main_candidates = []
    fe_files = []
    be_files = []
    prereq_files = []

    for f in md_files:
        fname = f.name
        upper = fname.upper()
        if fname in ("AGENTS.md", "README.md", "TRANSFORM_TO_SDD.md"):
            continue
        if upper.startswith("PREVIUS TICKET NEEDED") or upper.startswith("PREVIOUS TICKET NEEDED"):
            prereq_files.append(fname)
        elif any(upper.startswith(p) or f"[{p}]" in upper or f"({p})" in upper for p in fe_prefixes):
            fe_files.append(fname)
        elif any(upper.startswith(p) or f"[{p}]" in upper or f"({p})" in upper for p in be_prefixes):
            be_files.append(fname)
        else:
            main_candidates.append(f)

    main_file = main_candidates[0] if main_candidates else md_files[0]
    story_title = main_file.stem
    folder_name = sanitize_filename(story_title)

    if sdd_mode:
        if tracking:
            specs_parent = output_parent if output_parent.name == "specs" else output_parent / "specs"
        else:
            if specs_dir:
                sd = Path(os.path.expanduser(specs_dir))
                specs_parent = sd if sd.name == "specs" else sd / "specs"
            else:
                proj_name = Path.cwd().name
                specs_parent = Path.cwd().parent / f"{proj_name}-specs" / "specs"

        export_folder = specs_parent / folder_name
        export_folder.mkdir(parents=True, exist_ok=True)
        raw_export_dir = export_folder / "raw-export"
        raw_export_dir.mkdir(parents=True, exist_ok=True)
    else:
        export_folder = output_parent / folder_name
        export_folder.mkdir(parents=True, exist_ok=True)
        raw_export_dir = export_folder

    import shutil
    print(f"\n[1/3] Staging raw export files from '{export_source.name}' into '{raw_export_dir.name}'...")
    for f in md_files:
        shutil.copy2(f, raw_export_dir / f.name)
        print(f"      - Staged {f.name}")

    src_images = export_source / "images"
    if src_images.exists() and src_images.is_dir():
        dest_images = raw_export_dir / "images"
        if dest_images.exists():
            shutil.rmtree(dest_images)
        shutil.copytree(src_images, dest_images)
        print(f"      - Staged images/ ({len(list(dest_images.glob('*')))} files)")

    has_agents_copied = False
    agents_src = export_source / "AGENTS.md"
    if not agents_src.exists():
        agents_src = DEFAULT_AGENTS_MD
    if agents_src.exists():
        shutil.copy2(agents_src, raw_export_dir / "AGENTS.md")
        if sdd_mode:
            shutil.copy2(agents_src, export_folder / "AGENTS.md")
        has_agents_copied = True

    workspace_file_path = None
    if sdd_mode:
        print(f"\n[2/3] Generating SDD AI Directive (TRANSFORM_TO_SDD.md)...")
        transform_prompt = generate_transform_to_sdd_directive(
            story_filename=main_file.name,
            fe_files=fe_files,
            be_files=be_files,
            prereq_files=prereq_files,
            has_agents=has_agents_copied,
            specs_folder=export_folder
        )
        directive_file = export_folder / "TRANSFORM_TO_SDD.md"
        with open(directive_file, "w", encoding="utf-8") as f:
            f.write(transform_prompt)
        print(f"  -> Generated SDD AI Directive: {directive_file.name}")

        if workspace:
            proj_root = Path.cwd()
            ws_path = proj_root / f"{proj_root.name}.code-workspace"
            generate_code_workspace_file(proj_root, export_folder, ws_path)
            workspace_file_path = ws_path
            print(f"  -> Generated Multi-Root Workspace: {ws_path.name}")

    print("\n[3/3] Verification and Staging Complete!")
    print("\n" + "=" * 60)
    print("✅ Staging completed successfully!")
    if sdd_mode:
        print(f"📁 SDD Specs Folder:    {export_folder.resolve()}")
        print(f"   📦 Raw Export:        {raw_export_dir.resolve()}")
        print(f"   📋 SDD AI Directive:  {export_folder / 'TRANSFORM_TO_SDD.md'}")
        if (export_folder / "AGENTS.md").exists():
            print(f"   🤖 Architecture Guide: {export_folder / 'AGENTS.md'}")
        if workspace_file_path:
            print(f"   💻 IDE Workspace:     {workspace_file_path.resolve()}")
        print("\n💡 SDD Workflow Note:")
        print("   The raw ClickUp content has been staged into 'raw-export/'.")
        print("   SDD markdown files (requirements.md, design.md, tasks.md) are not included")
        print("   allowing your AI agent to transform the exported files into formal SDD.")
        print("   👉 Provide TRANSFORM_TO_SDD.md to your AI agent (Cursor / Antigravity / Claude Code) to begin.")
    else:
        print(f"📁 Destination Folder: {export_folder.resolve()}")
    print("=" * 60)

    return export_folder


def main():
    parser = argparse.ArgumentParser(
        description="Export ClickUp stories, subtasks, prerequisites ('blocked by'), and images into a local folder, with optional Spec-Driven Development (SDD) staging."
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="ClickUp Task URL (e.g. https://app.clickup.com/t/86a1b2c3d or https://app.clickup.com/t/12345678/PROJ-101) or Task ID"
    )
    parser.add_argument(
        "--from-export",
        default=None,
        help="Path to an existing exported folder to convert/stage into SDD mode without ClickUp API calls"
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output parent directory (default: current directory or configured default_output_dir)"
    )
    parser.add_argument(
        "-t", "--token",
        default="",
        help="ClickUp Personal API Token (or set CLICKUP_API_TOKEN env var / ~/.clickup_token)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["md", "markdown", "rtf", "rtfd", "both", "all"],
        default=None,
        help="Export format: 'md' (default, placed directly on root), 'rtf' (Rich Text placed directly on root), or 'both' (separated md/ and rtf/ folders)"
    )
    parser.add_argument(
        "--rtf", "-rtf",
        dest="rtf_flag",
        action="store_true",
        help="Export only Rich Text (.rtfd/.rtf) placed directly at root"
    )
    parser.add_argument(
        "--both", "-both",
        dest="both_flag",
        action="store_true",
        help="Export both Markdown (md/) and Rich Text (rtf/) in separate subfolders"
    )
    parser.add_argument(
        "--md", "-md",
        dest="md_flag",
        action="store_true",
        help="Export only Markdown placed directly at the root (default)"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to JSON configuration file for custom company/team conventions"
    )
    parser.add_argument(
        "--agents-file",
        default=None,
        help="Path to AGENTS.md to copy to the root of the output folder (default: templates/AGENTS.md)"
    )
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="Do not copy AGENTS.md guide to the exported story folder"
    )
    parser.add_argument(
        "--sdd",
        action="store_true",
        help="Enable Spec-Driven Development (SDD) mode. Exports tickets into raw-export/ and generates TRANSFORM_TO_SDD.md for the AI agent (does not generate SDD md files directly)."
    )
    parser.add_argument(
        "--tracking",
        action="store_true",
        default=None,
        help="In SDD mode, keep specs inside current project under specs/ directory (default)"
    )
    parser.add_argument(
        "--no-tracking",
        dest="no_tracking",
        action="store_true",
        help="In SDD mode, isolate specs outside code repository (e.g. in ../<project>-specs/ or --specs-dir)"
    )
    parser.add_argument(
        "--specs-dir",
        default=None,
        help="In SDD mode, custom base directory for specifications"
    )
    parser.add_argument(
        "--workspace",
        action="store_true",
        help="In SDD mode, generate a .code-workspace file linking source code and specs folder"
    )

    args = parser.parse_args()

    # Load configuration
    cfg = load_config(args.config)

    # Determine format mode (CLI flags take precedence over config)
    if args.both_flag:
        chosen_format = "both"
    elif args.rtf_flag:
        chosen_format = "rtf"
    elif args.md_flag:
        chosen_format = "md"
    elif args.format:
        chosen_format = args.format
    else:
        chosen_format = cfg.get("default_format", "md")

    # Output directory
    target_output = args.output or cfg.get("default_output_dir", ".")
    out_path = Path(os.path.expanduser(target_output))

    # SDD options
    sdd_cfg = cfg.get("sdd", {})
    sdd_mode = args.sdd or sdd_cfg.get("enabled", False)

    if args.no_tracking:
        tracking = False
    elif args.tracking is not None:
        tracking = args.tracking
    else:
        tracking = sdd_cfg.get("tracking", True)

    specs_dir = args.specs_dir or sdd_cfg.get("specs_dir")
    workspace = args.workspace or sdd_cfg.get("generate_workspace", False)

    # Handle --from-export mode
    if args.from_export:
        try:
            stage_from_export(
                export_source=Path(args.from_export),
                output_parent=out_path,
                sdd_mode=sdd_mode,
                tracking=tracking,
                specs_dir=specs_dir,
                workspace=workspace,
                config=cfg
            )
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Staging from export failed: {e}", file=sys.stderr)
            sys.exit(1)

    if not args.task:
        parser.error("A ClickUp Task URL/ID (or --from-export <folder>) is required.")

    token = resolve_token(args.token)

    try:
        export_clickup_story(
            task_id_or_url=args.task,
            output_parent=out_path,
            token=token,
            export_format=chosen_format,
            agents_file=args.agents_file,
            no_agents=args.no_agents,
            sdd_mode=sdd_mode,
            tracking=tracking,
            specs_dir=specs_dir,
            workspace=workspace,
            config=cfg
        )
    except Exception as e:
        print(f"\n❌ Export failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
