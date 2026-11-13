# Xiaomi Camera Native 0.3.15

## Experimental CW500 Dual PTZ

- Add an explicit opt-in for experimental pan/tilt controls on the Xiaomi Outdoor Camera CW500 Dual (`isa.camera.500dh`).
- Expose the four single-step movement buttons only on the motorized primary lens. The fixed secondary lens remains video-only.
- Reuse the shared authenticated MISS connection while video is active; use a short control-only connection when idle.
- Never automatically retry motor commands after a transport error.

CW500 motor movement has not yet been verified on physical hardware. Enable the option only for controlled testing and test one direction at a time. This release does not add continuous movement, presets, calibration or position feedback.
