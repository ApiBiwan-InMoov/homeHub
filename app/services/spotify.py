from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from app.config import settings

logger = logging.getLogger(__name__)

SCOPE = "user-modify-playback-state user-read-playback-state user-read-currently-playing playlist-read-private playlist-read-collaborative user-top-read streaming"
REQUIRED_SCOPES = set(SCOPE.split())


def _spotify_error_message(error: Exception) -> str:
    if isinstance(error, spotipy.SpotifyException):
        status = getattr(error, "http_status", None)
        msg = getattr(error, "msg", str(error))
        # Handle 404 No Active Device
        if status == 404 or "No active device found" in msg or "NO_ACTIVE_DEVICE" in msg:
            return "No active Spotify device found. Open Spotify on your phone or PC first."
        if status == 403:
            return "Spotify refused playlist access (403). Reconnect and re-approve playlist permissions."
        if status == 401:
            return "Spotify session expired (401). Reconnect Spotify."
        if status:
            return f"Spotify API error ({status}): {msg}"
        return f"Spotify API error: {msg}"
    
    err_str = str(error)
    if "No active device found" in err_str or "NO_ACTIVE_DEVICE" in err_str:
        return "No active Spotify device found. Open Spotify on your phone or PC first."
        
    return err_str

def get_spotify_oauth(request: Any | None = None) -> SpotifyOAuth | None:
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        return None
    
    redirect_uri = settings.spotify_redirect_uri
    if request and redirect_uri.startswith("/"):
        # Build absolute URL from request
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}{redirect_uri}"

    return SpotifyOAuth(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_path=settings.spotify_token_cache_path,
        open_browser=False
    )

