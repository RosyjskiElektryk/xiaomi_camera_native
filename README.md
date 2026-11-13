<img width="256" height="256" alt="icon" src="https://github.com/user-attachments/assets/c3833052-52e9-4ef4-9595-f7bf21ac5f13" />

# Xiaomi Camera Native

**Direct Xiaomi camera streaming and pan/tilt controls for Home Assistant — without go2rtc.**

Xiaomi Camera Native connects to compatible Xiaomi cameras using a native Python implementation of **MISS over CS2**. Video travels over your local network, and the cameras appear as ordinary Home Assistant camera entities.

> **Experimental integration.** Camera compatibility depends on model and firmware. Three models were verified by the owner's October 2026 live-view recordings and recorder events. On 12 November 2026, an `ip029a` owner separately reported physical movement in all four directions on one camera using v0.3.11. This is model-specific evidence, not verification of every firmware revision. See the [October recordings](docs/PTZ_HARDWARE_VERIFICATION_2026-10-24.md), the [November user report](docs/PTZ_HARDWARE_VERIFICATION_2026-11-12_ip029a.md) and [VALIDATION.md](VALIDATION.md).

## Features

- Direct camera video over CS2/UDP or CS2/TCP.
- Xiaomi account login, region selection, camera discovery and selection.
- Password login with CAPTCHA and email/SMS verification handling, or reuse of an existing Mi Home account credential.
- H.264 compatibility output through Home Assistant's FFmpeg, with configurable maximum resolution.
- Original H.264/H.265 video output without transcoding.
- A normal Home Assistant stream source for live view and snapshots.
- Four single-step controls: **Pan left**, **Pan right**, **Tilt up** and **Tilt down**.
- Movement arrows below the video in the standard camera pop-up, alongside **Download snapshot**.
- One shared video connection and, when required, one encoder per camera.
- Experimental dual-lens video for the Xiaomi Outdoor Camera CW500 Dual, exposed as two camera entities over one physical MISS connection.
- On-demand streaming, idle disconnection, bounded reconnection attempts and credential-safe diagnostics.

No go2rtc process, bridge container, add-on or Xiaomi native SDK is required by this integration.

## Camera compatibility

| Camera | Model | Default camera quality |
| --- | --- | --- |
| Mi 360 Home Security Camera 2K | `chuangmi.camera.029a02` | HD, quality 2 |
| Xiaomi Smart Camera PTZ Version 2K (China) | `chuangmi.camera.ip029a` | HD, quality 2 |
| Xiaomi Smart Camera C200 | `chuangmi.camera.046c04` | HD, quality 3 |
| Xiaomi Smart Camera C301 | `mxiang.camera.c301` | Automatic, quality 0 |
| Xiaomi Outdoor Camera CW500 Dual | `isa.camera.500dh` | HD, quality 3 (both lenses) |

The four established models among those listed have evidence of physical PTZ operation through Xiaomi Camera Native, with different verification sources. CW500 Dual PTZ is separate and remains experimental. The first three were verified through [owner screen recordings on 24 October 2026](docs/PTZ_HARDWARE_VERIFICATION_2026-10-24.md). For `chuangmi.camera.ip029a`, a separate user confirmed on 12 November 2026 that video and all four PTZ directions worked physically on **one camera** with the integration-only v0.3.11 package; streaming was also confirmed on a **second camera**, but its PTZ was not tested. See the [model-specific report](docs/PTZ_HARDWARE_VERIFICATION_2026-11-12_ip029a.md).

**Pan/tilt buttons are enabled by default for the four established models**, including `ip029a`; no experimental opt-in is required. CW500 Dual is not in this verified list. Its primary-lens controls are deliberately hidden until you enable **Enable experimental pan/tilt** in that camera's options. The secondary lens never receives PTZ buttons. The existing encrypted MISS `0x112` step command is sent over the shared video connection when active, or a short control-only connection while idle. Do not assume movement works until tested on your camera. Other modern MISS/CS2 models have no PTZ buttons unless separately validated. **TUTK, Agora, MTP and legacy protocols are not supported.**

