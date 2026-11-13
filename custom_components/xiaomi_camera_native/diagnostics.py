"""Useful diagnostics with no account credentials or media endpoint tokens."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import VERSION


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    runtime = entry.runtime_data
    return {
        "version": VERSION,
        "region": entry.data["region"],
        "cameras": [
            {
                "model": session.device.model,
                "lens": {0: "primary", 1: "secondary"}.get(getattr(session, "lens", None), "single"),
                "status": session.status,
                "transport": session.protocol,
                "source_codec": session.codec,
                "video_mode": session.options.video_mode,
                "max_h264_height": session.options.height,
                "quality": session.options.quality,
                "frames": session.frames,
                "reconnects": session.reconnects,
                "encoder_restarts": session.encoder_restarts,
                "encoder_dropped_frames": session.encoder_dropped_frames,
                "last_error": session.last_error,
                "pan_tilt_supported": session.supports_pan_tilt,
                "pan_tilt_experimental": session.pan_tilt_experimental,
                "last_ptz_error": session.last_ptz_error,
                "ip_address": session.host,
                "auto_update_ip": session.options.auto_update_ip,
                "address_source": session.address_source,
                "address_updates": session.address_updates,
            }
            for session in runtime.sessions.values()
        ],
    }
