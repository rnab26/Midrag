from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password, login_user, logout_user, verify_password
from app.database import get_db
from app.models import User
from app.templating import templates

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Email ou mot de passe incorrect."}, status_code=401
        )
    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/register")
def register(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email = email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "register.html", {"request": request, "error": "Ce compte existe déjà."}, status_code=400
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Le mot de passe doit faire au moins 8 caractères."},
            status_code=400,
        )
    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/auth/login", status_code=303)