class SpotifyService:
    def __init__(self):
        self._sp: spotipy.Spotify | None = None
        self._oauth: SpotifyOAuth | None = None
        self._access_token: str | None = None

    def _log_auth_context(
        self,
        context: str,
        oauth: SpotifyOAuth | None,
        token_info: dict[str, Any] | None,
    ) -> None:
        cache_path = settings.spotify_token_cache_path
        token_keys = sorted(token_info.keys()) if token_info else []
        logger.info(
            "Spotify auth context [%s]: configured=%s cache_path=%s token_present=%s token_keys=%s",
            context,
            bool(settings.spotify_client_id and settings.spotify_client_secret),
            cache_path,
            bool(token_info),
            token_keys,
        )

    def _get_oauth(self, request: Request | None = None) -> SpotifyOAuth | None:
        if self._oauth and not (request and settings.spotify_redirect_uri.startswith("/")):
            return self._oauth
        return get_spotify_oauth(request)

    def _get_cached_token(self, oauth: SpotifyOAuth | None) -> dict[str, Any] | None:
        if not oauth:
            return None
        try:
            return oauth.get_cached_token()
        except Exception as e:
            logger.warning("Spotify token cache read failed: %s", e, exc_info=True)
            return None

    def _refresh_token(self, oauth: SpotifyOAuth, token_info: dict[str, Any]) -> dict[str, Any] | None:
        refresh_token = token_info.get("refresh_token")
        if not refresh_token:
            logger.warning("Spotify token refresh skipped: missing refresh_token")
            return None
        try:
            return oauth.refresh_access_token(refresh_token)
        except Exception as e:
            logger.warning("Spotify token refresh failed: %s", e, exc_info=True)
            return None

    @property
    def sp(self) -> spotipy.Spotify:
        oauth = self._get_oauth()
        if not oauth:
            raise RuntimeError("Spotify not configured. Please set client ID and secret in .env")

        token_info = self._get_cached_token(oauth)
        if not token_info:
            self._log_auth_context("sp_missing_token", oauth, token_info)
            raise RuntimeError("Spotify not authenticated. Please login via web UI.")
        
        # Check if token is expired and refresh it
        if oauth.is_token_expired(token_info):
            token_info = self._refresh_token(oauth, token_info)
            if not token_info:
                self._log_auth_context("sp_refresh_failed", oauth, token_info)
                raise RuntimeError("Spotify session expired. Please login via web UI.")
            
        access_token = token_info["access_token"]
        if self._sp is None or self._access_token != access_token:
            self._sp = spotipy.Spotify(auth=access_token)
            self._access_token = access_token
            
        return self._sp

    def is_authenticated(self) -> bool:
        oauth = self._get_oauth()
        if not oauth:
            return False
        token_info = self._get_cached_token(oauth)
        if not token_info:
            self._log_auth_context("is_authenticated_missing_token", oauth, token_info)
            return False
        
        try:
            if oauth.is_token_expired(token_info):
                token_info = self._refresh_token(oauth, token_info)
                if not token_info:
                    self._log_auth_context("is_authenticated_refresh_failed", oauth, token_info)
                    return False
            return True
        except Exception:
            self._log_auth_context("is_authenticated_exception", oauth, token_info)
            return False

    def _get_device_to_activate(self):
        """Helper to find the best device ID to use if none is active."""
        try:
            devices_resp = self.sp.devices()
            devices = devices_resp.get("devices", [])
            active_device = next((d for d in devices if d["is_active"]), None)
            
            if active_device:
                return active_device["id"], True
                
            preferred_name = settings.spotify_speaker_name
            preferred_id = settings.spotify_speaker_device
            
            # 1. Try to find match by name or ID in current devices
            match = next((d for d in devices if d["name"] == preferred_name or d["id"] == preferred_id), None)
            if match:
                return match["id"], False
            
            # 2. If no match but devices exist, use the first one
            if devices:
                return devices[0]["id"], False
                
            # 3. Last resort: use the ID from config even if not in current list
            if preferred_id and preferred_id != 'default':
                return preferred_id, False
                
            return None, False
        except Exception as e:
            logger.error(f"Error finding device to activate: {e}")
            return None, False

    def play(self, context_uri: str | None = None, uris: list[str] | None = None):
        """Play a specific URI (album, playlist, artist) or a list of tracks."""
        try:
            device_id, is_active = self._get_device_to_activate()
            
            # If we found a device but it's not active, try to transfer playback first
            # to "wake it up" before sending the play command.
            if device_id and not is_active:
                logger.info(f"Attempting to activate device {device_id} before playback")
                try:
                    self.sp.transfer_playback(device_id=device_id, force_play=False)
                except Exception as te:
                    logger.warning(f"Failed to transfer playback to {device_id}: {te}")

            self.sp.start_playback(device_id=device_id, context_uri=context_uri, uris=uris)
            return True, None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error(f"Spotify play error: {msg}")
            return False, msg

    def resume(self):
        try:
            device_id, is_active = self._get_device_to_activate()
            
            if device_id and not is_active:
                logger.info(f"Attempting to activate device {device_id} before resume")
                try:
                    self.sp.transfer_playback(device_id=device_id, force_play=False)
                except Exception as te:
                    logger.warning(f"Failed to transfer playback to {device_id}: {te}")

            self.sp.start_playback(device_id=device_id)
            return True, None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error(f"Spotify resume error: {msg}")
            return False, msg

    def pause(self):
        try:
            self.sp.pause_playback()
            return True, None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error(f"Spotify pause error: {msg}")
            return False, msg

    def next(self):
        try:
            self.sp.next_track()
            return True, None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error(f"Spotify next error: {msg}")
            return False, msg

    def previous(self):
        try:
            self.sp.previous_track()
            return True, None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error(f"Spotify previous error: {msg}")
            return False, msg

    def search_and_play(self, query: str, type: str = "track"):
        """Search for a track/album/playlist and play the first result."""
        try:
            device_id, is_active = self._get_device_to_activate()
            
            if device_id and not is_active:
                logger.info(f"Attempting to activate device {device_id} before search_and_play")
                try:
                    self.sp.transfer_playback(device_id=device_id, force_play=False)
                except Exception as te:
                    logger.warning(f"Failed to transfer playback to {device_id}: {te}")

            results = self.sp.search(q=query, limit=1, type=type)
            if type == "track":
                items = results.get("tracks", {}).get("items", [])
                if items:
                    self.sp.start_playback(device_id=device_id, uris=[items[0]["uri"]])
                    return True, None
            elif type == "album":
                items = results.get("albums", {}).get("items", [])
                if items:
                    self.sp.start_playback(device_id=device_id, context_uri=items[0]["uri"])
                    return True, None
            elif type == "playlist":
                items = results.get("playlists", {}).get("items", [])
                if items:
                    self.sp.start_playback(device_id=device_id, context_uri=items[0]["uri"])
                    return True, None
            return False, "No results found"
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error(f"Spotify search_and_play error: {msg}")
            return False, msg

    def get_status(self) -> dict[str, Any]:
        try:
            current = self.sp.current_playback()
            devices_resp = self.sp.devices()
            devices = devices_resp.get("devices", [])
            active_device = next((d for d in devices if d["is_active"]), None)

            if not current:
                return {
                    "is_playing": False,
                    "has_active_device": active_device is not None,
                    "available_devices_count": len(devices)
                }
            
            item = current.get("item")
            image_url = None
            if item and item.get("album") and item["album"].get("images"):
                image_url = item["album"]["images"][0]["url"]
                
            return {
                "is_playing": current.get("is_playing", False),
                "item": item.get("name") if item else None,
                "artist": item.get("artists", [{}])[0].get("name") if item else None,
                "image": image_url,
                "progress_ms": current.get("progress_ms"),
                "duration_ms": item.get("duration_ms") if item else None,
                "device": current.get("device", {}).get("name"),
                "has_active_device": active_device is not None,
                "available_devices_count": len(devices)
            }
        except Exception as e:
            logger.error(f"Spotify get_status error: {e}")
            return {"error": str(e)}

    def get_health(self) -> dict[str, Any]:
        """Return a health report for Spotify integration.
        Includes configuration presence, authentication state, scopes, and API reachability.
        """
        health: dict[str, Any] = {
            "configured": bool(settings.spotify_client_id and settings.spotify_client_secret),
            "authenticated": False,
            "scopes_ok": False,
            "api_ok": False,
            "details": {}
        }
        try:
            oauth = self._get_oauth()
            if not oauth:
                return health
            token_info = self._get_cached_token(oauth)
            if not token_info:
                return health
            # Refresh if needed
            try:
                if oauth.is_token_expired(token_info):
                    token_info = self._refresh_token(oauth, token_info)
                    if not token_info:
                        health["details"]["refresh_error"] = "missing refresh_token"
                        return health
            except Exception as e:
                health["details"]["refresh_error"] = str(e)
                return health
            health["authenticated"] = True
            # Check scopes
            granted_scopes = set((token_info.get("scope") or "").split())
            missing = list(REQUIRED_SCOPES - granted_scopes)
            health["scopes_ok"] = len(missing) == 0
            if missing:
                health["details"]["missing_scopes"] = missing
            # Lightweight API reachability check
            try:
                sp = spotipy.Spotify(auth=token_info['access_token'])
                me = sp.me()
                _ = me.get("id")
                # Also try listing devices quickly (does not fail token-only auth)
                _ = sp.devices()
                health["api_ok"] = True
            except Exception as e:
                health["details"]["api_error"] = str(e)
            return health
        except Exception as e:
            logger.error(f"Spotify get_health error: {e}")
            health["details"]["error"] = str(e)
            return health

    def get_playlists(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            results = self.sp.current_user_playlists(limit=limit)
            return results.get("items", [])
        except Exception as e:
            logger.error(f"Spotify get_playlists error: {e}")
            return []

    def get_playlists_safe(self, limit: int = 20) -> tuple[list[dict[str, Any]], str | None]:
        try:
            return self.get_playlists(limit=limit), None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error("Spotify get_playlists error: %s", msg, exc_info=True)
            oauth = self._get_oauth()
            token_info = self._get_cached_token(oauth)
            self._log_auth_context("get_playlists_error", oauth, token_info)
            return [], msg

    def get_recommendations(self, limit: int = 10) -> list[dict[str, Any]]:
        # Get top tracks to use as seeds for recommendations
        top_tracks = self.sp.current_user_top_tracks(limit=2, time_range="short_term")
        seed_tracks = [t["id"] for t in top_tracks.get("items", [])]
        
        if not seed_tracks:
            # Fallback to some generic genres if no top tracks
            results = self.sp.recommendations(seed_genres=["pop", "rock"], limit=limit)
        else:
            results = self.sp.recommendations(seed_tracks=seed_tracks, limit=limit)
            
        return results.get("tracks", [])

    def get_recommendations_safe(self, limit: int = 10) -> tuple[list[dict[str, Any]], str | None]:
        try:
            return self.get_recommendations(limit=limit), None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error("Spotify get_recommendations error: %s", msg)
            return [], msg

    def get_devices(self) -> list[dict[str, Any]]:
        results = self.sp.devices()
        return results.get("devices", [])

    def get_devices_safe(self) -> tuple[list[dict[str, Any]], str | None]:
        try:
            return self.get_devices(), None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error("Spotify get_devices error: %s", msg)
            return [], msg

    def transfer_playback_safe(self, device_id: str, force_play: bool = True) -> tuple[bool, str | None]:
        try:
            self.sp.transfer_playback(device_id, force_play=force_play)
            return True, None
        except Exception as e:
            msg = _spotify_error_message(e)
            logger.error("Spotify transfer_playback error: %s", msg)
            return False, msg

spotify_service = SpotifyService()
