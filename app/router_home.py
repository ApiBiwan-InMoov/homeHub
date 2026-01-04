# app/router_home.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .storage.dashboard import load_layout, save_layout

router = APIRouter(tags=["home"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/", response_class=HTMLResponse)
def home_ui(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@router.get("/dashboard/layout")
def get_layout():
    return {"items": load_layout()}


@router.post("/dashboard/layout")
def set_layout(payload: dict[str, Any] = Body(...)):
    items = payload.get("items") or []
    if not isinstance(items, list):
        items = []
    save_layout(items)
    return {"ok": True, "items": load_layout()}
