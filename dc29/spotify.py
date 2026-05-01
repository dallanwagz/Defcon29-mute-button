"""
dc29.spotify — Spotify Web API client for reactive LED scenes.

This module is the foundation for :mod:`dc29.bridges.spotify_reactive`.  It
handles:

* **Authorization Code with PKCE** OAuth flow (no client-secret needed —
  works for desktop apps).  The user provides a client ID for their own
  Spotify dev app; we never need a secret.
* **Token storage** at ``~/.dc29_spotify_token`` (JSON, mode 0600).
* **Currently-playing** polling.
* **Audio analysis** fetch for arbitrary track IDs, with a permanent
  on-disk cache (Spotify's analysis is deterministic per track —
  caching forever is correct).

Why PKCE
--------

The classic Authorization Code flow requires a client secret which can't
ship safely in a desktop app.  PKCE (RFC 7636) replaces the secret with a
per-flow code-verifier / code-challenge pair, so we can authenticate as a
public client.  Spotify supports it.  The user only has to:

1. Register a free Spotify dev app at https://developer.spotify.com/dashboard
2. Add ``http://localhost:8754/callback`` (the default) as a redirect URI.
3. Paste the client ID into ``~/.config/dc29/config.toml``::

       [spotify]
       client_id = "..."
       redirect_uri = "http://localhost:8754/callback"  # optional override

4. Run ``dc29 spotify auth`` → consent in browser → done forever.

Tokens auto-refresh; the user shouldn't need to re-auth unless they revoke
access in their Spotify account settings.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

TOKEN_PATH: Path = Path.home() / ".dc29_spotify_token"
ANALYSIS_CACHE_DIR: Path = Path.home() / ".cache" / "dc29" / "spotify-analysis"

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8754/callback"
"""Default OAuth redirect URI.

Spotify treats raw IP loopback (``127.0.0.1``) as inherently secure and
allows it without HTTPS.  ``localhost`` triggers their "not secure" warning
since they tightened the rules — the URI itself works either way, but
the dashboard form blocks ``localhost`` saves on some accounts."""
SCOPES = "user-read-currently-playing user-read-playback-state"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


# ---------------------------------------------------------------------------
# Token store
# ---------------------------------------------------------------------------


@dataclass
class TokenSet:
    """Current OAuth tokens.  Persisted as JSON at :data:`TOKEN_PATH`."""

    access_token: str
    refresh_token: str
    expires_at: float                 # epoch seconds
    scope: str = ""

    @classmethod
    def load(cls) -> Optional["TokenSet"]:
        if not TOKEN_PATH.exists():
            return None
        try:
            data = json.loads(TOKEN_PATH.read_text())
            return cls(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=float(data["expires_at"]),
                scope=data.get("scope", ""),
            )
        except (KeyError, ValueError, OSError):
            log.exception("spotify: failed to load token from %s", TOKEN_PATH)
            return None

    def save(self) -> None:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }))
        # Mode 0600 — only the owner can read tokens.
        try:
            os.chmod(TOKEN_PATH, 0o600)
        except OSError:
            pass

    def expired(self, leeway_s: float = 30.0) -> bool:
        return time.time() + leeway_s >= self.expires_at


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` per RFC 7636 §4."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# OAuth flow — runs a tiny local HTTP server to catch the redirect
# ---------------------------------------------------------------------------


class _CallbackHandler(BaseHTTPRequestHandler):
    """Captures the ``?code=...`` from Spotify's redirect."""

    captured: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802 — required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if "code" in params:
            self.captured.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<!doctype html><meta charset=utf-8><title>dc29 Spotify auth</title>"
                b"<body style=\"font-family:system-ui;padding:2em;text-align:center\">"
                b"<h1>Connected.</h1><p>You can close this tab now.</p></body>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing code parameter")

    def log_message(self, format: str, *args: Any) -> None:  # silence the default access log
        return


