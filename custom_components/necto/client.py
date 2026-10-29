"""Experimental, unverified client for the observed Necto website flow.

Never use this client with production credentials until verified against the
service. Session construction and lifecycle belong to the caller.
"""

from html.parser import HTMLParser
import json
from urllib.parse import unquote, urljoin, urlsplit

BASE = "https://app.getnecto.com"


class NectoError(Exception):
    """Necto response or service error without sensitive response content."""


class NectoAuthError(NectoError):
    """Authentication failed or the session expired."""


class NectoRedirectError(NectoError):
    """Unexpected redirect, represented solely by an allowlisted category."""

    CATEGORIES = frozenset({"other_origin", "same_host_http", "root", "devices_trailing_slash",
                            "login_trailing_slash", "dashboard", "home", "verify_email", "other_path"})

    def __init__(self, category):
        super().__init__("Necto returned an unexpected login redirect")
        self.category = category if category in self.CATEGORIES else "other_path"


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.page = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if data.get("id") == "app" and "data-page" in data:
            self.page = data["data-page"]


class NectoClient:
    """Use a caller-owned async session and its isolated cookie jar."""

    def __init__(self, session, email=None, password=None):
        self._session = session
        self._version = None
        self._email = email
        self._password = password

    async def close(self):
        """Release the integration-owned session and its cookie jar."""
        await self._session.close()

    async def login(self, email, password):
        """Provisional login; initial CSRF issuance still needs live verification."""
        async with self._session.get(BASE + "/login", allow_redirects=False) as response:
            if response.status != 200:
                raise NectoError("Unable to load the login page")
            parser = _PageParser()
            parser.feed(await response.text())
        try:
            page = json.loads(parser.page)
            if page["component"] != "Auth/Login" or not isinstance(page["version"], str):
                raise ValueError
            self._version = page["version"]
            cookie = self._session.cookie_jar.filter_cookies(BASE)["XSRF-TOKEN"].value
        except (KeyError, TypeError, ValueError):
            raise NectoError("Login page did not provide expected CSRF or application data") from None
        headers = {"Accept": "text/html, application/xhtml+xml",
                   "X-Inertia": "true", "X-Inertia-Version": self._version,
                   "X-XSRF-TOKEN": unquote(cookie), "Referer": BASE + "/login"}
        async with self._session.post(BASE + "/login", headers=headers,
                                      json={"email": email, "password": password, "remember": False},
                                      allow_redirects=False) as response:
            location = urlsplit(urljoin(BASE + "/login", response.headers.get("Location", "")))
            if response.status in (401, 403, 422):
                raise NectoAuthError("Necto rejected the login")
            if response.status != 302:
                raise NectoError("Necto returned an unexpected login response")
            if location.scheme != "https" or location.netloc != "app.getnecto.com":
                category = "same_host_http" if location.scheme == "http" and location.netloc == "app.getnecto.com" else "other_origin"
                raise NectoRedirectError(category)
            if location.path == "/login":
                raise NectoAuthError("Necto rejected the login")
            if location.path != "/devices":
                category = {"/": "root", "/devices/": "devices_trailing_slash", "/login/": "login_trailing_slash",
                            "/dashboard": "dashboard", "/home": "home", "/email/verify": "verify_email"}.get(location.path, "other_path")
                raise NectoRedirectError(category)

    async def get_device_page(self, page_number):
        """Get stored readings, without invoking the device refresh control."""
        try:
            return await self._get_device_page(page_number)
        except NectoAuthError:
            if self._email is None or self._password is None:
                raise
            await self.login(self._email, self._password)
            return await self._get_device_page(page_number)

    async def _get_device_page(self, page_number):
        if type(page_number) is not int or not 1 <= page_number <= 100:
            raise ValueError("Invalid page number")
        headers = {"Accept": "text/html, application/xhtml+xml", "X-Inertia": "true"}
        if self._version:
            headers["X-Inertia-Version"] = self._version
        async with self._session.get(BASE + "/devices", params={"page": page_number},
                                     headers=headers, allow_redirects=False) as response:
            if response.status in (301, 302, 303, 401, 403, 419):
                raise NectoAuthError("Necto session expired or was rejected")
            if response.status != 200:
                raise NectoError("Unable to retrieve Necto devices")
            try:
                body = await response.json()
            except (TypeError, ValueError):
                raise NectoError("Necto returned an unexpected response") from None
            if not isinstance(body, dict) or body.get("component") == "Auth/Login":
                raise NectoAuthError("Necto did not return an authenticated device page")
            return body
