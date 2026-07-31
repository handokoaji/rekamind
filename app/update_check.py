import json
import urllib.request

# Filled in once when releases actually exist for this repo (GitHub or the
# UGM GitLab instance both expose a similar Releases API shape). Left blank
# on purpose: an empty URL means this feature makes zero network requests.
RELEASES_API_URL = ""
RELEASES_PAGE_URL = ""


def _parse_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.lstrip("v").split("."))


def _latest_tag(payload) -> str | None:
    if isinstance(payload, list):
        if not payload:
            return None
        return payload[0].get("tag_name")
    if isinstance(payload, dict):
        return payload.get("tag_name")
    return None


def check_for_update(current_version: str, releases_api_url: str) -> str | None:
    """Returns the newer version string (e.g. "0.2.0") if the Releases API
    reports one newer than current_version, else None -- including on any
    failure (blank URL, network error, malformed response). Never raises."""
    if not releases_api_url:
        return None
    try:
        with urllib.request.urlopen(releases_api_url, timeout=5) as response:
            payload = json.loads(response.read())
        tag = _latest_tag(payload)
        if not tag:
            return None
        latest = tag.lstrip("v")
        if _parse_version(latest) > _parse_version(current_version):
            return latest
        return None
    except Exception:
        return None
