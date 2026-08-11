from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import auth_router, faces_router, jobs_router, media_public_router, pages_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="FaceSwap Perso")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(pages_router.router)
app.include_router(auth_router.router)
app.include_router(faces_router.router)
app.include_router(jobs_router.router)
app.include_router(media_public_router.router)
