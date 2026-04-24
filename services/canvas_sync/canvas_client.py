"""Canvas LMS API client with token refresh and pagination."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests


def refresh_access_token(
    domain: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> Dict[str, Any]:
    """Refresh a Canvas access token using the refresh token."""
    resp = requests.post(
        f"https://{domain}/login/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_next_link(link_header: Optional[str]) -> Optional[str]:
    """Parse the Link header and return the 'next' URL, or None."""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            start = part.index("<") + 1
            end = part.index(">")
            return part[start:end]
    return None


def canvas_fetch(
    domain: str,
    access_token: str,
    path: str,
    per_page: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch a Canvas API endpoint, handling pagination and rate limiting.
    Returns all results across pages.
    """
    results: List[Dict[str, Any]] = []
    url = path if path.startswith("http") else f"https://{domain}/api/v1{path}"

    if "per_page" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}per_page={per_page}"

    headers = {"Authorization": f"Bearer {access_token}"}

    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        # Rate limit handling
        remaining = float(resp.headers.get("X-Rate-Limit-Remaining", "100"))
        if remaining < 20:
            time.sleep(1)

        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            return [data]

        url = _parse_next_link(resp.headers.get("Link"))

    return results
