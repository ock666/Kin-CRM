from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from typing import Optional
import asyncio
import wave

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)


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
        "piper_host": get_setting(db, "tts_piper_host", ""),
        "piper_port": get_setting(db, "tts_piper_port", "10200"),
        "mirror_mode": get_setting(db, "tts_mirror_mode", "1"),
    }


def should_reply_with_voice(db) -> tuple[bool, bool]:
    """Return a tuple (deprecated_reply_default, mirror_mode).
    reply_default is deprecated and always False. mirror_mode controls whether
    the bot replies with voice when the user sends a voice note."""
    cfg = _read_tts_settings(db)
    return (False, cfg.get("mirror_mode") == "1")


def synthesize_from_settings(db, text: str, *, voice: Optional[str] = None, fmt: str = "mp3") -> bytes:
    cfg = _read_tts_settings(db)
    provider = (cfg.get("provider") or "piper").lower()
    fmt = fmt or (cfg.get("format") or "mp3")
    v = voice or (cfg.get("voice") or "en_GB-alba-medium")
    logger.info("TTS synth request: provider=%s voice=%s fmt=%s text_len=%d", provider, v, fmt, len(text))
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
    """Prefer Wyoming TCP (host/port). If not configured, fall back to Piper web UI HTTP
    (only if a synth endpoint exists; some builds don't expose one)."""
    host = (cfg.get("piper_host") or cfg.get("tts_piper_host") or "").strip()
    port = int((cfg.get("piper_port") or cfg.get("tts_piper_port") or 10200))
    if host:
        logger.info("TTS Piper via Wyoming TCP %s:%s voice=%s", host, port, voice)
        return asyncio.run(_synthesize_piper_wyoming(host, port, text, voice, fmt))
    # HTTP fallback (may not exist in wyoming-piper images) - best effort only
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise TTSError("Piper not configured (host/port missing).")
    url = f"{base}/synthesize"
    with httpx.Client(timeout=60.0) as client:
        r = client.post(url, json={"text": text, "voice": voice})
        if r.status_code != 200:
            raise TTSError(f"Piper HTTP synth error {r.status_code}")
        wav = r.content
    return _maybe_to_mp3(wav, fmt)


async def _synthesize_piper_wyoming(host: str, port: int, text: str, voice: str, fmt: str) -> bytes:
    try:
        # wyoming client API (async)
        from wyoming.client import AsyncTcpClient
        from wyoming.tts import Synthesize, SynthesizeVoice
        from wyoming.audio import AudioChunk, AudioStart, AudioStop
    except Exception as e:
        raise TTSError("Wyoming client not available. Ensure 'wyoming' is installed.") from e

    chunks: list[bytes] = []
    sample_rate = 22050
    channels = 1
    sample_width = 2  # 16-bit
    async with AsyncTcpClient(host, port) as client:
        await client.write_event(Synthesize(text=text, voice=SynthesizeVoice(name=voice)).event())
        while True:
            event = await client.read_event()
            if event is None:
                break
            if AudioStart.is_type(event.type):
                # Wyoming sends the PCM format on AudioStart (rate/width/channels).
                data = event.data or {}
                sample_rate = int(data.get("rate", sample_rate))
                sample_width = int(data.get("width", sample_width))
                channels = int(data.get("channels", channels))
            elif AudioChunk.is_type(event.type):
                # Audio samples arrive in event.payload (not event.data).
                payload = event.payload
                if payload:
                    chunks.append(bytes(payload))
            elif AudioStop.is_type(event.type):
                break

    if not chunks:
        raise TTSError("No audio returned from Piper.")
    raw = b"".join(chunks)
    # Wrap PCM s16le frames in a WAV container so ffmpeg can transcode reliably.
    wav_bytes = _pcm_to_wav(raw, sample_rate=sample_rate, channels=channels, sample_width=sample_width)
    return _maybe_to_mp3(wav_bytes, fmt)


def _pcm_to_wav(pcm: bytes, *, sample_rate: int, channels: int, sample_width: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _maybe_to_mp3(wav_bytes: bytes, fmt: str) -> bytes:
    if (fmt or "mp3").lower() == "mp3":
        return _wav_to_mp3(wav_bytes)
    return wav_bytes


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
