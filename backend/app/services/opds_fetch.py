"""Server-side fetches for OPDS catalogs: feeds, images and book files.

The server fetches on the reader's behalf (browsers can't — catalogs
rarely allow CORS), so every request goes through here:

- A request may only start at the catalog's own origin. Any signed-in
  reader can ask for a URL, so the catalog an admin saved is what bounds
  where the server goes — not whatever the client sends.
- Redirects are followed by hand, at most MAX_REDIRECTS. Each hop is
  checked against the private-network setting, and credentials are only
  sent to the catalog's origin (a download bounced to a CDN never sees
  them).
- With opds_block_private_network on, a host that resolves to a private,
  loopback or link-local address is refused.
- Bodies are capped; a book file streams to disk.
"""

import asyncio
import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 5
FEED_MAX_BYTES = 10 * 1024 * 1024
IMAGE_MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "BeePub OPDS"


class OpdsFetchError(Exception):
    """kind: auth (401), http (other 4xx/5xx), network, blocked (origin or
    private address refused), too_large."""

    def __init__(self, kind: str, status: int | None = None):
        super().__init__(f"{kind}{f' {status}' if status else ''}")
        self.kind = kind
        self.status = status


@dataclass
class Credentials:
    username: str
    password: str


def origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme, (parts.hostname or "").lower(), port


def is_http_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _blocked_address(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


async def _check_host(url: str, block_private: bool) -> None:
    if not block_private:
        return
    host = urlsplit(url).hostname or ""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    except OSError:
        raise OpdsFetchError("network")
    if not infos or any(_blocked_address(info[4][0]) for info in infos):
        raise OpdsFetchError("blocked")


@dataclass
class FetchResult:
    url: str  # final, after redirects — relative links resolve against it
    content_type: str
    content_disposition: str | None
    body: bytes = b""


class OpdsFetcher:
    def __init__(
        self,
        catalog_url: str,
        creds: Credentials | None,
        block_private: bool,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._origin = origin(catalog_url)
        self._creds = creds
        self._block_private = block_private
        self._transport = transport

    def in_catalog(self, url: str) -> bool:
        return is_http_url(url) and origin(url) == self._origin

    async def _open(
        self, client: httpx.AsyncClient, url: str, accept: str | None
    ) -> httpx.Response:
        """The final response, streaming, after following redirects."""
        if not self.in_catalog(url):
            raise OpdsFetchError("blocked")
        for _ in range(MAX_REDIRECTS + 1):
            await _check_host(url, self._block_private)
            headers = {"User-Agent": USER_AGENT}
            if accept:
                headers["Accept"] = accept
            auth = None
            if self._creds and origin(url) == self._origin:
                auth = httpx.BasicAuth(self._creds.username, self._creds.password)
            request = client.build_request("GET", url, headers=headers)
            try:
                response = await client.send(request, auth=auth, stream=True)
            except httpx.HTTPError:
                raise OpdsFetchError("network")
            if response.is_redirect:
                location = response.headers.get("location", "")
                await response.aclose()
                url = urljoin(url, location)
                if not is_http_url(url):
                    raise OpdsFetchError("http", response.status_code)
                continue
            if response.status_code == 401:
                await response.aclose()
                raise OpdsFetchError("auth", 401)
            if response.status_code >= 400:
                await response.aclose()
                raise OpdsFetchError("http", response.status_code)
            return response
        raise OpdsFetchError("http", 310)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=False, transport=self._transport
        )

    async def fetch(
        self, url: str, max_bytes: int, accept: str | None = None
    ) -> FetchResult:
        async with self._client() as client:
            response = await self._open(client, url, accept)
            try:
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise OpdsFetchError("too_large")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise OpdsFetchError("too_large")
                    chunks.append(chunk)
            except httpx.HTTPError:
                raise OpdsFetchError("network")
            finally:
                await response.aclose()
            return FetchResult(
                url=str(response.url),
                content_type=response.headers.get("content-type", ""),
                content_disposition=response.headers.get("content-disposition"),
                body=b"".join(chunks),
            )

    async def download(self, url: str, dest: str, max_bytes: int) -> FetchResult:
        """Stream a file to dest. Nothing is left behind on failure."""
        async with self._client() as client:
            response = await self._open(client, url, None)
            size = 0
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise OpdsFetchError("too_large")
                        f.write(chunk)
            except BaseException as exc:
                try:
                    os.remove(dest)
                except FileNotFoundError:
                    pass
                if isinstance(exc, httpx.HTTPError):
                    raise OpdsFetchError("network")
                raise
            finally:
                await response.aclose()
            return FetchResult(
                url=str(response.url),
                content_type=response.headers.get("content-type", ""),
                content_disposition=response.headers.get("content-disposition"),
            )