## CW500 Dual night-vision and fill-light controls

For `isa.camera.500dh`, the integration exposes one **Night vision mode** selector and one **Fill light** switch on the shared camera device. The selector uses MIoT service 2/property 3 (`night-shot`): Off, IR/on, Auto, Auto full-colour, Always full-colour and Smart full-colour. The fill-light switch uses service 6/property 16 (`hl-filllight-switch`). Selecting Off also disables the fill light; changing to another night-vision mode does not alter the independent fill-light switch. These settings are sent through the authenticated Xiaomi cloud MIoT API, not the local MISS video socket. The MIoT specification lists the properties as writable, but this integration path still needs physical testing on each camera firmware. The fill light may be subject to the camera's own timeout/automation behavior.

## Experimental dual-lens video: CW500 Dual

The Xiaomi Outdoor Camera CW500 Dual (`isa.camera.500dh`) is exposed as two Home Assistant camera entities: the existing primary camera entity and a new secondary-lens entity. Both streams are requested over one authenticated MISS/CS2 connection and separated by the lens flags in the incoming media packets. Each lens has its own video muxer and optional H.264 encoder.

This path is experimental. The dual-stream command and lens flag values have been confirmed on a physical CW500 Dual, and live video from both lenses has been reported working with this fork. Latency and buffering still need investigation. The secondary lens is fixed. Experimental PTZ controls are available only for the primary lens after explicit opt-in in that camera's options; motor movement is not yet hardware-verified. MicroSD playback is not implemented.

## Requirements

- Cameras already paired with your Xiaomi account in Xiaomi Home/Mi Home.
- Home Assistant able to reach the cameras over the local network.
- Internet access for Xiaomi account authentication and fresh camera session keys.
- FFmpeg available to Home Assistant, including the `libx264` encoder for H.264 output.

The documented minimum baseline is **Home Assistant 2025.3.0**. Initial live streaming diagnostics were checked on Home Assistant 2026.10.2; not every Home Assistant version has been tested. The integration loads the standard `camera`, `ffmpeg`, `frontend` and `stream` dependencies automatically.

## Installation

### Installation through HACS (Custom repository)

1. Open **HACS** in Home Assistant.
2. From the three-dot menu, choose **Custom repositories**.
3. Add `https://github.com/RosyjskiElektryk/xiaomi_camera_native` and select **Integration**.
4. Find **Xiaomi Camera Native** in HACS and install it.
5. Restart Home Assistant; then add it from **Settings → Devices & services**.


### Manual installation

1. Download and extract the integration ZIP, or download this repository.
2. Copy the `custom_components/xiaomi_camera_native` directory into your Home Assistant configuration directory.
3. Confirm that the manifest is located at:

   ```text
   /config/custom_components/xiaomi_camera_native/manifest.json
   ```

4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Xiaomi Camera Native**.
7. Sign in, select the same region used in Xiaomi Home/Mi Home, and choose your cameras.
8. Refresh your browser after setup so the camera pop-up controls can load. Use a hard refresh if necessary, or fully close and reopen the Home Assistant Companion app.

No YAML configuration or manual dashboard resource registration is required.

### Remove a camera / Rediscover

Open **Settings → Devices & services → Xiaomi Camera Native → Configure →
Rediscover**, then **deselect** any cameras you no longer want and save.
The integration reloads with the selected cameras and removes the deselected
camera's Home Assistant device record and its camera/PTZ entity records.
Previous camera-specific streaming/PTZ options for removed cameras are also cleared.

The cleanup also runs after a successful integration restart/reload, fixing
empty camera devices left behind by older releases (for example, "Outdoor Garage").
If an orphan remains, open its device page and choose **Delete device**:
v0.3.14 supports deletion of orphaned Xiaomi camera devices. A **currently
selected** camera cannot be deleted that way; deselect it in Rediscover first.
A camera still visible in the Mi Home account may appear in the Rediscover list,
but will not be re-added until explicitly selected.

