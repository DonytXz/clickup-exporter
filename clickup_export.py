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

Usage:
  python3 clickup_export.py <TASK_URL_OR_ID> [options]

Examples:
  python3 clickup_export.py https://app.clickup.com/t/86a1b2c3d
  python3 clickup_export.py https://app.clickup.com/t/12345678/PROJ-101 --output ~/Downloads
  python3 clickup_export.py PROJ-101 --format both
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
    "development_profile": {
        "role": "agnostic",           # "agnostic", "frontend", "backend", "fullstack"
        "framework": "generic",       # "generic", "angular", "react", "vue", "nestjs", "fastapi", etc.
        "language": "generic",        # "generic", "typescript", "python", "go", etc.
        "architecture_style": "clean-architecture"
    },
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
    }
}


def load_dotenv(dotenv_path: Path = None):
    """Loads environment variables from .env if present and not already set in os.environ."""
    if dotenv_path is None:
        dotenv_path = Path(".env")
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


def render_agents_template(template_content: str, dev_prof: dict) -> str:
    """Renders AGENTS.md template with dynamic profile values if placeholders exist."""
    role = (dev_prof.get("role") or "agnostic").lower()
    framework = dev_prof.get("framework") or "generic"
    language = dev_prof.get("language") or "generic"
    arch_style = dev_prof.get("architecture_style") or "clean-architecture"

    if role == "agnostic":
        summary_lines = [
            "- **Modo:** Agnóstico / Adaptable al contexto del repositorio (`agnostic`)",
            "- **Framework:** Detección automática según el repositorio (o genérico)",
            "- **Lenguaje:** Detección automática según el repositorio (o genérico)",
            f"- **Arquitectura base:** {arch_style}"
        ]
    else:
        summary_lines = [
            f"- **Rol activo:** {role.capitalize()} (`{role}`)",
            f"- **Framework:** {framework}",
            f"- **Lenguaje:** {language}",
            f"- **Arquitectura base:** {arch_style}"
        ]
    profile_summary = "\n".join(summary_lines)

    replacements = {
        "{{DEV_PROFILE_SUMMARY}}": profile_summary,
        "{{DEV_ROLE}}": role,
        "{{FRAMEWORK}}": framework,
        "{{LANGUAGE}}": language,
        "{{ARCHITECTURE_STYLE}}": arch_style,
    }
    rendered = template_content
    for k, v in replacements.items():
        rendered = rendered.replace(k, v)
    return rendered


