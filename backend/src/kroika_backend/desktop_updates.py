"""User-triggered release check; never execute downloaded code or expose AI credentials."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .desktop_preferences import PreferenceError
from .desktop_version import VERSION, REPOSITORY, RELEASES_URL


def check_updates() -> dict:
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"Kroika-Desktop/{VERSION}",
    })
    try:
        with urlopen(request, timeout=12) as response:
            content = response.read(1_000_001)
        if len(content) > 1_000_000:
            raise ValueError()
        release = json.loads(content)
        match = re.fullmatch(r"desktop-v(\d+)\.(\d+)\.(\d+)", release.get("tag_name", ""))
        if not match or release.get("draft") or release.get("prerelease"):
            raise ValueError()
        version = ".".join(match.groups())
        names = {item["name"] for item in release.get("assets", [])}
        available = (tuple(map(int, match.groups())) > tuple(map(int, VERSION.split(".")))
                     and f"Kroika-{version}-windows-x64-setup.exe" in names
                     and "SHA256SUMS.txt" in names)
        return {"current_version": VERSION, "latest_version": version,
                "available": available, "release_url": RELEASES_URL}
    except HTTPError as error:
        if error.code == 404:
            return {"current_version": VERSION, "latest_version": None,
                    "available": False, "release_url": RELEASES_URL}
        raise PreferenceError("Не удалось проверить обновления. Попробуйте позднее.") from error
    except (URLError, OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise PreferenceError("Не удалось проверить обновления. Проверьте интернет или откройте страницу выпусков.") from error
