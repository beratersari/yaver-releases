"""Editable public page text.

The admin page stores replacements. A missing row uses the text in
``DEFAULTS``. Visitors never send this text; only a signed-in admin does.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from markupsafe import Markup, escape

_MAX_CHARS = 20_000
_TOKEN = re.compile(r"\{([a-z0-9_]+)\}")
_INLINE = re.compile(r"`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)")

# Order is the order of the admin form and the public pages.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("home_intro", "Release history introduction", "Release history"),
    ("home_update", "Release history, after install", "Release history"),
    ("install_intro", "Install page introduction", "Install"),
    ("windows", "Windows install", "Install"),
    ("windows_update", "Windows update", "Install"),
    ("ubuntu_intro", "Ubuntu note", "Install"),
    ("ubuntu18", "Ubuntu 18.04", "Install"),
    ("ubuntu20", "Ubuntu 20.04", "Install"),
    ("ubuntu22", "Ubuntu 22.04", "Install"),
    ("ubuntu24", "Ubuntu 24.04", "Install"),
    ("ubuntu_update", "Ubuntu update, shown in each version", "Install"),
    ("deps_intro", "Dependencies introduction", "Dependencies"),
    ("opencode_windows", "OpenCode on Windows", "Dependencies"),
    ("opencode_linux", "OpenCode on Linux", "Dependencies"),
    ("claude_windows", "Claude Code on Windows", "Dependencies"),
    ("claude_linux", "Claude Code on Linux", "Dependencies"),
    ("codex_windows", "Codex on Windows", "Dependencies"),
    ("codex_linux", "Codex on Linux", "Dependencies"),
)

# The file an operator pastes over before install. Same text the CLI zip ships.
# Destinations are the paths the install command copies that file to.
CONFIG_DESTINATIONS: dict[str, tuple[str, str]] = {
    "opencode": (
        r"%USERPROFILE%\.opencode\opencode.json",
        "~/.opencode/opencode.json",
    ),
    "claude": (
        r"%USERPROFILE%\.claude\settings.json",
        "~/.claude/settings.json",
    ),
    "codex": (
        r"%USERPROFILE%\.codex\config.toml",
        "~/.codex/config.toml",
    ),
}

SAMPLE_CONFIGS: dict[str, tuple[str, str]] = {
    "opencode": (
        "opencode.json",
        """{
  "$schema": "https://opencode.ai/config.json",
  "autoupdate": false,
  "plugin": [],
  "model": "custom/YOUR_MODEL",
  "provider": {
    "custom": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Custom host",
      "options": {
        "baseURL": "https://YOUR_HOST/v1",
        "apiKey": "{env:AI_API_KEY}"
      },
      "models": {
        "YOUR_MODEL": {
          "name": "YOUR_MODEL"
        }
      }
    }
  }
}
""",
    ),
    "claude": (
        "settings.json",
        """{
  "env": {
    "ANTHROPIC_BASE_URL": "https://YOUR_HOST"
  }
}
""",
    ),
    "codex": (
        "config.toml",
        """# Edit YOUR_HOST and YOUR_MODEL, then run install-codex.bat again.
# The token is read from the AI_API_KEY environment variable.

model = "YOUR_MODEL"
model_provider = "custom"
approval_policy = "never"
sandbox_mode = "danger-full-access"