def load_config(config_path: str = None) -> dict:
    """
    Loads configuration from a JSON file if present, merged with defaults.
    Checks:
      1. Explicit config_path (if supplied)
      2. config.json in current directory
      3. clickup_config.json in current directory
      4. config.json in script directory
    Environment variables (.env / os.environ) can also override profile settings.
    """
    import copy
    load_dotenv()
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

    dev_prof = config.setdefault("development_profile", {})
    if "CLICKUP_DEV_ROLE" in os.environ:
        dev_prof["role"] = os.environ["CLICKUP_DEV_ROLE"].strip().lower()
    if "CLICKUP_FRAMEWORK" in os.environ:
        dev_prof["framework"] = os.environ["CLICKUP_FRAMEWORK"].strip().lower()
    if "CLICKUP_LANGUAGE" in os.environ:
        dev_prof["language"] = os.environ["CLICKUP_LANGUAGE"].strip().lower()
    if "CLICKUP_ARCH_STYLE" in os.environ:
        dev_prof["architecture_style"] = os.environ["CLICKUP_ARCH_STYLE"].strip().lower()

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
                data = resp.read()
                return json.loads(data.decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"ClickUp API Error ({e.code}): {error_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error accessing ClickUp: {e.reason}") from e

    def load_authorized_teams(self) -> list:
        """Validate token and fetch all workspaces/teams accessible with this token."""
        try:
            res = self._get("team")
            self.authorized_teams = res.get("teams", [])
            return self.authorized_teams
        except RuntimeError as e:
            raise RuntimeError(
                f"Failed to authenticate with ClickUp API.\n"
                f"Details: {e}\n"
                f"Please ensure your Personal API Token (pk_...) is valid and not expired."
            ) from e

    def get_task(self, task_id: str, hint_team_id: str = None) -> dict:
        """
        Fetch task details with automatic resolution for standard IDs,
        Custom Task IDs (e.g. PROJ-101), and workspace authorization.
        """
        if not self.authorized_teams:
            self.load_authorized_teams()

        candidate_team_ids = []
        if hint_team_id:
            candidate_team_ids.append(str(hint_team_id))
        if self.active_team_id and str(self.active_team_id) not in candidate_team_ids:
            candidate_team_ids.append(str(self.active_team_id))
        for t in self.authorized_teams:
            tid = str(t.get("id"))
            if tid not in candidate_team_ids:
                candidate_team_ids.append(tid)

        is_custom_id_format = ("-" in task_id) or (len(task_id) > 15)
        last_error = None

        # Strategy 1: Standard internal ID lookup (if not explicitly custom-formatted)
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

        # Strategy 2: Custom Task ID lookup across authorized teams
        for tid in candidate_team_ids:
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
    lines.append(f"> **Ticket ClickUp:** [`{display_id}`]({url}) | **ID Interno:** `{internal_id}` | **Estado:** `{status_str}`")

    dev_prof = cfg.get("development_profile", {})
    dev_role = (dev_prof.get("role") or "agnostic").lower()

    if role == "story":
        slug = to_kebab_case(name)
        branch_name = f"{branch_prefix}/{display_id}-{slug}"
        commit_example = f"{commit_type} : {display_id} - {name}"
        lines.append(f"> **Ámbito:** 🌟 **Historia Principal (Main Story)**")
        lines.append(f">")
        lines.append(f"> 📌 **Recomendación por defecto (Ramas y PR):**")
        lines.append(f"> Crear la rama Git y el Pull Request **directamente para esta Historia Principal (`{display_id}`)**.")

        if dev_role == "frontend":
            lines.append(f"> Todas las subtareas de Frontend (`FE - ...`) deben desarrollarse e integrarse dentro de esta misma rama.")
        elif dev_role == "backend":
            lines.append(f"> Todas las subtareas de Backend (`BE - ...`) deben desarrollarse e integrarse dentro de esta misma rama.")
        elif dev_role == "fullstack":
            lines.append(f"> Todas las subtareas (Frontend y Backend) deben desarrollarse e integrarse coordinadamente dentro de esta misma rama.")
        else:  # agnostic (default)
            lines.append(f"> Las subtareas asociadas deben desarrollarse e integrarse dentro de esta misma rama según el alcance técnico del repositorio activo.")

        lines.append(f"> - **Rama sugerida:** `{branch_name}`")
        lines.append(f"> - **Commit base:** `{commit_example}`")

        if subtasks:
            lines.append("\n### 📋 Subtareas Asociadas (Subtasks)\n")
            lines.append("| Ticket ID | Subtarea | Ámbito | Rol / Propósito |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for sub in subtasks:
                sub_cid = sub.get("custom_id") or sub.get("id")
                sub_name = sub.get("name", f"Subtask-{sub.get('id')}")
                sub_url = sub.get("url", f"https://app.clickup.com/t/{sub.get('id')}")
                sub_md_name = f"{sanitize_filename(sub_name)}.md"
                sub_encoded = urllib.parse.quote(sub_md_name)

                # Detect FE vs BE using configured prefixes
                upper_name = sub_name.strip().upper()
                is_fe_sub = any(upper_name.startswith(p) or f" {p}" in upper_name or f"[{p}]" in upper_name for p in fe_prefixes)
                is_be_sub = any(upper_name.startswith(p) or f" {p}" in upper_name or f"[{p}]" in upper_name for p in be_prefixes)

                if is_fe_sub:
                    ambito = "Frontend"
                    if dev_role == "frontend":
                        prop = "🛠️ **Implementación / Desarrollo directo**"
                    elif dev_role == "backend":
                        prop = "ℹ️ Solo Contexto UI / Flujos de Usuario"
                    elif dev_role == "fullstack":
                        prop = "🛠️ **Implementación / Desarrollo (Capa Cliente)**"
                    else:  # agnostic
                        prop = "🛠️ Desarrollo FE (o contexto UI si se trabaja en BE)"
                elif is_be_sub:
                    ambito = "Backend"
                    if dev_role == "backend":
                        prop = "🛠️ **Implementación / Desarrollo directo (APIs, DB)**"
                    elif dev_role == "frontend":
                        prop = "ℹ️ Solo Contexto / Especificación API y Contratos"
                    elif dev_role == "fullstack":
                        prop = "🛠️ **Implementación / Desarrollo (Capa Servidor / DB)**"
                    else:  # agnostic
                        prop = "🛠️ Desarrollo BE (o contratos API si se trabaja en FE)"
                else:
                    ambito = "General"
                    prop = "Tarea asociada"

                lines.append(f"| [`{sub_cid}`]({sub_url}) | [{sub_name}]({sub_encoded}) | {ambito} | {prop} |")

    elif role == "subtask":
        upper_name = name.strip().upper()
        is_fe = any(upper_name.startswith(p) or f" {p}" in upper_name or f"[{p}]" in upper_name for p in fe_prefixes)
        is_be = any(upper_name.startswith(p) or f" {p}" in upper_name or f"[{p}]" in upper_name for p in be_prefixes)

        parent_cid = parent_task.get("custom_id") or parent_task.get("id") if parent_task else "Parent"
        parent_name = parent_task.get("name", "Historia Principal") if parent_task else "Historia Principal"
        parent_md = f"{sanitize_filename(parent_name)}.md"
        parent_encoded = urllib.parse.quote(parent_md)

        lines.append(f"> **Historia Principal (Parent):** [`{parent_cid} - {parent_name}`]({parent_encoded})")

        # Dynamically shorten custom ticket IDs (e.g., 'PROJ-101' -> 'T101', 'TASK-4900' -> 'T4900')
        id_match = re.match(r'^[A-Za-z]+[-_]?(\d+)$', display_id)
        short_sub_id = f"T{id_match.group(1)}" if id_match else display_id

        if is_fe:
            lines.append(f"> **Ámbito:** 🛠️ **Frontend (Capa de Cliente / UI)**")
            lines.append(f">")
            lines.append(f"> 📌 **Recomendación por defecto (Ramas y PR):**")
            lines.append(f"> Por defecto, **NO crear una rama ni PR individual para esta subtarea**. Trabajar e integrar los cambios en la rama de la **Historia Principal** (`{branch_prefix}/{parent_cid}-...`).")
            lines.append(f"> - **Commit sugerido:** `{commit_type} : {parent_cid}_({short_sub_id}) - {name}` o `{commit_type} : {parent_cid} - {name}`")
            lines.append(f"> - **Vincular en PR:** En el PR de la Historia Principal, agregar este ticket (`{display_id}`) bajo `## Tickets relacionados`.")
            if dev_role == "backend":
                lines.append(f"> ℹ️ **Nota de Rol (Backend):** Utilizar como contexto de interfaz de usuario y contratos de datos requeridos por el cliente.")
            elif dev_role == "agnostic":
                lines.append(f"> ℹ️ **Alcance según repositorio:** Si el repositorio activo es de Frontend, implementar directamente. Si es de Backend, usar como referencia de requerimientos UI.")
        elif is_be:
            lines.append(f"> **Ámbito:** ⚙️ **Backend (Capa de Servidor / APIs / DB)**")
            lines.append(f">")
            lines.append(f"> 📌 **Recomendación por defecto (Ramas y PR):**")
            lines.append(f"> Por defecto, **NO crear una rama ni PR individual para esta subtarea**. Trabajar e integrar los cambios en la rama de la **Historia Principal** (`{branch_prefix}/{parent_cid}-...`).")
            lines.append(f"> - **Commit sugerido:** `{commit_type} : {parent_cid}_({short_sub_id}) - {name}` o `{commit_type} : {parent_cid} - {name}`")
            lines.append(f"> - **Vincular en PR:** En el PR de la Historia Principal, agregar este ticket (`{display_id}`) bajo `## Tickets relacionados`.")
            if dev_role == "frontend":
                lines.append(f"> ⚠️ **Atención:** Este ticket es únicamente para referencia de contratos, DTOs y endpoints de API/BD. **No modificar código de backend** salvo instrucción explícita o estar en un repositorio de backend.")
            elif dev_role == "agnostic":
                lines.append(f"> ℹ️ **Alcance según repositorio:** Si el repositorio activo es de Backend, implementar endpoints, modelos y servicios. Si es de Frontend, usar como referencia de contratos y endpoints.")
        else:
            lines.append(f"> **Ámbito:** General")
            lines.append(f"> 📌 **Recomendación:** Integrar en la rama de la Historia Principal (`{parent_cid}`).")

    elif role == "prerequisite":
        lines.append(f"> **Tipo:** 🛑 **Prerrequisito / Ticket Bloqueante (Blocked By)**")
        if parent_task:
            p_cid = parent_task.get("custom_id") or parent_task.get("id")
            p_name = parent_task.get("name", "Historia Principal")
            p_md = f"{sanitize_filename(p_name)}.md"
            lines.append(f"> **Historia Dependiente:** [`{p_cid} - {p_name}`]({urllib.parse.quote(p_md)})")
        lines.append(f"> **Propósito:** Requerimiento previo necesario para la historia principal. Revisar como contexto y dependencias de pantalla o contratos previos.")

    lines.append("\n---\n")
    return "\n".join(lines) + "\n"


def process_task_content(client: ClickUpClient, task: dict, images_dir: Path, image_counter: list,
                         role: str = "story", parent_task: dict = None, subtasks: list = None,
                         config: dict = None) -> tuple:
    raw_md = task.get("markdown_description") or task.get("description") or task.get("text_content") or ""
    downloaded_images = []

    md_img_pattern = re.compile(r'!\[(.*?)\]\((https?://[^\s\)]+)\)')
    html_img_pattern = re.compile(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', re.IGNORECASE)

    found_urls = set()
    for match in md_img_pattern.findall(raw_md):
        url = match[1] if isinstance(match, tuple) else match
        found_urls.add(url)
    for match in html_img_pattern.findall(raw_md):
        url = match if isinstance(match, str) else match[0]
        found_urls.add(url)

    for att in task.get("attachments", []):
        att_url = att.get("url")
        mimetype = att.get("mimetype", "")
        if att_url and (mimetype.startswith("image/") or any(att_url.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"])):
            found_urls.add(att_url)

    url_to_local = {}
    for url in found_urls:
        image_counter[0] += 1
        ext = ".png"
        path_part = urllib.parse.urlparse(url).path
        for candidate_ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"]:
            if path_part.lower().endswith(candidate_ext):
                ext = candidate_ext
                break

        img_filename = f"image_{image_counter[0]}{ext}"
        local_img_path = images_dir / img_filename

        try:
            client.download_file(url, local_img_path)
            url_to_local[url] = f"images/{img_filename}"
            downloaded_images.append(local_img_path)
        except Exception as e:
            print(f"  [Warning] Could not download image {url}: {e}", file=sys.stderr)

    processed_md = raw_md
    for remote_url, local_rel_path in url_to_local.items():
        processed_md = processed_md.replace(remote_url, local_rel_path)

    # Append any task attachments not already embedded in the body text
    unreferenced = []
    for att in task.get("attachments", []):
        att_url = att.get("url")
        if att_url in url_to_local and att_url not in raw_md:
            att_title = att.get("title") or "Attachment"
            rel_path = url_to_local[att_url]
            unreferenced.append(f"![{att_title}]({rel_path})\n*{att_title}*")

    if unreferenced:
        processed_md += "\n\n---\n\n## 📎 Adjuntos adicionales (Task Attachments)\n\n" + "\n\n".join(unreferenced) + "\n"

    header = generate_task_header(task, role=role, parent_task=parent_task, subtasks=subtasks, config=config)
    full_md = header + processed_md

    return full_md, downloaded_images


def convert_to_rtfd_if_possible(md_content: str, output_path: Path, work_dir: Path, has_images: bool, display_prefix: str = ""):
    html_content = simple_md_to_html(md_content)
    temp_html = work_dir / f"_temp_{output_path.stem}.html"
    try:
        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(html_content)

        fmt = "rtfd" if has_images else "rtf"
        target_file = output_path.with_suffix(f".{fmt}")

        subprocess.run(
            ["textutil", "-convert", fmt, str(temp_html.name), "-output", str(target_file.resolve())],
            cwd=str(work_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(f"  -> Saved Rich Text: {display_prefix}{target_file.name}")
    except Exception as e:
        print(f"  [Note] textutil conversion skipped/failed: {e}")
    finally:
        if temp_html.exists():
            temp_html.unlink()


def export_clickup_story(
    task_id_or_url: str,
    output_parent: Path,
    token: str,
    export_format: str = "md",
    agents_file: str = None,
    no_agents: bool = False,
    config: dict = None
):
    cfg = config or DEFAULT_CONFIG
    client = ClickUpClient(token)
    
    # Normalize format
    fmt = export_format.lower()
    if fmt in ("md", "markdown"):
        mode = "md"
    elif fmt in ("rtf", "rtfd"):
        mode = "rtf"
    elif fmt in ("both", "all"):
        mode = "both"
    else:
        mode = "md"

    print("\n[1/5] Connecting to ClickUp API & Verifying Workspace...")
    teams = client.load_authorized_teams()
    teams_str = ", ".join([f"'{t.get('name')}' (ID: {t.get('id')})" for t in teams])
    print(f"      Authorized Workspaces: {teams_str or 'None'}")

    task_id, team_id_hint = parse_clickup_input(task_id_or_url)
    print(f"\n[2/5] Fetching Main Story details (Task ID: {task_id})...")
    
    main_task = client.get_task(task_id, hint_team_id=team_id_hint)
    task_name = main_task.get("name", f"Task-{task_id}")

    # If the provided ticket is a subtask (has a parent), auto-resolve to the Main Story
    parent_id = main_task.get("parent")
    if parent_id:
        sub_cid = main_task.get("custom_id") or task_id
        print(f"      [Info] Provided ticket '{task_name}' ({sub_cid}) is a subtask (Parent ID: {parent_id}).")
        print(f"      -> Auto-resolving to the Main Story to export entire story and all subtasks...")
        main_task = client.get_task(parent_id, hint_team_id=client.active_team_id)
        story_title = main_task.get("name", f"Task-{parent_id}")
    else:
        story_title = task_name

    folder_name = sanitize_filename(story_title)

    export_folder = output_parent / folder_name
    export_folder.mkdir(parents=True, exist_ok=True)

    # Configure directory structure based on mode:
    # 1. mode == 'md' (default): Markdown files & images/ placed directly on root of export_folder
    # 2. mode == 'rtf': RTF files placed directly on root of export_folder (no subfolder), temp md cleaned up
    # 3. mode == 'both': Both md/ and rtf/ subdirectories created
    if mode == "both":
        md_dir = export_folder / "md"
        rtf_dir = export_folder / "rtf"
        images_dir = md_dir / "images"
        md_dir.mkdir(parents=True, exist_ok=True)
        rtf_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
    elif mode == "rtf":
        md_dir = export_folder / "_temp_work"
        rtf_dir = export_folder  # Directly on root of export folder
        images_dir = md_dir / "images"
        md_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
    else:  # mode == 'md' (default)
        md_dir = export_folder
        rtf_dir = None
        images_dir = export_folder / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

    print(f"      Target folder: {export_folder}")
    if mode == "md":
        print(f"      - Mode: Markdown default (files placed directly at root)")
    elif mode == "rtf":
        print(f"      - Mode: RTF only (files placed directly at root)")
    elif mode == "both":
        print(f"      - Mode: Both (Markdown in md/, Rich Text in rtf/)")

    image_counter = [0]
    subtasks = main_task.get("subtasks", [])

    rtf_prefix = "rtf/" if mode == "both" else ""

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
        prefix = "md/" if mode == "both" else ""
        print(f"  -> Saved Markdown: {prefix}{main_md_file.name}")

    if mode in ("rtf", "both") and rtf_dir:
        rtf_base = rtf_dir / sanitize_filename(story_title)
        convert_to_rtfd_if_possible(main_md, rtf_base, md_dir, bool(main_imgs), display_prefix=rtf_prefix)

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
                    prefix = "md/" if mode == "both" else ""
                    print(f"        -> Saved Markdown: {prefix}{p_md_file.name}")

                if mode in ("rtf", "both") and rtf_dir:
                    p_rtf_base = rtf_dir / filename_base
                    convert_to_rtfd_if_possible(p_md, p_rtf_base, md_dir, bool(p_imgs), display_prefix=rtf_prefix)

            except Exception as e:
                print(f"      [Warning] Failed to fetch prerequisite {p_id}: {e}", file=sys.stderr)
    else:
        print("      No 'Blocked By' prerequisite tickets detected.")

    # --- 3. Process Subtasks ---
    print(f"\n[5/5] Processing {len(subtasks)} Subtask(s)...")

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

            if mode in ("md", "both"):
                sub_md_file = md_dir / f"{sanitize_filename(sub_name)}.md"
                with open(sub_md_file, "w", encoding="utf-8") as f:
                    f.write(sub_md)
                prefix = "md/" if mode == "both" else ""
                print(f"        -> Saved Markdown: {prefix}{sub_md_file.name}")

            if mode in ("rtf", "both") and rtf_dir:
                sub_rtf_base = rtf_dir / sanitize_filename(sub_name)
                convert_to_rtfd_if_possible(sub_md, sub_rtf_base, md_dir, bool(sub_imgs), display_prefix=rtf_prefix)

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

    # In 'both' mode, create convenience symlink at root of folder for images
    if mode == "both" and images_dir.exists() and any(images_dir.iterdir()):
        top_images = export_folder / "images"
        if not top_images.exists():
            try:
                top_images.symlink_to(Path("md") / "images")
            except Exception:
                pass

    # Include AGENTS.md guide if enabled
    agents_guide_cfg = cfg.get("agents_guide", {})
    should_include_agents = not no_agents and agents_guide_cfg.get("include", True)

    if should_include_agents:
        template_target = agents_file or agents_guide_cfg.get("template_path") or str(DEFAULT_AGENTS_MD)
        candidate_agents = Path(template_target)
        if candidate_agents.exists():
            dest_agents = export_folder / "AGENTS.md"
            dev_prof = cfg.get("development_profile", {})
            try:
                raw_template = candidate_agents.read_text(encoding="utf-8")
                rendered_template = render_agents_template(raw_template, dev_prof)
                dest_agents.write_text(rendered_template, encoding="utf-8")
                print(f"  -> Included AGENTS.md at root: {dest_agents.name} (profile: {dev_prof.get('role', 'agnostic')})")
            except Exception as e:
                import shutil
                shutil.copy2(candidate_agents, dest_agents)
                print(f"  -> Included AGENTS.md at root: {dest_agents.name}")

    print("\n" + "=" * 60)
    print("✅ Export completed successfully!")
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
    load_dotenv()
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


def main():
    parser = argparse.ArgumentParser(
        description="Export ClickUp stories, subtasks, prerequisites ('blocked by'), and images into a local folder."
    )
    parser.add_argument(
        "task",
        help="ClickUp Task URL (e.g. https://app.clickup.com/t/86a1b2c3d or https://app.clickup.com/t/12345678/PROJ-101) or Task ID"
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
        "--role", "-r",
        choices=["agnostic", "frontend", "backend", "fullstack"],
        default=None,
        help="Development profile role: 'agnostic' (default), 'frontend', 'backend', or 'fullstack'"
    )
    parser.add_argument(
        "--framework",
        default=None,
        help="Target framework (e.g. 'generic', 'angular', 'react', 'vue', 'nestjs', 'fastapi')"
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Primary programming language (e.g. 'generic', 'typescript', 'python', 'go')"
    )
    parser.add_argument(
        "--arch-style",
        default=None,
        help="Architecture style (e.g. 'clean-architecture', 'hexagonal', 'modular')"
    )

    args = parser.parse_args()

    # Load configuration
    cfg = load_config(args.config)

    # CLI profile flags take top precedence over config and env
    dev_prof = cfg.setdefault("development_profile", {})
    if args.role:
        dev_prof["role"] = args.role.strip().lower()
    if args.framework:
        dev_prof["framework"] = args.framework.strip().lower()
    if args.language:
        dev_prof["language"] = args.language.strip().lower()
    if args.arch_style:
        dev_prof["architecture_style"] = args.arch_style.strip().lower()

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

    token = resolve_token(args.token)

    try:
        export_clickup_story(
            task_id_or_url=args.task,
            output_parent=out_path,
            token=token,
            export_format=chosen_format,
            agents_file=args.agents_file,
            no_agents=args.no_agents,
            config=cfg
        )
    except Exception as e:
        print(f"\n❌ Export failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
