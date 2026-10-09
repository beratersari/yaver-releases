# Yaver releases

A small site for the office network. Install is the first page. Release history lists each published version as its own section, with a download for Windows and for each Ubuntu version. OpenCode, Claude Code, and Codex are on the Dependencies page. An admin uploads one Yaver zip that contains the Windows zip and one zip for each Ubuntu version, plus one zip for each of those tools on Windows and on Linux. Colleagues still download each system on its own. A newer upload keeps the older version in the history. When the Yaver zip contains `RELEASE_NOTES.txt`, that text is the release note for the version.

Yaver reads this site from `RELEASE_HOST` and `RELEASE_PORT` in the install `.env`. From the Yaver folder, run `update.bat` on Windows or `./update.sh` on Ubuntu. The script stops Yaver in that folder, downloads the package for that computer, and replaces the program files. `.env` and the script you ran stay. Start Yaver after the script finishes.

The install page, Release history, and the Dependencies page are edited from `/admin` after sign-in. Placeholders such as `{windows}` are filled from the address the visitor used.

## Run

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python -m yaver_releases
```

On Linux, use `python3`, `.venv/bin/pip`, and `.venv/bin/python`. `serve.bat` and `serve.sh` start it the same way when `.venv` already exists.

The Windows release is a zip, laid out the same way as a Yaver executable zip. Extract it and the folder contains `yaver-releases.exe`, `_internal`, `.env.example`, `START_HERE.txt`, and `VERSION`. Copy `.env.example` to `.env`, set the admin user and password, and start `yaver-releases.exe`. The site reads `.env` and `data` from that folder. Stop the other copy first when port 8090 is already in use. The zip does not contain a filled `.env` or the admin password.

Build that zip from this repository on Windows:

```bat
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python packaging\pyinstaller\build.py
```

The zip is `dist\yaver-releases-windows-x64-1.3.0.zip`. Its root is the executable and the files next to it. The folder name is not inside the zip.

The site listens on `0.0.0.0:8090` unless `YAVER_RELEASE_HOST` and `YAVER_RELEASE_PORT` say otherwise. Open `http://127.0.0.1:8090`.

Set both `YAVER_RELEASE_ADMIN_USER` and `YAVER_RELEASE_ADMIN_PASSWORD` before the first login. There is no default password. Downloads stay open on the LAN. The password only protects the upload page. Open `/admin` to sign in. The download pages do not link to that page. Do not forward this port to the public internet.

Windows firewall, from an elevated prompt:

```bat
netsh advfirewall firewall add rule name="Yaver releases" dir=in action=allow protocol=TCP localport=8090
```

Ubuntu: `sudo ufw allow 8090/tcp`.

## What to upload

Publish one Yaver zip. The files inside it are:

| File inside the upload | Who downloads it |
|------------------------|------------------|
| `yaver-windows-x64-0.9.79.zip` | Windows PCs |
| `yaver-linux-x64-ubuntu-18.04-0.9.79.zip` | Ubuntu 18.04 |
| `yaver-linux-x64-ubuntu-20.04-0.9.79.zip` | Ubuntu 20.04 |
| `yaver-linux-x64-ubuntu-22.04-0.9.79.zip` | Ubuntu 22.04 |
| `yaver-linux-x64-ubuntu-24.04-0.9.79.zip` | Ubuntu 24.04 |
| `RELEASE_NOTES.txt` | Release history, under that version |

The version in this example is `0.9.79`. Use the version that is in the file names. The form has no version field. A name such as `yaver-executables-0.9.79.zip` has to use that same version. All five zip files are required, and they have to share one version. `RELEASE_NOTES.txt` is optional. When it is present, its text is the release note and the notes box on the form is ignored. Release history shows that version as one collapsible section, with the note above the downloads. Each zip inside it stays its own download. The previous version stays in the history.

Dependencies are still one zip each:

| Package | Id |
|---------|----|
| OpenCode for Windows | `opencode-windows` |
| OpenCode for Linux | `opencode-linux` |
| Claude Code for Windows | `claude-windows` |
| Claude Code for Linux | `claude-linux` |
| Codex for Windows | `codex-windows` |
| Codex for Linux | `codex-linux` |

Upload the executable those PCs already run. A dependency zip is one CLI: its installer, the binary, the host config, and a `VERSION` file with that tool's version. `update.bat` and `update.sh` do not download these. `GET /api/latest` accepts only `windows`, `ubuntu-18.04`, `ubuntu-20.04`, `ubuntu-22.04`, and `ubuntu-24.04`. An executable zip has `yaver.exe` or `yaver` next to `_internal`, at the top of the zip. The install page tells people to download that zip, unpack it, and start the executable. It does not tell them to run an install-zip script. Later updates use `update.bat` or `update.sh` from that same folder.

If the uploaded Yaver zip has a single folder around the five zips, the site removes that folder before it reads the names. Each published zip is opened the same way, so a download lists `yaver.exe` or `yaver` at the top. A frozen zip that has no `update.bat` (Windows) or `update.sh` (Ubuntu) at the top receives that script before it is published. A script already in the zip stays as it was uploaded. The checksum on the site is the checksum of that published zip.

A `VERSION` file inside one of the five zips has to match the version in that file's name. A dependency leaves the version field empty when its zip has a `VERSION` file at the top. The site publishes that text. Type a dependency version only when that file is missing. A typed version that disagrees with the file is refused.

A PC running the executable will not install a full install zip, and a full install will not apply an executable zip. Uploading again for the same platform replaces the current file.

## API

`GET /api/health` returns `{"ok": true}`.

`GET /api/latest?platform=windows` returns the current package. `platform` is `windows`, `ubuntu-18.04`, `ubuntu-20.04`, `ubuntu-22.04`, or `ubuntu-24.04`. An optional `current` is the version that install is running. Each version check and each download is stored by the caller's address. The version check does not include Analytics. Update scripts use this GET.

A signed-in admin sees Analytics in the left bar on the publish page and on `/admin/analytics`. The list shows every address with its version, platform, and last contact. Selecting an address makes this site GET `http://{address}:8080/api/analytics/install` and show that install’s jobs, merge requests, and the other counts. The install, release history, and dependencies pages do not show that item. No extra setting is required. An address that has not checked in, a hostname, or a link-local address is not requested. `GET /api/admin/installations` returns the same list to that signed-in admin, or to HTTP Basic using the existing admin username and password. A missing password is rejected. The public pages do not link to it. The install’s own Analytics page stays behind that install’s dashboard password.

```json
{
  "platform": "windows",
  "version": "0.9.72",
  "filename": "yaver-windows.zip",
  "sha256": "...",
  "size": 1234,
  "layout": "frozen",
  "notes": "",
  "published_at": "2026-10-04T12:00:00+00:00",
  "download_path": "/download/windows"
}
```

`layout` is `frozen` for the executable, `source` for the install zip, or `unknown` when the zip is neither. Yaver refuses an unknown zip.

`GET /download/windows` sends the file. Yaver always downloads that path. It does not follow a redirect. `GET /download/opencode-windows` (and the other dependency ids) sends that CLI zip. `GET /api/releases` includes a `dependencies` list beside `releases`.

## Tests

```bash
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest tests -q
```