def authenticate(client_id: str, redirect_uri: str = DEFAULT_REDIRECT_URI) -> TokenSet:
    """Run the full PKCE flow: open browser, capture code, exchange for tokens.

    Blocks until the user consents (or aborts).  Saves the resulting
    :class:`TokenSet` to :data:`TOKEN_PATH` and returns it.
    """
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError(
            f"redirect_uri must be on localhost (got {redirect_uri!r}).  "
            "Add http://localhost:8754/callback to your Spotify app's "
            "Redirect URIs and use that here."
        )
    port = parsed.port or 8754

    auth_url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    })

    server = HTTPServer((parsed.hostname or "localhost", port), _CallbackHandler)
    server.timeout = 0.5
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    log.info("Opening browser for Spotify auth…")
    print(f"\nIf the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    deadline = time.time() + 300  # 5 minutes
    try:
        while "code" not in _CallbackHandler.captured:
            if time.time() > deadline:
                raise TimeoutError("Spotify auth timed out after 5 minutes.")
            time.sleep(0.2)
    finally:
        server.shutdown()

    captured = dict(_CallbackHandler.captured)
    _CallbackHandler.captured.clear()

    if captured.get("state") != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF; aborting.")

    code = captured["code"]
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read())

    tokens = TokenSet(
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=time.time() + int(token_data.get("expires_in", 3600)),
        scope=token_data.get("scope", SCOPES),
    )
    tokens.save()
    log.info("✓ Spotify token saved to %s", TOKEN_PATH)
    return tokens


def refresh_tokens(tokens: TokenSet, client_id: str) -> TokenSet:
    """Exchange a refresh token for a new access token; persists + returns."""
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": tokens.refresh_token,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    new = TokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", tokens.refresh_token),
        expires_at=time.time() + int(data.get("expires_in", 3600)),
        scope=data.get("scope", tokens.scope),
    )
    new.save()
    return new


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


@dataclass
class Beat:
    start: float
    duration: float
    confidence: float


@dataclass
class Bar:
    start: float
    duration: float
    confidence: float


@dataclass
class Section:
    start: float
    duration: float
    confidence: float
    loudness: float
    tempo: float
    key: int
    mode: int
    time_signature: int


@dataclass
class Segment:
    start: float
    duration: float
    confidence: float
    loudness_start: float
    loudness_max: float
    pitches: list[float]   # 12 floats, 0..1, chromagram
    timbre: list[float]    # 12 timbre coefficients


@dataclass
class AudioAnalysis:
    """Parsed subset of Spotify's /audio-analysis response.

    Times are in **seconds** (Spotify's native unit).
    """

    track_id: str
    duration: float
    tempo: float
    key: int
    mode: int
    time_signature: int
    beats: list[Beat] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)


@dataclass
class CurrentlyPlaying:
    """Subset of /me/player/currently-playing."""

    is_playing: bool
    track_id: Optional[str]
    track_name: str
    artist: str
    progress_ms: int
    duration_ms: int
    fetched_at: float = field(default_factory=time.time)

    def estimate_position_ms(self) -> int:
        """Estimate current position by adding wall-clock elapsed since fetch."""
        if not self.is_playing:
            return self.progress_ms
        elapsed = (time.time() - self.fetched_at) * 1000
        return min(int(self.progress_ms + elapsed), self.duration_ms)


