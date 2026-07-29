from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models.note import Note
from app.schemas.note import NoteCreate, NoteUpdate, NoteResponse

router = APIRouter(tags=["notes"])


@router.get("/notes", response_model=list[NoteResponse])
async def list_notes(folder_id: int | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Note).order_by(Note.updated_at.desc())
    if folder_id is not None:
        stmt = stmt.where(Note.folder_id == folder_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/notes", response_model=NoteResponse, status_code=201)
async def create_note(body: NoteCreate, db: AsyncSession = Depends(get_db)):
    note = Note(
        title=body.title,
        content=body.content,
        raw_text=body.raw_text,
        folder_id=body.folder_id,
        status="draft",
    )
    db.add(note)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(note)
    return note


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, body: NoteUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(note, field, value)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(note)
    return note


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
