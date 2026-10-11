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
    ("use_settings", "1. Save Settings", "How to use"),
    ("use_scheduled", "2. Start from Scheduled", "How to use"),
    ("use_existing_issue", "2.1 Run an existing Jira issue", "How to use"),
    ("use_existing_work_item", "2.2 Run an existing Azure work item", "How to use"),
    ("use_new_issue", "2.3 Create a Jira issue", "How to use"),
    ("use_new_work_item", "2.4 Create an Azure work item", "How to use"),
    ("use_existing_mr", "2.5 Continue or review a GitLab merge request", "How to use"),
    ("use_existing_pr", "2.6 Continue or review an Azure pull request", "How to use"),
    ("use_jobs", "3. Open the job", "How to use"),
    ("use_implement", "3.1 Choose Implement", "How to use"),
    ("use_revise", "3.2 Choose Revise", "How to use"),
    ("use_stop", "3.3 Choose Stop work", "How to use"),
    ("use_intro", "How to use introduction", "How to use"),
    ("use_jira", "Using it from the Jira website", "How to use"),
    ("use_review", "Using it from the GitLab or Azure website", "How to use"),
    ("use_azure", "Using it from the Azure Boards website", "How to use"),
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

Then open `http://<ip>:8080`.
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
        "`http://<ip>:8080` on that machine."
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
    "use_settings": """Open the dashboard at `http://<ip>:8080`.

1. If the page asks you to sign in, use `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` from `.env`.
2. Open Settings.
3. Enter the Jira host, the token, and the board.
4. Enter the Jira trigger user. Use the display name or username, with no `@`. To Do tickets assigned to that name are accepted. If you leave it empty, Yaver accepts an assignee named `jira ai bot`, `jira-ai-bot`, `jiraai`, or `devbot`. Trigger label is optional. When you set it, the ticket also needs that label.
5. For GitLab, add the host and its PAT, and enter the GitLab trigger user. Turn Enabled on when comments and merge requests should start work.
6. For Azure, add the collection URL and its PAT, and enter the Azure trigger user. Turn Enabled on when pull requests and work items should start work.
7. Open Agent. Set Worker to OpenCode. Set Default model to a model that is already in `opencode.json`. On Windows that file is `%USERPROFILE%\\.opencode\\opencode.json`. On Linux it is `~/.opencode/opencode.json`. Use the `model` value from that file, such as `custom/YOUR_MODEL`. Codex and Claude Code are the other workers. Install one of those only when you select it here.
8. Save.

Do this before the first job. Yaver uses these values to find your tickets and to sign its comments. An OpenCode job needs OpenCode installed. The Install page has that step.
""",
    "use_scheduled": """Open Scheduled when you are ready to start something.

Run now starts the job immediately. Schedule waits until the time you pick.

On a Jira issue or an Azure work item, Mode is plan, build, or test. Choose plan the first time if you want to read the plan before Yaver writes code. Build writes the code. Test writes tests.

A review uses a different form. Choose Existing MR for a GitLab merge request, or Existing PR for an Azure pull request. You can also assign the trigger user as a reviewer on that request. That starts the same review.
""",
    "use_existing_issue": """Use this when the Jira ticket already exists.

1. Open Scheduled.
2. Choose Existing issue, then Jira.
3. Type the issue key, such as KAN-12, and choose Look up.
4. Check the prompt, the repository, the branches, and the mode. If the ticket has no mode, the form shows build.
5. Change anything you need.
6. Choose Run now to start now, or Schedule to start later.

Yaver writes those fields back onto the Jira ticket.
""",
    "use_existing_work_item": """Use this when the Azure work item already exists.

1. Open Scheduled.
2. Choose Existing issue, then Azure work item.
3. Choose the collection, type the work item id, and choose Look up.
4. Set the prompt, the repository, the branches, and the mode. Mode is plan, build, or test.
5. Choose Run now to start now, or Schedule to start later.

Yaver writes those fields back onto the work item.
""",
    "use_new_issue": """Use this when you do not have a Jira ticket yet.

1. Open Scheduled.
2. Choose New issue, then Jira.
3. Type a title and a description.
4. Add the repository, the source branch, and the target branch.
5. Choose the issue type and Mode. Choose plan the first time if you want to read the plan before any code is written.
6. Choose Create & run now to create the ticket and start. Choose Create schedule to create the ticket and wait until the time you set.
""",
    "use_new_work_item": """Use this when you do not have an Azure work item yet.

1. Open Scheduled.
2. Choose New issue, then Azure work item.
3. Choose the collection and the team project.
4. Type a title and a description. Add the repository and the branches.
5. Choose the work item type and Mode.
6. Choose Create & run now to create the work item and start. Choose Create schedule to wait until the time you set.
""",
    "use_existing_mr": """Use this when the GitLab merge request already exists.

1. Open Scheduled.
2. Choose Existing MR.
3. Paste the repository URL, type the merge request number, and choose Look up.
4. Write what you want Yaver to do.
5. Choose the mode. Build posts your note and continues the work, and Yaver can commit and push. GitLab review reads the change and does not push. It is the same review as writing `@yaver /review` on the merge request. `/ask` is not on this form.
6. Choose Run now to start now, or Schedule to start later.

You can also start the review on the merge request itself. Assign the GitLab trigger user as a reviewer. That starts the same review. When the review finishes, the merge request shows Re-request review. Re-request review starts the review again and does not push.
""",
    "use_existing_pr": """Use this when the Azure pull request already exists.

1. Open Scheduled.
2. Choose Existing PR.
3. Paste the Azure repository URL, type the pull request id, and choose Look up.
4. Choose the mode. Build continues the work and can push. Azure review reads the change and does not push. It is the same review as `@yaver /review`. `/ask` is not on this form.
5. Choose Run now to start now, or Schedule to start later.

You can also start the review on the pull request itself. Assign the Azure trigger user as a reviewer. That starts the same review.
""",
    "use_jobs": """After you start a job, open Jobs.

The list shows each run. Open the one you just started. You see that run's prompt and its log.

When a plan is ready, this page shows Implement and Revise. The next two steps are those buttons. Stop work appears while a run is still pending, planning, or executing. It is absent while a plan is waiting.
""",
    "use_implement": """Use this after a plan is ready and you want the code.

1. Open Jobs and open the run.
2. Choose Implement.
3. On a Jira ticket, Yaver moves the ticket to In Progress when it can, and renames the label `plan_ready` to `plan_execute`. The build starts on the next poll.
4. On an Azure work item, Yaver posts `/planExecute` for the Azure trigger user. That hands the build to the work-item path.
5. When that build succeeds, Yaver pushes the branch and opens a merge request or a pull request.
""",
    "use_revise": """Use this when the plan needs a change before any code is written.

1. Open Jobs and open the run.
2. Choose Revise.
3. Type a short note about what should change, then confirm.
4. On Jira, Yaver posts a comment that mentions the Jira trigger user, removes `plan_ready` and `plan_execute`, and adds `plan_refactor`. The revision starts on the next poll.
5. On an Azure work item, Yaver posts `/planRefactor` with your note.
""",
    "use_stop": """Use this when you want the current run to stop.

1. Open Jobs and open the run.
2. Choose Stop work.

Yaver cancels that run and stops the agent. The ticket stays where it is.
""",
    "use_intro": (
        "The steps above are the dashboard. Using the dashboard is strongly "
        "recommended. It is easier. You can also use Yaver from the Jira "
        "website, the GitLab or Azure website, or the Azure Boards website. "
        "The three sections below are those same jobs."
    ),
    "use_jira": """Use this on the Jira website.

1. Create the ticket on the board you saved in Settings.
2. Leave it on To Do.
3. Assign it to the Jira trigger user.
4. Put this block in the description. Change the repository and the branches to yours.

```
{params}
Repository: https://gitlab.example.com/group/app.git
Source branch: feature/KAN-12
Target branch: develop
Mode: plan
{params}
```

5. Wait for the next poll. Yaver accepts the ticket, moves it to In Progress, and posts the plan as a comment.
6. Yaver adds the label `plan_ready` and stops. This step does not push code.
7. To write the code on that same ticket, keep it In Progress and rename `plan_ready` to `plan_execute`. Choose Implement on the job to do that rename. The build starts on the next poll.
8. To change the plan, choose Revise on the job. That posts a comment for the Jira trigger user, removes `plan_ready` and `plan_execute`, and adds `plan_refactor`. The revision starts on the next poll. Changing Mode to build on this ticket does not start the code.
9. A new ticket with `Mode: build`, and the same repository, source branch, and target branch, implements that plan in its own run. Yaver pushes the branch and opens a merge request.
10. When a run is finished and you want it again, move the ticket back to To Do and leave it assigned to the trigger user.
""",
    "use_review": """Use this on the GitLab website or the Azure website, on the merge request or the pull request.

1. On GitLab, add a project webhook for comments and merge requests. The address is the computer running Yaver, port 8080, path `/yaver/webhook/gitlab`. Use the same secret as `GITLAB_WEBHOOK_SECRET`.
2. On Azure, add a service hook to `/yaver/webhook/azure` on that same port. Azure has no webhook secret. Include pull request reviewers updated, `git.pullrequest.reviewers.update`, so assigning a reviewer can start a review.
3. Comment on the merge request or pull request. The name is the trigger user you saved in Settings.

```
@yaver /yaver cover the limiter with unit tests
```

4. Yaver replies on that thread. When the agent commits, Yaver pushes and opens or updates the merge request or pull request.
5. For a review, comment `@yaver /review`. For a question, comment `@yaver /ask`. Both read the change and do not push. An empty `/review` approves the GitLab merge request. `/ask` posts the overview and leaves approval to `/review`. A mention with no command posts a short usage note and does not start a job.
6. Assign the GitLab trigger user as a reviewer on the merge request. That starts the same review as `@yaver /review` and does not push. Opening a merge request that already lists that user as a reviewer starts it too. A draft merge request does not start the review when it is opened. A new commit by itself does not start another review.
7. A finished `/review` that has findings, a finished `/ask`, and a finished `/yaver` reply are marked reviewed, so the merge request shows Re-request review. An empty `/review` approves the merge request. Re-request review starts the review again and does not push, including after that approval.
8. Assign the Azure trigger user as a reviewer on the pull request. That starts the same review and does not push. Opening a pull request that already lists that user as a reviewer starts it too. A draft pull request does not start the review when it is opened. A new commit by itself does not start another review.
""",
    "use_azure": """Use this on the Azure Boards website, on the work item.

1. Put the same `{params}` block on the work item. Use Mode plan the first time.
2. Assign it to the Azure trigger user while the state is To Do or In Progress, or the matching column for that process, such as New, Active, or Doing.
3. Yaver moves it to the in-progress column, posts the plan, and stops.

To write the code, comment on the work item:

```
@yaver /planExecute
```

That implements the waiting plan and opens a pull request. The work item stays in progress. You close it when the pull request is done.

To change the plan, comment:

```
@yaver /planRefactor tighten the API
```

These two commands belong on the work item. A pull request comment ignores them.

Set `Mode: build` when the first assignment should write the code, with no plan step. Moving In Progress back to To Do, while the item stays assigned, does not run it again. After an error, change the title or the description while the item stays assigned to the Azure trigger user, on To Do or In Progress.

Assigning the work item starts the plan or the build. Assign the Azure trigger user as a reviewer on the pull request to start a review.
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
    "opencode_windows": r"""The zip contains `install-opencode.bat`, `opencode.exe`, and `opencode.json`. Set `YOUR_HOST` and `YOUR_MODEL` in `opencode.json`. The key is read from `AI_API_KEY`. Then run the commands. The install command copies `opencode.json` to `%USERPROFILE%\.opencode\opencode.json`. If `opencode.exe` is already on PATH, the installer replaces that file and renames the old one with the date. On a first install the CLI goes to `%USERPROFILE%\.opencode\bin`, and that folder is added to your user PATH. Open a new terminal afterward.

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
    "claude_windows": r"""The zip contains `install-claude.bat`, `claude.exe`, and `settings.json`. Set `YOUR_HOST` in `settings.json`. Yaver passes `AI_API_KEY` to Claude. Do not paste the key into `settings.json`. Then run the commands. The install command copies `settings.json` to `%USERPROFILE%\.claude\settings.json`. If `claude.exe` is already on PATH, the installer replaces that file and renames the old one with the date. On a first install the CLI goes to `%USERPROFILE%\.local\bin`. Open a new terminal afterward.

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
    "codex_windows": r"""The zip contains `install-codex.bat`, `codex.exe`, and `config.toml`. Set `YOUR_HOST` and `YOUR_MODEL` in `config.toml`. The key is read from `AI_API_KEY`. The install command copies `config.toml` to `%USERPROFILE%\.codex\config.toml`. If `codex.exe` is already on PATH, the installer replaces that file and renames the old one with the date. On a first install the CLI goes to `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`. Open a new terminal afterward.

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
                    "use_intro",
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
