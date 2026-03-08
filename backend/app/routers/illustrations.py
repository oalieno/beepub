import os
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.deps import get_current_user, get_current_user_or_cookie
from app.models.illustration import Illustration
from app.models.user import User
from app.routers.books import _get_book_with_access
from app.schemas.illustration import IllustrationCreate, IllustrationOut, StylePromptOut
from app.services.gemini import generate_illustration, get_style_prompts
from app.services.storage import delete_file, get_illustration_path

router = APIRouter(prefix="/api/books", tags=["illustrations"])


@router.get("/{book_id}/illustrations", response_model=list[IllustrationOut])
async def list_illustrations(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(Illustration)
        .where(Illustration.user_id == current_user.id, Illustration.book_id == book_id)
        .order_by(Illustration.created_at.asc())
    )
    return result.scalars().all()


@router.post(
    "/{book_id}/illustrations",
    response_model=IllustrationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_illustration(
    book_id: uuid.UUID,
    body: IllustrationCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    illustration_id = uuid.uuid4()
    image_path = get_illustration_path(illustration_id)

    illustration = Illustration(
        id=illustration_id,
        user_id=current_user.id,
        book_id=book_id,
        cfi_range=body.cfi_range,
        text=body.text,
        style_prompt=body.style_prompt,
        custom_prompt=body.custom_prompt,
        image_path=image_path,
        status="generating",
    )
    db.add(illustration)
    await db.commit()
    await db.refresh(illustration)

    background_tasks.add_task(
        _generate_illustration_task,
        illustration_id,
        body.text,
        body.style_prompt,
        body.custom_prompt,
        image_path,
    )
    return illustration


@router.get("/{book_id}/illustrations/styles", response_model=list[StylePromptOut])
async def list_styles(
    book_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    return get_style_prompts()


@router.get(
    "/{book_id}/illustrations/{illustration_id}", response_model=IllustrationOut
)
async def get_illustration(
    book_id: uuid.UUID,
    illustration_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(Illustration).where(
            Illustration.id == illustration_id,
            Illustration.user_id == current_user.id,
            Illustration.book_id == book_id,
        )
    )
    illustration = result.scalar_one_or_none()
    if not illustration:
        raise HTTPException(status_code=404, detail="Illustration not found")
    return illustration


@router.get("/{book_id}/illustrations/{illustration_id}/image")
async def get_illustration_image(
    book_id: uuid.UUID,
    illustration_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user_or_cookie)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _get_book_with_access(book_id, current_user, db)
    result = await db.execute(
        select(Illustration).where(
            Illustration.id == illustration_id,
            Illustration.user_id == current_user.id,
            Illustration.book_id == book_id,
        )
    )
    illustration = result.scalar_one_or_none()
    if not illustration:
        raise HTTPException(status_code=404, detail="Illustration not found")
    if illustration.status != "completed":
        raise HTTPException(status_code=404, detail="Image not ready")
    if not os.path.exists(illustration.image_path):
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(illustration.image_path, media_type="image/png")


@router.delete(
    "/{book_id}/illustrations/{illustration_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_illustration(
    book_id: uuid.UUID,
    illustration_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Illustration).where(
            Illustration.id == illustration_id,
            Illustration.user_id == current_user.id,
            Illustration.book_id == book_id,
        )
    )
    illustration = result.scalar_one_or_none()
    if not illustration:
        raise HTTPException(status_code=404, detail="Illustration not found")
    delete_file(illustration.image_path)
    await db.delete(illustration)
    await db.commit()


async def _generate_illustration_task(
    illustration_id: uuid.UUID,
    text: str,
    style_prompt: str | None,
    custom_prompt: str | None,
    image_path: str,
) -> None:
    """Background task: call Gemini API, save image, update DB status."""
    async with AsyncSessionLocal() as db:
        try:
            image_bytes = await generate_illustration(text, style_prompt, custom_prompt)
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            with open(image_path, "wb") as f:
                f.write(image_bytes)
            result = await db.execute(
                select(Illustration).where(Illustration.id == illustration_id)
            )
            ill = result.scalar_one()
            ill.status = "completed"
            await db.commit()
        except Exception as e:
            result = await db.execute(
                select(Illustration).where(Illustration.id == illustration_id)
            )
            ill = result.scalar_one()
            ill.status = "failed"
            ill.error_message = str(e)[:500]
            await db.commit()
