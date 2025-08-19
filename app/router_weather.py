from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from .weather.open_meteo import fetch_next_18h

router = APIRouter(prefix="/weather", tags=["weather"])
templates = Jinja2Templates(directory="app/ui/templates")

@router.get("/hourly")
def hourly_json():
    try:
        return fetch_next_18h()
    except Exception as e:
        # Log and return a readable error
        import logging, traceback
        logging.exception("weather fetch failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def weather_page(request: Request):
    return templates.TemplateResponse("weather.html", {"request": request})