### Account and region

Choose the region where the cameras are registered:

| Region | Code |
| --- | --- |
| China | `cn` |
| Europe | `de` |
| India | `i2` |
| Russia | `ru` |
| Singapore | `sg` |
| United States | `us` |

For a European Mi Home account, select **Europe (`de`)**. Selecting another region can result in an empty or incomplete camera list.

You can also select **Use an existing Mi Home account credential** and supply your numeric Xiaomi account ID and account **passToken**. If migrating from go2rtc, this is the account credential under its `xiaomi:` configuration section. It is different from an individual camera's 32-character device token.

The password is used only during interactive login. Home Assistant stores the reusable account credential and completed authentication session so the integration can reconnect.

## Camera options

Open **Settings → Devices & services → Xiaomi Camera Native → Options → Configure a camera**.

| Option | Default | Purpose |
| --- | --- | --- |
| Camera IPv4 address | Discovered address | Local address used to connect to the camera. |
| Automatically update camera IP | Enabled | Recover a changed address from matching router trackers or Xiaomi cloud discovery, and save it after a successful connection. |
| CS2 transport | Automatic | Accept the camera's negotiated UDP or TCP transport; manual choices are also available. |
| Camera quality | HD; Automatic for C301 | Select the camera's own stream quality. |
| Video output | H.264 | Convert to H.264, or preserve the original encoded video. |
| Maximum H.264 height | 720p | Choose 360p, 720p, 1080p or 2160p. |
| Disconnect after no viewers | 30 seconds | Idle timeout, configurable from 10 to 300 seconds. |

The options menu also provides **Discover and select cameras** to update the camera selection. Existing camera entity IDs are retained for cameras that remain selected.

### H.264 output and CPU use

The default output is **H.264 with a maximum height of 720 pixels**. FFmpeg converts the camera video on the Home Assistant host, using `libx264`. Higher output resolutions increase CPU usage while a stream is active.

The height setting is an upper limit: the integration does not upscale a smaller camera image. Selecting 2160p therefore does not turn a lower-resolution camera into a 4K camera.

Select **Original** to retain the camera's encoded H.264 or H.265 video without transcoding. In this mode, the maximum-height setting is ignored. H.265 playback depends on the browser and device.

A camera's `source_codec` attribute describes its incoming video. Seeing `H.265` there while **H.264** output is selected is expected.

Hardware-accelerated transcoding is not implemented.

## Pan and tilt controls

### While watching video

Open a native Xiaomi camera's usual Home Assistant pop-up. The bottom bar contains **left, up, down and right** arrow buttons alongside **Download snapshot**.

Each press sends **one movement step**. The current video player stays in place, and the controls use the same button entities available on the camera's device page.

The frontend helper loads automatically. If the arrows do not appear after upgrading:

1. Restart Home Assistant and refresh the browser page.
2. Try a hard refresh or fully reopen the Companion app.
3. Confirm that you opened a `camera.*` entity from **Xiaomi Camera Native**.
4. Confirm that the camera's movement button entities are enabled.

The pop-up enhancement follows Home Assistant's current camera dialog structure. A future frontend change may require an update to the helper. The separate device buttons remain available if the helper cannot attach.

### Device buttons and automations

Each supported camera has four ordinary `button.*` entities:

- **Pan left**
- **Pan right**
- **Tilt up**
- **Tilt down**

Find their actual entity IDs on the camera's device page. Add them to a dashboard or use the standard `button.press` action in an automation. The pop-up resolves targets through the entity registry, so renamed button IDs remain supported.

While video is running, movement commands reuse its encrypted MISS connection. If the camera is idle, the integration opens a brief control-only connection and closes it after the step. This does not start video capture or an encoder; a cold connection still requires fresh cloud session keys.

