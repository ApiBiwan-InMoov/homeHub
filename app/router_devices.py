from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .storage.devices import get_all_devices, revoke_device
from .router_auth import DEVICE_COOKIE_NAME

router = APIRouter(prefix="/devices", tags=["devices"])
templates = Jinja2Templates(directory="app/ui/templates")

@router.get("", response_class=HTMLResponse)
async def list_devices(request: Request):
    devices = get_all_devices()
    current_device_id = request.cookies.get(DEVICE_COOKIE_NAME)
    
    # Sort devices by last seen
    devices.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
    
    return templates.TemplateResponse(
        "devices.html", 
        {
            "request": request, 
            "devices": devices,
            "current_device_id": current_device_id
        }
    )

@router.post("/revoke/{device_id}")
async def revoke(request: Request, device_id: str):
    revoke_device(device_id)
    
    current_device_id = request.cookies.get(DEVICE_COOKIE_NAME)
    if device_id == current_device_id:
        # If user revokes current device, log them out
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(DEVICE_COOKIE_NAME)
        return response
        
    return RedirectResponse(url="/devices", status_code=303)
