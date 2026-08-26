from __future__ import annotations

import io
import subprocess
import tempfile
from typing import Optional

import httpx
from openai import OpenAI


class TTSError(Exception):
    pass


def _read_tts_settings(db):
    from ..settings_store import get_setting, get_setting_sensitive
    return {
        "provider": get_setting(db, "tts_provider", "piper"),
        "base_url": get_setting(db, "tts_base_url", ""),
        "api_key": get_setting_sensitive(db, "tts_api_key"),
        "voice": get_setting(db, "tts_voice", "en_GB-alba-medium"),
        "lang": get_setting(db, "tts_lang", "en-GB"),
        "format": get_setting(db, "tts_format", "mp3"),
        "reply_default": get_setting(db, "tts_reply_default", "1"),
        "mirror_mode": get_setting(db, "tts_mirror_mode", "1"),
    }


def should_reply_with_voice(db) -> tuple[bool, bool]:
    cfg = _read_tts_settings(db)
    return (cfg.get("reply_default") == "1", cfg.get("mirror_mode") == "1")


def synthesize_from_settings(db, text: str, *, voice: Optional[str] = None, fmt: str = "mp3") -> bytes:
    cfg = _read_tts_settings(db)
    provider = (cfg.get("provider") or "piper").lower()
    fmt = fmt or (cfg.get("format") or "mp3")
    v = voice or (cfg.get("voice") or "en_GB-alba-medium")
    if provider == "openai":
        return _synthesize_openai(cfg, text, v, fmt)
    return _synthesize_piper(cfg, text, v, fmt)


def _synthesize_openai(cfg: dict, text: str, voice: str, fmt: str) -> bytes:
    base = cfg.get("base_url") or "https://api.openai.com/v1"
    key = cfg.get("api_key") or ""
    if not key:
        raise TTSError("OpenAI TTS requires an API key.")
    client = OpenAI(base_url=base, api_key=key)
    # OpenAI TTS returns bytes; model tts-1
    resp = client.audio.speech.create(model="tts-1", voice=voice or "alloy", input=text, response_format=fmt)
    # SDK may return a stream-like object with .read(); use .to_bytes() if present
    data = getattr(resp, "to_bytes", None)
    if callable(data):
        return data()
    # Fallback
    b = getattr(resp, "content", None)
    if isinstance(b, (bytes, bytearray)):
        return bytes(b)
    raise TTSError("Unexpected OpenAI TTS response")


def _synthesize_piper(cfg: dict, text: str, voice: str, fmt: str) -> bytes:
    """Call a Piper HTTP server and transcode WAV->mp3 if needed.
    Expected endpoint: POST {base_url}/synthesize with json {"text":..., "voice":...}
    Response: audio/wav (PCM 16-bit). If your server differs, adjust base URL/params.
    """
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise TTSError("Piper base URL not set.")
    url = f"{base}/synthesize"
    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json={"text": text, "voice": voice})
        if r.status_code != 200:
            raise TTSError(f"Piper error {r.status_code}")
        wav = r.content
    if (fmt or "mp3").lower() == "mp3":
        return _wav_to_mp3(wav)
    return wav


def _wav_to_mp3(wav_bytes: bytes) -> bytes:
    # Requires ffmpeg in container
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as w, \
         tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as m:
        w.write(wav_bytes)
        w.flush()
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", w.name,
            "-codec:a", "libmp3lame",
            m.name,
        ]
        subprocess.run(cmd, check=True)
        return m.read()
