"""A book's own files are never served as pages of the site."""

import zipfile
from io import BytesIO

from tests.factories.epub import build_epub
from tests.integration.util import create_library, upload_epub


async def test_a_chapter_is_not_served_as_a_page(admin_client):
    library_id = await create_library(admin_client)
    book = await upload_epub(admin_client, library_id)

    response = await admin_client.get(
        f"/api/books/{book['id']}/content/OEBPS/chapter1.xhtml"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"

    # Kept on the answer to a revalidation too.
    response = await admin_client.get(
        f"/api/books/{book['id']}/content/OEBPS/chapter1.xhtml",
        headers={"If-None-Match": response.headers["etag"]},
    )
    assert response.status_code == 304
    assert response.headers["content-security-policy"] == "sandbox"


async def test_a_chapter_named_html_is_not_served_as_a_page(admin_client):
    """An older book names its chapters .html: a type a browser opens."""
    library_id = await create_library(admin_client)
    source = BytesIO(build_epub())
    renamed = BytesIO()
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(renamed, "w") as out:
        for item in src.infolist():
            data = src.read(item.filename)
            name = item.filename
            if name.endswith(".opf"):
                data = data.replace(b"chapter1.xhtml", b"chapter1.html")
            if name.endswith("chapter1.xhtml"):
                name = name.replace(".xhtml", ".html")
            out.writestr(
                zipfile.ZipInfo(name, date_time=item.date_time),
                data,
                compress_type=item.compress_type,
            )
    response = await admin_client.post(
        "/api/books",
        files={"file": ("book.epub", renamed.getvalue(), "application/epub+zip")},
        data={"library_id": library_id},
    )
    assert response.status_code == 201, response.text

    response = await admin_client.get(
        f"/api/books/{response.json()['id']}/content/OEBPS/chapter1.html"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-security-policy"] == "sandbox"
