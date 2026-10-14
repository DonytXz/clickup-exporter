# ClickUp Story & Subtasks Exporter

An open-source CLI tool to export ClickUp stories, subtasks, prerequisite tickets ("Blocked By"), and all embedded images into clean Markdown or macOS Rich Text (`.rtfd`/`.rtf`) formats, complete with an AI agent workspace guide (`AGENTS.md`).

---

## 🌟 Key Features

- **📦 Complete Story Hierarchy:** Automatically exports the main story, all associated subtasks, and upstream blocking dependencies ("Blocked By").
- **🖼️ Image & Attachment Ingestion:** Automatically downloads all embedded screenshots and attachments into a local `images/` directory, updating Markdown image references to relative links for instant rendering in VS Code, Cursor, Obsidian, GitHub, and browser previews.
- **📄 Flexible Export Formats:**
  - **Markdown (Default):** Generates clean `.md` files and an `images/` folder directly at the root of the exported directory.
  - **Rich Text (`--rtf`):** Generates native macOS `.rtfd` bundles (with embedded images) and `.rtf` documents using macOS `textutil`.
  - **Both (`--both`):** Generates separated `md/` and `rtf/` directories.
- **🤖 AI Agent Workspace Guide:** Includes a customizable `AGENTS.md` file in the export folder to provide coding assistants (Cursor, Copilot, Cline, Claude Code, Antigravity) with architectural context, development scopes (Frontend vs. Backend), and Git conventions.
- **🏢 Configurable for Any Company or Team:** Easily customizable via `config.json` or CLI flags for company-specific ticket prefixes (`FE`, `BE`, `API`), custom branch naming, commit rules, and template guides.
- **🔒 Privacy & Security First:** Zero telemetry and no external services. All API calls connect directly to ClickUp's official API (`api.clickup.com`). Personal API tokens stay strictly on your local machine.

---

## 📁 Output Structure Preview

```
PROJ-101 - Customer Authentication Flow/
├── AGENTS.md             # AI workspace guide, architectural standards & Git rules
├── PROJ-101 - Customer Authentication Flow.md
├── PREVIUS TICKET NEEDED PROJ-99 - SSO Infrastructure Setup.md
├── BE - User Auth Endpoints.md
├── BE - Database Schema Migration.md
├── FE - Login Form Component.md
├── FE - Password Reset View.md
└── images/
    ├── image_1.png
    ├── image_2.png
    └── ...
```

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.8 or higher.
- *(Optional)* macOS with `textutil` (pre-installed on macOS) if using Rich Text (`--rtf`) export.

### 2. Installation
Clone the repository:
```bash
git clone https://github.com/DonytXz/clickup-exporter.git
cd clickup-exporter
```

Make the bash runner executable:
```bash
chmod +x clickup-export.sh clickup_export.py
```

### 3. Configure Your ClickUp API Token
The exporter searches for your ClickUp Personal API Token in the following order:
1. `--token` CLI argument (`-t pk_...`)
2. `CLICKUP_API_TOKEN` environment variable
3. `~/.clickup_token` file (created automatically if you input your token interactively)
4. `.env` file in the working directory (copy from `.env.example`)
5. Interactive prompt on first run

To set it up via `.env`:
```bash
cp .env.example .env
# Edit .env and paste your token: CLICKUP_API_TOKEN=pk_...
```

> **How to get your ClickUp Token:**  
> In ClickUp, navigate to **Settings** ➔ **Apps** ➔ **ClickUp API** ➔ **Generate Personal API Token**.

---

## 💻 Usage & Examples

### 1. Default Export (Markdown at Root)
Exports the story, its subtasks, and dependencies as Markdown files:
```bash
./clickup-export.sh "https://app.clickup.com/t/86a1b2c3d" -o ~/Downloads
```
*(Or with Python directly)*:
```bash
python3 clickup_export.py "https://app.clickup.com/t/86a1b2c3d" -o ~/Downloads
```

### 2. Export Using Custom Task IDs
Supports custom task IDs (e.g. `PROJ-101`):
```bash
./clickup-export.sh "https://app.clickup.com/t/12345678/PROJ-101" -o ~/Downloads
# Or simply pass the ID:
./clickup-export.sh PROJ-101 -o ~/Downloads
```

### 3. Export to Rich Text (`--rtf`)
Exports native macOS rich text files (`.rtfd` bundles with embedded images and `.rtf` files):
```bash
./clickup-export.sh PROJ-101 -o ~/Downloads -rtf
```

### 4. Export Both Formats (`--both`)
Creates separated `md/` and `rtf/` directories inside the story folder:
```bash
./clickup-export.sh PROJ-101 -o ~/Downloads -both
```

### 5. Skip the Agent Guide (`--no-agents`)
If you do not need the `AGENTS.md` file copied to the exported directory:
```bash
./clickup-export.sh PROJ-101 --no-agents
```

---

## ⚙️ Customization for Your Company / Team

You can customize the exporter for any organization by creating a `config.json` (or `clickup_config.json`) in the project root:

```bash
cp config.example.json config.json
```

### Configuration Options (`config.json`):
```json
{
  "company_name": "Company X",
  "default_output_dir": "~/Downloads",
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
    "include": true,
    "template_path": "templates/AGENTS.md"
  }
}
```

- **`task_conventions`**: Defines prefixes used by your team to distinguish Frontend tasks (development scope) from Backend tasks (API reference/context).
- **`git_conventions`**: Sets the default branch prefix (e.g., `feature/PROJ-101-...`) and commit syntax generated in ticket headers.
- **`agents_guide`**: Configures whether `AGENTS.md` is bundled and the path to your custom template.

You can also pass a custom configuration file at runtime:
```bash
python3 clickup_export.py PROJ-101 --config path/to/custom-config.json
```

---

## 📋 CLI Options Reference

| Option | Flag | Description | Default |
| :--- | :--- | :--- | :--- |
| **Task** | *(positional)* | ClickUp Task URL or Task ID (standard or custom ID like `PROJ-101`). | *(Required)* |
| **Output** | `-o`, `--output` | Destination parent directory. | `.` (Current dir) |
| **Token** | `-t`, `--token` | ClickUp Personal API Token (`pk_...`). | Reads `~/.clickup_token` or env |
| **Format** | `-f`, `--format` | Format mode: `md`, `rtf`, or `both`. | `md` |
| **Markdown** | `--md`, `-md` | Export only Markdown placed directly at root. | **Yes (Default)** |
| **Rich Text** | `--rtf`, `-rtf` | Export only Rich Text placed directly at root. | `false` |
| **Both** | `--both`, `-both` | Export both formats in separate `md/` and `rtf/` subfolders. | `false` |
| **Config** | `--config` | Path to custom JSON configuration file. | Looks for `config.json` |
| **Agents Guide** | `--agents-file` | Path to custom `AGENTS.md` template file. | `templates/AGENTS.md` |
| **No Agents** | `--no-agents` | Skip copying `AGENTS.md` to the output folder. | `false` |
| **Help** | `-h`, `--help` | Show command usage and options. | |

---

## 🔒 Security & Privacy

- **No Hardcoded Secrets:** This project contains zero hardcoded API keys, tokens, or private workspace identifiers.
- **Local Credentials:** Your API token is stored securely on your local machine and is only sent via HTTPS headers directly to `api.clickup.com`.
- **Git Protection:** The included `.gitignore` prevents `.env`, `*.token`, `.clickup_token`, and exported ticket files from ever being accidentally committed.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
