from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db import get_db
from app.models.folder import Folder
from app.schemas.note import FolderCreate, FolderUpdate, FolderResponse

router = APIRouter(tags=["folders"])


async def _get_folder_depth(db: AsyncSession, parent_id: int | None) -> int:
    if parent_id is None:
        return 0
    depth = 0
    current_id = parent_id
    while current_id is not None:
        result = await db.execute(select(Folder.parent_id).where(Folder.id == current_id))
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        current_id = row[0]
        depth += 1
    return depth


async def _build_tree(db: AsyncSession) -> list[FolderResponse]:
    result = await db.execute(select(Folder).options(selectinload(Folder.children)))
    all_folders = result.unique().scalars().all()
    folder_map = {}
    for f in all_folders:
        folder_map[f.id] = FolderResponse(
            id=f.id,
            name=f.name,
            parent_id=f.parent_id,
            created_at=f.created_at,
            updated_at=f.updated_at,
            children=[],
        )
    roots = []
    for f in all_folders:
        resp = folder_map[f.id]
        if f.parent_id is None:
            roots.append(resp)
        else:
            parent = folder_map.get(f.parent_id)
            if parent:
                parent.children.append(resp)
    return roots


@router.get("/folders", response_model=list[FolderResponse])
async def list_folders(db: AsyncSession = Depends(get_db)):
    return await _build_tree(db)


@router.post("/folders", response_model=FolderResponse, status_code=201)
async def create_folder(body: FolderCreate, db: AsyncSession = Depends(get_db)):
    depth = await _get_folder_depth(db, body.parent_id)
    new_depth = depth + 1
    if new_depth > 5:
        raise HTTPException(status_code=400, detail="Folder depth cannot exceed 5")

    folder = Folder(name=body.name, parent_id=body.parent_id)
    db.add(folder)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        children=[],
    )


@router.patch("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: int, body: FolderUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    folder.name = body.name
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        children=[],
    )


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.delete(folder)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
