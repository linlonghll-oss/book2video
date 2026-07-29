from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from app.db import engine, Base
from app.models.folder import Folder
from app.models.note import Note
from app.models.script import Script
from app.models.material import Material
from app.models.video_output import VideoOutput
from app.models.model_config import ModelConfig
from app.routers import folders, notes, workflow, config
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.join(STORAGE_DIR, "cards"), exist_ok=True)
    os.makedirs(os.path.join(STORAGE_DIR, "images"), exist_ok=True)
    os.makedirs(os.path.join(STORAGE_DIR, "videos"), exist_ok=True)
    os.makedirs(os.path.join(STORAGE_DIR, "slides"), exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="book2video", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(folders.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(workflow.router, prefix="/api")
app.include_router(config.router, prefix="/api")

app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")