[model_providers.custom]
name = "Custom host"
base_url = "https://YOUR_HOST/v1"
wire_api = "responses"
env_key = "AI_API_KEY"
""",
    ),
}


TOKEN_HELP: tuple[tuple[str, str], ...] = (
    ("{base}", "this site, such as http://192.168.1.20:8090"),
    ("{windows}", "Windows zip"),
    ("{ubuntu18}", "Ubuntu 18.04 zip"),
    ("{ubuntu20}", "Ubuntu 20.04 zip"),
    ("{ubuntu22}", "Ubuntu 22.04 zip"),
    ("{ubuntu24}", "Ubuntu 24.04 zip"),
    ("{opencode_windows}", "OpenCode for Windows"),
    ("{opencode_linux}", "OpenCode for Linux"),
    ("{claude_windows}", "Claude Code for Windows"),
    ("{claude_linux}", "Claude Code for Linux"),
    ("{codex_windows}", "Codex for Windows"),
    ("{codex_linux}", "Codex for Linux"),
)

def _ubuntu_steps(version: str, token: str) -> str:
    return f"""```
mkdir -p "$HOME/yaver"
curl -fL -o /tmp/yaver-{version}.zip "{{{token}}}"
unzip -o /tmp/yaver-{version}.zip -d "$HOME/yaver"
cd "$HOME/yaver"
chmod 755 yaver install-agents.sh
./install-agents.sh
if [ ! -f .env ]; then cp .env.example .env; fi
nano .env
sudo ufw allow 8080
setsid nohup ./yaver start > yaver.log 2>&1 < /dev/null &
```
"""


DEFAULTS: dict[str, str] = {
    "home_intro": (
        "Yaver runs OpenCode agents for work that arrives from Jira, GitLab, "
        "or Azure DevOps. This page is the copy your office downloads, so a "
        "new release does not have to come from the public internet one PC "
        "at a time.\n\n"
        "Pick the package that matches the computer. Windows is one package. "
        "Each Ubuntu release is its own package, because the executable build "
        "is tied to that Ubuntu version."
    ),
    "home_update": (
        "The first install is on the [install page](/install). After that, "
        "run `update.bat` on Windows or `./update.sh` on Ubuntu from the "
        "Yaver folder. Set `RELEASE_HOST` and `RELEASE_PORT` in `.env` "
        "first. The script stops Yaver, downloads the package for that "
        "computer, and replaces the program files, including `yaver.exe` "
        "or `yaver`, `_internal`, `.env.example`, `opencoderman`, and "
        "`install-agents.bat` or `install-agents.sh`. The `.env` file "
        "stays. The script file you ran stays. Start Yaver after the "
        "script finishes. If this folder does not have `update.bat` or "
        "`update.sh` yet, download the zip once, copy that script into "
        "the Yaver folder, and run it there."
    ),
    "install_intro": (
        "Open this page from the address the other computers use, then copy "
        "the commands. Everyone installs the executable. The commands "
        "download that zip, unpack it, and start Yaver."
    ),
    "windows": """The zip contains `yaver.exe`, a folder named `_internal`, `.env.example`, `install-agents.bat`, and `update.bat`. Keep `yaver.exe` and `_internal` in the same folder. Edit `.env` before the first real run and set the Jira host, token, and board id.

PowerShell:

```
curl.exe -fL -o yaver-windows.zip "{windows}"
New-Item -ItemType Directory -Force -Path yaver | Out-Null
tar.exe -xf yaver-windows.zip -C yaver
cd yaver
.\\install-agents.bat
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
.\\yaver.exe
```