Overlapping presses are rejected instead of queued. Movement commands are not automatically replayed on a new connection after a failure, because the camera may already have moved.

These controls perform discrete steps. Continuous movement, zoom, calibration, presets and position feedback are not implemented.

### Chinese `ip029a` model — verified PTZ support (12 November 2026)

1. Sign in to the Xiaomi account region where the camera is registered (the reported test used **China, `cn`**).
2. Choose `chuangmi.camera.ip029a`. The four PTZ `button.*` entities are created automatically; **there is no experimental pan/tilt switch to enable** since v0.3.12.
3. To match the tested playback setup, begin with **CS2 transport: Automatic** (the confirmed negotiated transport was UDP) and **Video output: H.264**. The tested source codec was **H.265**.
4. Open the native camera entity and try single movement presses in a clear, safe area. The buttons send discrete steps; no calibration, presets or position feedback are implemented.
5. If a camera revision behaves differently, report the model, firmware, region, transport, playback and physical PTZ result, along with sanitized `pan_tilt_supported` and `last_ptz_error` diagnostics. Do not post Xiaomi credentials or camera keys.

**Scope of evidence:** One `ip029a` camera was physically tested for left, right, up and down movement on integration v0.3.11 with Home Assistant 2026.11.1. A second `ip029a` camera streamed successfully but its motors were not tested. This is a user report, not a video recording independently reviewed by maintainers. [Full report](docs/PTZ_HARDWARE_VERIFICATION_2026-11-12_ip029a.md).

### Physical motor verification (24 October 2026)

