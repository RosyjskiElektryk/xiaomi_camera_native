# Xiaomi Camera Native 0.3.14

## CW500 Dual dual-lens video

- Add isa.camera.500dh as the Xiaomi Outdoor Camera CW500 Dual model.
- Expose separate primary and secondary Home Assistant camera entities while retaining the existing primary entity unique ID.
- Receive both interleaved video streams over one authenticated MISS/CS2 connection and route frames by the measured lens flag.
- Keep independent MPEG-TS muxers and H.264 encoder pipelines for the two lenses.

This release's dual-lens implementation is experimental and requires physical CW500 validation. It does not add SD-card playback, PTZ or audio support.
