# Yaver releases

A small site for the office network. It shows the current Yaver packages, explains how to install them, and lets an admin upload a new Windows zip and one zip for each Ubuntu version.

Yaver reads this site from `RELEASE_HOST` and `RELEASE_PORT`. Stop Yaver, then run `yaver update` (Windows: `yaver.exe update`). The command reads `RELEASE_HOST` and `RELEASE_PORT` from `.env`, downloads the package for that computer, and starts Yaver again with the same `.env` and data folder.

The releases page and the install page are edited from `/admin` after sign-in. Placeholders such as `{windows}` are filled from the address the visitor used.

## Run

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python -m yaver_releases
```

On Linux, use `python3`, `.venv/bin/pip`, and `.venv/bin/python`. `serve.bat` and `serve.sh` start it the same way when `.venv` already exists.

The site listens on `0.0.0.0:8090` unless `YAVER_RELEASE_HOST` and `YAVER_RELEASE_PORT` say otherwise. Open `http://127.0.0.1:8090`.

Set both `YAVER_RELEASE_ADMIN_USER` and `YAVER_RELEASE_ADMIN_PASSWORD` before the first login. There is no default password. Downloads stay open on the LAN. The password only protects the upload page. Open `/admin` to sign in. The download pages do not link to that page. Do not forward this port to the public internet.

Windows firewall, from an elevated prompt:

```bat
netsh advfirewall firewall add rule name="Yaver releases" dir=in action=allow protocol=TCP localport=8090
```

Ubuntu: `sudo ufw allow 8090/tcp`.

## What to upload

Publish one zip per platform:

| Platform | Who downloads it |
|----------|------------------|
| Windows | Windows PCs |
| Ubuntu 18.04 | Ubuntu 18.04 |
| Ubuntu 20.04 | Ubuntu 20.04 |
| Ubuntu 22.04 | Ubuntu 22.04 |
| Ubuntu 24.04 | Ubuntu 24.04 |

Upload the executable those PCs already run. An executable zip has `yaver.exe` or `yaver` next to `_internal`, at the top of the zip. The install page tells people to download that zip, unpack it, and start the executable. It does not tell them to run an install-zip script.

If the uploaded zip has a single folder around those files, the site removes that folder before it publishes. A download then opens onto the binary and the other files. The checksum on the site is the checksum of that published zip.

Leave the version field empty when the zip has a `VERSION` file at the top. The site publishes that text. A filename that contains `latest`, such as `yaver-windows-latest.zip` or `yaver-ubuntu-22.04-latest.zip`, is the usual executable upload. Type a version only when that file is missing. A typed version that disagrees with the file is refused.

A PC running the executable will not install a full install zip, and a full install will not apply an executable zip. Uploading again for the same platform replaces the current file.

## API

`GET /api/health` returns `{"ok": true}`.

`GET /api/latest?platform=windows` returns the current package. `platform` is `windows`, `ubuntu-18.04`, `ubuntu-20.04`, `ubuntu-22.04`, or `ubuntu-24.04`.

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

`GET /download/windows` sends the file. Yaver always downloads that path. It does not follow a redirect.

## Tests

```bash
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest tests -q
```