Then open [http://127.0.0.1:8080](http://127.0.0.1:8080).
""",
    "windows_update": r"""```
cd C:\path\to\yaver
update.bat
```
""",
    "ubuntu_intro": (
        "Open the version that matches the computer. An executable built on "
        "Ubuntu 24.04 does not start on 22.04 or older. Check with "
        "`lsb_release -rs`. These commands use `unzip`. If it is missing, "
        "run `sudo apt-get install -y unzip` once. Edit `.env` before the "
        "first real run and set the Jira host, token, and board id. "
        "`nano .env` opens that file. If nano is missing, run "
        "`sudo apt-get install -y nano` once. Run Yaver as the account "
        "that should own the work. Do not use root. The log is `yaver.log` "
        "in that folder. The commands allow TCP and UDP port 8080 in ufw. Open "
        "[http://127.0.0.1:8080](http://127.0.0.1:8080) on that machine."
    ),
    "ubuntu18": _ubuntu_steps("18.04", "ubuntu18"),
    "ubuntu20": _ubuntu_steps("20.04", "ubuntu20"),
    "ubuntu22": _ubuntu_steps("22.04", "ubuntu22"),
    "ubuntu24": _ubuntu_steps("24.04", "ubuntu24"),
    "ubuntu_update": r"""```
cd "$HOME/yaver"
chmod 755 update.sh
./update.sh
```
""",
    "deps_intro": (
        "OpenCode, Claude Code, and Codex are not inside the Yaver executable. "
        "Each tool is its own zip. Windows and Linux are separate files. "
        "Set `AI_API_KEY` in the step above. Edit `YOUR_HOST` and "
        "`YOUR_MODEL` where that tool's config has them, then run its "
        "install command. "
        "These zips do not include agents. After Yaver is installed, "
        "`install-agents.bat` or `install-agents.sh` from the Yaver package "
        "copies the agents. The Linux commands use `unzip` and `nano`. If "
        "either is missing, run `sudo apt-get install -y unzip nano` once."
    ),
    "opencode_windows": r"""The zip contains `install-opencode.bat`, `opencode.exe`, and `opencode.json`. Set `YOUR_HOST` and `YOUR_MODEL` in `opencode.json`. The key is read from `AI_API_KEY`. Then run the commands. The install command copies `opencode.json` to `%USERPROFILE%\.opencode\opencode.json`, copies the CLI to `%USERPROFILE%\.opencode\bin`, and adds that folder to your user PATH. Open a new terminal afterward.

PowerShell:

```
curl.exe -fL -o opencode-windows.zip "{opencode_windows}"
New-Item -ItemType Directory -Force -Path opencode | Out-Null
tar.exe -xf opencode-windows.zip -C opencode
cd opencode
notepad opencode\opencode.json
.\install-opencode.bat
```
""",
    "opencode_linux": r"""The zip contains `install-opencode.sh`, the `opencode` binary, and `opencode.json`. Set `YOUR_HOST` and `YOUR_MODEL` in `opencode.json`. The key is read from `AI_API_KEY`. Then run the commands. The script copies `opencode.json` to `~/.opencode/opencode.json` and copies the CLI to `~/.opencode/bin` when OpenCode is not already on PATH.

```
mkdir -p "$HOME/opencode"
curl -fL -o /tmp/opencode-linux.zip "{opencode_linux}"
unzip -o /tmp/opencode-linux.zip -d "$HOME/opencode"
cd "$HOME/opencode"
chmod 755 install-opencode.sh opencode/opencode
nano opencode/opencode.json
./install-opencode.sh
```
""",
    "claude_windows": r"""The zip contains `install-claude.bat`, `claude.exe`, and `settings.json`. Set `YOUR_HOST` in `settings.json`. Yaver passes `AI_API_KEY` to Claude. Do not paste the key into `settings.json`. Then run the commands. The install command copies `settings.json` to `%USERPROFILE%\.claude\settings.json` and the CLI to `%USERPROFILE%\.local\bin`. Open a new terminal afterward.

PowerShell:

```
curl.exe -fL -o claude-windows.zip "{claude_windows}"
New-Item -ItemType Directory -Force -Path claude | Out-Null
tar.exe -xf claude-windows.zip -C claude
cd claude
notepad claude\settings.json
.\install-claude.bat
```
""",
    "claude_linux": r"""The zip contains `install-claude.sh`, the `claude` binary, and `settings.json`. Set `YOUR_HOST` in `settings.json`. Yaver passes `AI_API_KEY` to Claude. Do not paste the key into `settings.json`. Then run the commands. The script copies `settings.json` to `~/.claude/settings.json` and copies the CLI next to an existing `claude` on PATH, or into `~/.local/bin` on a first install.

```
mkdir -p "$HOME/claude"
curl -fL -o /tmp/claude-linux.zip "{claude_linux}"
unzip -o /tmp/claude-linux.zip -d "$HOME/claude"
cd "$HOME/claude"
chmod 755 install-claude.sh claude/claude
nano claude/settings.json
./install-claude.sh
```
""",
    "codex_windows": r"""The zip contains `install-codex.bat`, `codex.exe`, and `config.toml`. Set `YOUR_HOST` and `YOUR_MODEL` in `config.toml`. The key is read from `AI_API_KEY`. The install command copies `config.toml` to `%USERPROFILE%\.codex\config.toml` and the CLI to `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`. Open a new terminal afterward.

PowerShell:

```
curl.exe -fL -o codex-windows.zip "{codex_windows}"
New-Item -ItemType Directory -Force -Path codex | Out-Null
tar.exe -xf codex-windows.zip -C codex
cd codex
notepad codex\config.toml
.\install-codex.bat
```
""",
    "codex_linux": r"""The zip contains `install-codex.sh`, the `codex` binary, and `config.toml`. Set `YOUR_HOST` and `YOUR_MODEL` in `config.toml`. The key is read from `AI_API_KEY`. The script copies `config.toml` to `~/.codex/config.toml` and copies the CLI next to an existing `codex` on PATH, or into `~/.local/bin` on a first install.

```
mkdir -p "$HOME/codex"
curl -fL -o /tmp/codex-linux.zip "{codex_linux}"
unzip -o /tmp/codex-linux.zip -d "$HOME/codex"
cd "$HOME/codex"
chmod 755 install-codex.sh codex/codex
nano codex/config.toml
./install-codex.sh
```
""",
}


class CopyError(ValueError):
    """The submitted page text cannot be stored."""


def sections_for_edit(
    stored: Mapping[str, str],
    drafts: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    drafts = drafts or {}
    rows: list[dict[str, object]] = []
    for key, label, page in SECTIONS:
        if key in drafts:
            body = drafts[key]
        elif key in stored:
            body = stored[key]
        else:
            body = DEFAULTS[key]
        rows.append(
            {
                "key": key,
                "label": label,
                "page": page,
                "body": body,
                "tall": key not in {
                    "home_intro",
                    "home_update",
                    "install_intro",
                    "ubuntu_intro",
                    "deps_intro",
                },
            }
        )
    return rows


def public_html(stored: Mapping[str, str], tokens: Mapping[str, str]) -> dict[str, Markup]:
    rendered: dict[str, Markup] = {}
    for key, _label, _page in SECTIONS:
        raw = stored[key] if key in stored else DEFAULTS[key]
        rendered[key] = render_copy(fill(raw, tokens))
    return rendered


def clean_body(value: str) -> str:
    text = (value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > _MAX_CHARS:
        raise CopyError(f"Each text must be {_MAX_CHARS} characters or fewer.")
    return text


def fill(text: str, tokens: Mapping[str, str]) -> str:
    """Replace ``{name}`` tokens. Anything else, including ``{ Copy-Item }``, stays."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in tokens:
            return str(tokens[key])
        return match.group(0)

    return _TOKEN.sub(repl, text)


def tokens_from_url(base_url: str, host: str, port: int | None, scheme: str) -> dict[str, str]:
    base = (base_url or "").rstrip("/")
    if port is None:
        port_text = "443" if scheme == "https" else "80"
    else:
        port_text = str(port)
    return {
        "base": base,
        "host": host or "",
        "port": port_text,
        "windows": f"{base}/download/windows",
        "ubuntu18": f"{base}/download/ubuntu-18.04",
        "ubuntu20": f"{base}/download/ubuntu-20.04",
        "ubuntu22": f"{base}/download/ubuntu-22.04",
        "ubuntu24": f"{base}/download/ubuntu-24.04",
        "opencode_windows": f"{base}/download/opencode-windows",
        "opencode_linux": f"{base}/download/opencode-linux",
        "claude_windows": f"{base}/download/claude-windows",
        "claude_linux": f"{base}/download/claude-linux",
        "codex_windows": f"{base}/download/codex-windows",
        "codex_linux": f"{base}/download/codex-linux",
    }


def render_copy(text: str) -> Markup:
    """Turn admin text into HTML.

    A line that is only ``` opens a command block. `backticks` mark a short
    command. ``[label](url)`` makes a link when the url is http(s) or a
    same-site path. Every other character is escaped.
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Markup] = []
    index = 0
    while index < len(lines):
        if lines[index].strip().startswith("```"):
            index += 1
            code: list[str] = []
            while index < len(lines) and lines[index].strip() != "```":
                code.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(Markup("<pre>") + escape("\n".join(code)) + Markup("</pre>"))
            continue
        if not lines[index].strip():
            index += 1
            continue
        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip() and not lines[index].strip().startswith("```"):
            paragraph.append(lines[index])
            index += 1
        inner = Markup("<br>\n").join(_inline(line) for line in paragraph)
        blocks.append(Markup("<p>") + inner + Markup("</p>"))
    return Markup("\n").join(blocks)


def _inline(text: str) -> Markup:
    parts: list[Markup] = []
    cursor = 0
    for match in _INLINE.finditer(text):
        parts.append(escape(text[cursor:match.start()]))
        code = match.group(1)
        if code is not None:
            parts.append(Markup("<code>") + escape(code) + Markup("</code>"))
        else:
            label = match.group(2)
            url = match.group(3)
            if _href_ok(url):
                parts.append(
                    Markup('<a href="')
                    + escape(url)
                    + Markup('">')
                    + escape(label)
                    + Markup("</a>")
                )
            else:
                parts.append(escape(match.group(0)))
        cursor = match.end()
    parts.append(escape(text[cursor:]))
    return Markup("").join(parts)


def _href_ok(url: str) -> bool:
    if url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return True
    lowered = url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    rest = url.split("://", 1)[1]
    return bool(rest) and not rest.startswith("/") and "<" not in url and '"' not in url and ">" not in url


_BARE_URL = re.compile(r"https?://[^\s<>\"'`\\]+", re.IGNORECASE)


def certificate_url(text: str) -> str:
    """First external certificate address in the dependencies description.

    A markdown link wins over a bare address. Same-site paths and anything
    that would break the install command are left out.
    """

    raw = text or ""
    for match in _INLINE.finditer(raw):
        url = match.group(3)
        if url and _external_http_url(url):
            return url
    for match in _BARE_URL.finditer(_INLINE.sub(" ", raw)):
        url = match.group(0).rstrip(").,")
        if _external_http_url(url):
            return url
    return ""


def _external_http_url(url: str) -> bool:
    lowered = url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    if not _href_ok(url):
        return False
    return not any(char in url for char in " \t\r\n'`\\")
