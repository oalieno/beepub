"""Small helpers shared by the integration test modules."""

from httpx import AsyncClient

from tests.factories.epub import build_epub


async def create_library(client: AsyncClient, name: str = "Main") -> str:
    response = await client.post("/api/libraries", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def upload_epub(client: AsyncClient, library_id: str, **epub_kwargs) -> dict:
    epub = build_epub(**epub_kwargs)
    response = await client.post(
        "/api/books",
        files={"file": ("book.epub", epub, "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text
    return response.json()