class SpotifyClient:
    """Thin Spotify Web API client geared for live LED reactivity.

    Usage::

        client = SpotifyClient(client_id="...")
        client.ensure_authenticated()
        playing = client.currently_playing()
        if playing and playing.track_id:
            analysis = client.audio_analysis(playing.track_id)

    All methods are synchronous and use ``urllib`` — no aiohttp dependency.
    Wrap calls in ``loop.run_in_executor`` from async code if you don't want
    to block the event loop on network IO.
    """

    def __init__(self, client_id: str, redirect_uri: str = DEFAULT_REDIRECT_URI) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self._tokens: Optional[TokenSet] = TokenSet.load()

    # ---- auth helpers ---------------------------------------------------

    @property
    def has_tokens(self) -> bool:
        return self._tokens is not None

    def ensure_authenticated(self) -> TokenSet:
        if self._tokens is None:
            raise RuntimeError(
                "No Spotify tokens stored — run `dc29 spotify auth` first."
            )
        if self._tokens.expired():
            self._tokens = refresh_tokens(self._tokens, self.client_id)
        return self._tokens

    # ---- HTTP plumbing --------------------------------------------------

    def _api_get(self, path: str) -> Optional[dict]:
        tokens = self.ensure_authenticated()
        req = urllib.request.Request(
            API_BASE + path,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 204:  # No Content — happens for /currently-playing when nothing is playing
                    return None
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                # Token may have just expired between checks — refresh and retry once.
                self._tokens = refresh_tokens(tokens, self.client_id)
                req = urllib.request.Request(
                    API_BASE + path,
                    headers={"Authorization": f"Bearer {self._tokens.access_token}"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 204:
                        return None
                    return json.loads(resp.read())
            log.warning("spotify: HTTP %d on %s — %s", exc.code, path, exc.reason)
            return None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            log.warning("spotify: request failed on %s — %s", path, exc)
            return None

    # ---- Public API -----------------------------------------------------

    def currently_playing(self) -> Optional[CurrentlyPlaying]:
        """Return what's playing right now, or ``None`` if nothing is."""
        data = self._api_get("/me/player/currently-playing")
        if not data:
            return None
        item = data.get("item") or {}
        if not item:
            return None
        artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
        return CurrentlyPlaying(
            is_playing=bool(data.get("is_playing", False)),
            track_id=item.get("id"),
            track_name=item.get("name", ""),
            artist=artists,
            progress_ms=int(data.get("progress_ms") or 0),
            duration_ms=int(item.get("duration_ms") or 0),
        )

    def audio_analysis(self, track_id: str) -> Optional[AudioAnalysis]:
        """Fetch (or load from disk cache) the full audio-analysis for *track_id*.

        Cached forever — Spotify's analysis is deterministic per track.
        """
        cache_path = ANALYSIS_CACHE_DIR / f"{track_id}.json"
        if cache_path.exists():
            try:
                raw = json.loads(cache_path.read_text())
                return _parse_analysis(track_id, raw)
            except (ValueError, OSError):
                log.warning("spotify: bad cache for %s — refetching", track_id)
        data = self._api_get(f"/audio-analysis/{track_id}")
        if not data:
            return None
        try:
            ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data))
        except OSError:
            pass
        return _parse_analysis(track_id, data)


def _parse_analysis(track_id: str, raw: dict) -> AudioAnalysis:
    track = raw.get("track", {})
    return AudioAnalysis(
        track_id=track_id,
        duration=float(track.get("duration", 0.0)),
        tempo=float(track.get("tempo", 0.0)),
        key=int(track.get("key", 0)),
        mode=int(track.get("mode", 0)),
        time_signature=int(track.get("time_signature", 4)),
        beats=[
            Beat(float(b.get("start", 0)), float(b.get("duration", 0)), float(b.get("confidence", 0)))
            for b in raw.get("beats", [])
        ],
        bars=[
            Bar(float(b.get("start", 0)), float(b.get("duration", 0)), float(b.get("confidence", 0)))
            for b in raw.get("bars", [])
        ],
        sections=[
            Section(
                start=float(s.get("start", 0)),
                duration=float(s.get("duration", 0)),
                confidence=float(s.get("confidence", 0)),
                loudness=float(s.get("loudness", -60)),
                tempo=float(s.get("tempo", 0)),
                key=int(s.get("key", 0)),
                mode=int(s.get("mode", 0)),
                time_signature=int(s.get("time_signature", 4)),
            )
            for s in raw.get("sections", [])
        ],
        segments=[
            Segment(
                start=float(g.get("start", 0)),
                duration=float(g.get("duration", 0)),
                confidence=float(g.get("confidence", 0)),
                loudness_start=float(g.get("loudness_start", -60)),
                loudness_max=float(g.get("loudness_max", -60)),
                pitches=list(g.get("pitches", [0.0] * 12)),
                timbre=list(g.get("timbre", [0.0] * 12)),
            )
            for g in raw.get("segments", [])
        ],
    )
