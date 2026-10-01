"""Welche Adressen der Updater abrufen darf: nur HTTPS, nur GitHub.

* Releases: ``https://api.github.com/…``
* Downloads: ``https://github.com/<Repository>/releases/download/…`` – GitHub leitet auf den
  Speicher ``https://release-assets.githubusercontent.com/…`` (früher ``objects.…``) weiter.
* Weiterleitungen: höchstens fünf, nur zu einer ebenfalls erlaubten Adresse – nie von HTTPS
  auf HTTP, nie zu einem fremden Server, keine Zugangsdaten in der Adresse.

Tests verwenden ``UrlPolicy.loopback(port)`` für einen lokalen Testserver; die App selbst
verwendet immer ``UrlPolicy.github()``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

MAX_REDIRECTS = 5
GITHUB_HOSTS = frozenset({"api.github.com", "github.com"})
GITHUB_SUFFIXES = (".githubusercontent.com",)


class UrlPolicy:
    """Prüft Adressen vor jedem Abruf und jeder Weiterleitung."""

    def __init__(
        self,
        hosts: frozenset[str] | set[str],
        suffixes: tuple[str, ...] = (),
        schemes: tuple[str, ...] = ("https",),
        ports: frozenset[int | None] | set[int | None] = frozenset({None, 443}),
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        self.hosts = frozenset(host.lower() for host in hosts)
        self.suffixes = tuple(suffix.lower() for suffix in suffixes)
        self.schemes = tuple(scheme.lower() for scheme in schemes)
        self.ports = frozenset(ports)
        self.max_redirects = int(max_redirects)

    @classmethod
    def github(cls) -> "UrlPolicy":
        """Die Regel der App: HTTPS zu GitHub und seinem Download-Speicher."""
        return cls(GITHUB_HOSTS, GITHUB_SUFFIXES)

    @classmethod
    def loopback(cls, port: int) -> "UrlPolicy":
        """Nur für Tests: ``http://127.0.0.1:<port>`` (lokaler Testserver, kein Netzwerk)."""
        return cls(frozenset({"127.0.0.1"}), schemes=("http",), ports=frozenset({int(port)}))

    def allows(self, url: str) -> bool:
        text = str(url or "")
        if not text or len(text) > 4096 or any(char.isspace() or ord(char) < 32 or char == "\\" for char in text):
            return False
        try:
            parts = urlsplit(text)
            port = parts.port
        except ValueError:
            return False
        if parts.scheme.lower() not in self.schemes:
            return False
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            return False
        host = (parts.hostname or "").lower()
        if not host:
            return False
        if host not in self.hosts and not any(host.endswith(suffix) and len(host) > len(suffix) for suffix in self.suffixes):
            return False
        return port in self.ports

    def allows_redirect(self, source: str, target: str) -> bool:
        """Weiterleitung von ``source`` nach ``target`` – nur zu einer erlaubten Adresse."""
        if not self.allows(target):
            return False
        # Nie von HTTPS auf ein unsichereres Protokoll (für die App ohnehin nur HTTPS erlaubt)
        return not (urlsplit(source).scheme.lower() == "https" and urlsplit(target).scheme.lower() != "https")
