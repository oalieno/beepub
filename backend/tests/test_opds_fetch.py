"""The OPDS fetch rules: origin, redirects, credentials, private hosts, size."""

import httpx
import pytest

from app.services.opds_fetch import Credentials, OpdsFetcher, OpdsFetchError

CATALOG = "https://books.example.org/opds"


def _fetcher(handler, creds=None, block_private=False) -> OpdsFetcher:
    return OpdsFetcher(
        CATALOG, creds, block_private, transport=httpx.MockTransport(handler)
    )


async def test_refuses_urls_outside_the_catalog_origin():
    fetcher = _fetcher(lambda r: httpx.Response(200, text="x"))
    with pytest.raises(OpdsFetchError) as err:
        await fetcher.fetch("https://elsewhere.example.org/feed", 1000)
    assert err.value.kind == "blocked"
    with pytest.raises(OpdsFetchError):
        await fetcher.fetch("http://books.example.org/opds", 1000)  # other scheme


async def test_follows_redirects_and_reports_the_final_url():
    def handler(request):
        if request.url.path == "/opds":
            return httpx.Response(302, headers={"location": "/opds/root.xml"})
        return httpx.Response(200, text="<feed/>")

    result = await _fetcher(handler).fetch(CATALOG, 1000)
    assert result.url == "https://books.example.org/opds/root.xml"
    assert result.body == b"<feed/>"


async def test_credentials_stay_on_the_catalog_origin():
    seen: dict[str, str | None] = {}

    def handler(request):
        seen[request.url.host] = request.headers.get("authorization")
        if request.url.host == "books.example.org":
            return httpx.Response(
                302, headers={"location": "https://cdn.example.net/f.epub"}
            )
        return httpx.Response(200, content=b"PK")

    await _fetcher(handler, Credentials("reader", "pw")).fetch(
        CATALOG + "/download/1", 1000
    )
    assert seen["books.example.org"].startswith("Basic ")
    assert seen["cdn.example.net"] is None


async def test_upstream_401_is_an_auth_error():
    with pytest.raises(OpdsFetchError) as err:
        await _fetcher(lambda r: httpx.Response(401)).fetch(CATALOG, 1000)
    assert err.value.kind == "auth"


async def test_bodies_are_capped():
    with pytest.raises(OpdsFetchError) as err:
        await _fetcher(lambda r: httpx.Response(200, content=b"x" * 2000)).fetch(
            CATALOG, 1000
        )
    assert err.value.kind == "too_large"


async def test_private_addresses_are_refused_only_when_blocking():
    def handler(request):
        return httpx.Response(200, text="ok")

    local = "http://127.0.0.1:8080/opds"
    allowed = OpdsFetcher(local, None, False, transport=httpx.MockTransport(handler))
    assert (await allowed.fetch(local, 100)).body == b"ok"

    blocked = OpdsFetcher(local, None, True, transport=httpx.MockTransport(handler))
    with pytest.raises(OpdsFetchError) as err:
        await blocked.fetch(local, 100)
    assert err.value.kind == "blocked"


async def test_a_redirect_into_the_private_network_is_refused_when_blocking(
    monkeypatch,
):
    async def fake_getaddrinfo(host, *_args, **_kwargs):
        ip = "10.0.0.5" if host == "internal.example.net" else "93.184.216.34"
        return [(None, None, None, None, (ip, 0))]

    import asyncio

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    def handler(request):
        return httpx.Response(
            302, headers={"location": "http://internal.example.net/admin"}
        )

    with pytest.raises(OpdsFetchError) as err:
        await _fetcher(handler, block_private=True).fetch(CATALOG, 100)
    assert err.value.kind == "blocked"


async def test_download_leaves_nothing_behind_when_too_large(tmp_path):
    dest = tmp_path / "book.bin"
    fetcher = _fetcher(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(OpdsFetchError):
        await fetcher.download(CATALOG + "/f", str(dest), 1000)
    assert not dest.exists()
