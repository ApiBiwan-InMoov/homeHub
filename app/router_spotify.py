from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse

from app.services.spotify import spotify_service, get_spotify_oauth

from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/spotify", tags=["spotify"])
templates = Jinja2Templates(directory="app/ui/templates")
logger = logging.getLogger(__name__)

@router.get("/callback")
@router.get("/auth/callback", include_in_schema=False)
def spotify_callback(request: Request, code: str):
    oauth = get_spotify_oauth(request)
    if not oauth:
        return {"ok": False, "message": "Spotify is not configured"}
    try:
        token_info = oauth.get_access_token(code)
    except Exception as e:
        logger.error("Spotify callback failed to exchange code: %s", e, exc_info=True)
        return {"ok": False, "message": "Failed to authenticate with Spotify"}
    if token_info:
        logger.info("Spotify callback authenticated successfully")
        return RedirectResponse(url="/spotify/ui")
    logger.warning("Spotify callback returned empty token_info")
    return {"ok": False, "message": "Failed to authenticate with Spotify"}

@router.get("/ui", response_class=HTMLResponse)
def spotify_ui(request: Request):
    return templates.TemplateResponse("spotify.html", {"request": request})

@router.get("/login")
def spotify_login(request: Request):
    oauth = get_spotify_oauth(request)
    if not oauth:
        return {"ok": False, "message": "Spotify is not configured. Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env"}
    auth_url = oauth.get_authorize_url()
    return RedirectResponse(auth_url)

@router.get("/status")
def spotify_status():
    if not spotify_service.is_authenticated():
        return {"ok": False, "authenticated": False}
    return {"ok": True, "authenticated": True, "status": spotify_service.get_status()}

@router.get("/health")
def spotify_health():
    return {"ok": True, "health": spotify_service.get_health()}

@router.get("/playlists")
def spotify_playlists():
    if not spotify_service.is_authenticated():
        logger.info("Spotify playlists requested but not authenticated")
        return {"ok": False, "authenticated": False}
    items, error = spotify_service.get_playlists_safe()
    if error:
        logger.warning("Spotify playlists failed: %s", error)
        return {"ok": False, "authenticated": True, "items": [], "message": error}
    return {"ok": True, "items": items}

@router.get("/recommendations")
def spotify_recommendations():
    if not spotify_service.is_authenticated():
        return {"ok": False, "authenticated": False}
    items, error = spotify_service.get_recommendations_safe()
    return {"ok": not error, "items": items, "message": error}

@router.get("/devices")
def spotify_devices():
    if not spotify_service.is_authenticated():
        return {"ok": False, "authenticated": False}
    items, error = spotify_service.get_devices_safe()
    return {"ok": not error, "items": items, "message": error}

@router.get("/token")
def spotify_token():
    if not spotify_service.is_authenticated():
        return {"ok": False, "authenticated": False}
    
    token_info = spotify_service._get_cached_token(spotify_service._get_oauth())
    if not token_info:
        return {"ok": False, "authenticated": False}
        
    return {"ok": True, "access_token": token_info.get("access_token")}

@router.post("/transfer")
def spotify_transfer(payload: dict = Body(...)):
    device_id = payload.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")
    res, msg = spotify_service.transfer_playback_safe(device_id)
    return {"ok": res, "message": msg}

@router.post("/play")
def spotify_play(payload: dict = Body({})):
    query = payload.get("query")
    type = payload.get("type", "track")
    uri = payload.get("uri")
    
    if uri:
        res, msg = spotify_service.play(context_uri=uri if "track" not in uri else None, 
                                     uris=[uri] if "track" in uri else None)
    elif query:
        res, msg = spotify_service.search_and_play(query, type=type)
    else:
        res, msg = spotify_service.resume()
        
    return {"ok": res, "message": msg}

@router.post("/pause")
def spotify_pause():
    res, msg = spotify_service.pause()
    return {"ok": res, "message": msg}

@router.post("/next")
def spotify_next():
    res, msg = spotify_service.next()
    return {"ok": res, "message": msg}

@router.post("/previous")
def spotify_previous():
    res, msg = spotify_service.previous()
    return {"ok": res, "message": msg}
