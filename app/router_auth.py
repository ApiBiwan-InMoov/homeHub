from __future__ import annotations

from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import hmac
import hashlib
import uuid

from .config import settings
from .storage.devices import approve_device, is_device_approved

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="app/ui/templates")

AUTH_COOKIE_NAME = "homehub_auth"
DEVICE_COOKIE_NAME = "homehub_device_id"

def get_auth_token(password: str) -> str:
    # Simple stable token based on password. 
    # In a real app we'd use a random secret, but here we want something simple.
    return hashlib.sha256(password.encode()).hexdigest()

def is_authenticated(request: Request) -> bool:
    if not settings.app_password:
        return True
    
    expected_token = get_auth_token(settings.app_password)
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    
    if cookie_token != expected_token:
        return False
        
    # Check device approval
    device_id = request.cookies.get(DEVICE_COOKIE_NAME)
    return is_device_approved(device_id)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == settings.app_password:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=AUTH_COOKIE_NAME, 
            value=get_auth_token(password),
            httponly=True,
            samesite="lax",
            max_age=365 * 24 * 60 * 60 # 1 year
        )
        
        # Ensure device_id exists
        device_id = request.cookies.get(DEVICE_COOKIE_NAME)
        if not device_id:
            device_id = str(uuid.uuid4())
            response.set_cookie(
                key=DEVICE_COOKIE_NAME,
                value=device_id,
                httponly=True,
                samesite="lax",
                max_age=365 * 24 * 60 * 60
            )
        
        return response
    
    return RedirectResponse(url="/login?error=Invalid+password", status_code=303)

@router.get("/verify-device", response_class=HTMLResponse)
async def verify_device_page(request: Request, error: str | None = None):
    return templates.TemplateResponse("verify_device.html", {"request": request, "error": error})

@router.post("/verify-device")
async def verify_device(request: Request, code: str = Form(...)):
    if code == settings.device_verification_code:
        device_id = request.cookies.get(DEVICE_COOKIE_NAME)
        if not device_id:
            device_id = str(uuid.uuid4())
        
        approve_device(device_id, user_agent=request.headers.get("User-Agent", "Unknown"))
        
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=DEVICE_COOKIE_NAME,
            value=device_id,
            httponly=True,
            samesite="lax",
            max_age=365 * 24 * 60 * 60
        )
        return response
    
    return RedirectResponse(url="/verify-device?error=Code+invalide", status_code=303)

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response
