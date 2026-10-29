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


class _VersionChanged(NectoError):
    """The Inertia application version changed."""


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


def release_session(session):
    """Clear the private cookies and detach from HA's shared connector."""
    try:
        session.cookie_jar.clear()
    finally:
        session.detach()


class NectoClient:
    """Use a caller-owned async session and its isolated cookie jar."""

    def __init__(self, session, email=None, password=None):
        self._session = session
        self._version = None
        self._email = email
        self._password = password

    async def close(self):
        """Release the integration's private session and its cookie jar."""
        release_session(self._session)

    async def login(self, email, password):
        """Provisional login; initial CSRF issuance still needs live verification."""
        verify_session = False
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
                verify_session = True
        if verify_session:
            await self._verify_login_session()

    async def _verify_login_session(self):
        """Verify an unfamiliar same-origin redirect without following it."""
        from .model import parse_devices

        try:
            try:
                page = await self._get_device_page(1)
            except _VersionChanged:
                await self._refresh_version()
                page = await self._get_device_page(1)
            meta = page["props"]["devices"]["meta"]
            current, last = meta["current_page"], meta["last_page"]
            if type(current) is not int or type(last) is not int or current != 1 or not 1 <= last <= 100:
                raise ValueError
            parse_devices(page)
        except (NectoError, KeyError, TypeError, ValueError, AttributeError):
            raise NectoError("Necto login session could not be verified") from None

    async def get_device_page(self, page_number):
        """Get stored readings, without invoking the device refresh control."""
        authenticated = version_refreshed = False
        while True:
            try:
                return await self._get_device_page(page_number)
            except _VersionChanged:
                if version_refreshed:
                    raise NectoError("Necto application version changed repeatedly") from None
                version_refreshed = True
                try:
                    await self._refresh_version()
                except NectoAuthError:
                    if authenticated or self._email is None or self._password is None:
                        raise
                    authenticated = True
                    await self.login(self._email, self._password)
            except NectoAuthError:
                if authenticated or self._email is None or self._password is None:
                    raise
                authenticated = True
                await self.login(self._email, self._password)

    async def _refresh_version(self):
        """Read the same device page as HTML, without following redirects."""
        async with self._session.get(BASE + "/devices", allow_redirects=False) as response:
            if response.status in (301, 302, 303, 401, 403, 419):
                raise NectoAuthError("Necto session expired or was rejected")
            if response.status != 200:
                raise NectoError("Unable to reload Necto application data")
            parser = _PageParser()
            parser.feed(await response.text())
        try:
            page = json.loads(parser.page)
            if (page["component"] == "Auth/Login" or not isinstance(page["component"], str)
                    or not isinstance(page["props"]["devices"]["data"], list)
                    or not isinstance(page["version"], str) or not page["version"]):
                raise ValueError
            self._version = page["version"]
        except (KeyError, TypeError, ValueError):
            raise NectoError("Necto returned unexpected application data") from None

    async def _get_device_page(self, page_number):
        if type(page_number) is not int or not 1 <= page_number <= 100:
            raise ValueError("Invalid page number")
        headers = {"Accept": "text/html, application/xhtml+xml", "X-Inertia": "true"}
        if self._version:
            headers["X-Inertia-Version"] = self._version
        async with self._session.get(BASE + "/devices", params={"page": page_number},
                                     headers=headers, allow_redirects=False) as response:
            if response.status == 409:
                location = response.headers.get("X-Inertia-Location", "")
                parsed = urlsplit(urljoin(BASE + "/devices", location))
                if not location or parsed.scheme != "https" or parsed.netloc != "app.getnecto.com" or parsed.path != "/devices" or parsed.fragment:
                    raise NectoError("Necto returned an unexpected application redirect")
                raise _VersionChanged
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