The owner tested **Mi 360 2K / `chuangmi.camera.029a02`**, **C200 / `chuangmi.camera.046c04`**, and **C301 / `mxiang.camera.c301`** with Xiaomi Camera Native v0.3.8 on physical cameras. The screen recordings show changes in the camera scene alongside native `button.*` PTZ activations. The Home Assistant recorder independently logged matching left/right/up/down events. Review the [model-specific report](docs/PTZ_HARDWARE_VERIFICATION_2026-10-24.md) and the [three published recordings](https://github.com/hacs/default/pull/12439#issuecomment-6388692080). The motor command implementation remains unchanged through v0.3.14. These observations do not establish firmware-wide compatibility or a motor position acknowledgement.

## HomeKit

The integration provides a standard camera stream source that can be used by Home Assistant's [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/).

Keep this integration's output set to **H.264**. In HomeKit Bridge options, select the camera under **Cameras that support native H.264 streams** to allow forwarding without another video encode; the YAML equivalent is `video_codec: copy`.

Select the native camera entity when exposing it to HomeKit. Audio is unavailable in this release. The movement controls do not appear inside Apple's camera interface, and HomeKit Bridge does not support HomeKit Secure Video recording.

End-to-end playback in Apple Home has not been verified by this project.

## How streaming works

Xiaomi's cloud supplies authentication and per-connection camera session keys. The integration then connects to the camera over the LAN using CS2 and decrypts its MISS video stream.

The video is packaged as MPEG-TS, optionally converted to H.264, and served to Home Assistant through an in-process endpoint bound to **127.0.0.1**. Home Assistant's built-in `stream` integration handles HLS playback.

Viewers and snapshots share the camera session. The connection closes after the configured idle timeout when there are no consumers. A live dashboard card, a preloaded stream or another playback client can keep it active.

CS2 starts with UDP communication to camera port **32108**, then uses the negotiated UDP or TCP port. Port forwarding is not required.

**Local video does not mean fully offline operation:** Xiaomi's cloud is still required when authenticating or obtaining fresh connection keys.

## Diagnostics and troubleshooting

Camera attributes include:

| Attribute | Meaning |
| --- | --- |
| `connection_status` | Idle, connecting, streaming, reconnecting or error. |
| `transport` | The negotiated CS2 transport. |
| `source_codec` | Incoming H.264 or H.265 video codec. |
| `video_mode` | Configured H.264 or Original output mode. |
| `frames_received` | Decrypted source frame count. |
| `reconnects` | Reconnection attempts. |
| `last_error` | Latest video-session error. |
| `pan_tilt_supported` | Whether the four buttons are enabled for this camera. |
| `pan_tilt_experimental` | True only when experimental PTZ is enabled for an unverified model. Always false for `ip029a` since v0.3.12; CW500 Dual requires explicit opt-in. |
| `last_ptz_error` | Latest movement-command error. |
| `ip_address` | Current local camera address. |
| `auto_update_ip` | Whether automatic address recovery is enabled. |
| `address_source` | Configured address, matching router tracker, or Xiaomi cloud discovery. |
| `address_updates` | Number of address changes accepted after a successful connection. |

`idle` is normal when nobody is watching. A nonzero source frame count confirms video reception, but does not by itself prove that a browser decoded the output.

| Symptom | Checks |
| --- | --- |
| No cameras discovered | Confirm the account, region and Mi Home device ownership. |
| Authentication failure | Reauthenticate the integration; check the missing field names in the error without sharing their values. |
| CS2 handshake timeout | Check the camera address, LAN reachability and transport. Close competing camera viewers during the first test. |
| Missing or poor-quality C200 video | Try HD or explicit Quality 3. |
| C301 does not produce video | Start with Automatic camera quality. |
| H.264 conversion fails | Confirm FFmpeg includes `libx264`, or try Original output. |
| High CPU usage | Lower the H.264 height, close unused live views, or use Original when your playback client supports it. |
| Movement controls report an error | Check `last_ptz_error`, camera reachability and account authentication. |

When reporting an issue, include the camera model, firmware, Home Assistant version, integration version, chosen transport/output mode, and relevant sanitized logs or integration diagnostics.

## Privacy and credentials

- Video travels from the camera to Home Assistant over the LAN; this integration does not proxy it through a go2rtc server.
- Account credentials and session keys are stored in Home Assistant and excluded from integration diagnostics.
- The internal media endpoint uses a random port and per-start secret and is bound to the loopback interface.
- Treat Home Assistant configuration storage and backups as sensitive. Do not publish passTokens, session keys, endpoint secrets or complete configuration dumps in issues.

## Current limitations

- No audio or two-way talk.
- No zoom, continuous PTZ, presets, calibration or position feedback.
- No SD-card playback or camera motion-event entities.
- No hardware transcoding or independent WebRTC server.
- No support for non-CS2 Xiaomi camera protocols.
- Cloud access remains necessary for connection provisioning.
- Camera firmware and Home Assistant frontend compatibility require further testing.

## Development and testing

Run from the repository root with Python 3.12 or later:

```bash
python3 tools/validate_package.py
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
```

These commands check package metadata, translation/version/license consistency,
the verified PTZ allowlist, the explicitly opt-in CW500 experimental model and Python syntax. The bundled tests are
**offline structural checks**; they are not a substitute for camera
integration or on-device testing. Remote GitHub Actions run HACS and
Hassfest validations after you push the repository.

Earlier documentation described a larger set of protocol and DOM tests
that is **not included** in the currently published repository.
See [VALIDATION.md](VALIDATION.md) for test scope and limits.

## Credits and license

Developed by **Kosztyk**.

The Xiaomi cloud and MISS/CS2 protocol implementations adapt work from [AlexxIT/go2rtc](https://github.com/AlexxIT/go2rtc), used under its MIT license. The motor-command reference is documented in [go2rtc PR #2531](https://github.com/AlexxIT/go2rtc/pull/2531).

Original copyright and permission notices are preserved in [LICENSE](License) and [NOTICE](custom_components/xiaomi_camera_native/NOTICE). go2rtc itself and Xiaomi's closed-source SDK are not bundled or executed by this integration.
