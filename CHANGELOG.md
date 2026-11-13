# Changelog

## 0.3.15 — experimental CW500 Dual primary-lens PTZ

- Add an explicit opt-in for experimental PTZ on the CW500 Dual.
- Expose movement buttons only for the motorized primary lens; the secondary lens remains video-only.
- Route movement commands through the active shared MISS connection while streaming, or use a short control-only connection while idle.
- Never automatically retry a movement command after a transport error.
- Add offline regression checks for active-socket reuse, idle control connections and invalid directions.
- Physical CW500 motor movement remains unverified; enable the option only for controlled testing.
## 0.3.14 — CW500 Dual dual-lens video foundation

- Add the CW500 Dual model identifier and two Home Assistant camera entities for its primary and secondary lenses.
- Use one authenticated MISS/CS2 connection and demultiplex interleaved packets by the verified lens flag bits.
- Keep each logical lens on its own MPEG-TS muxer, output subscribers, snapshot path and optional H.264 encoder.
- Preserve the existing primary camera unique ID so existing dashboards and automations keep their entity reference.
- Add offline checks for protocol command shape, lens routing and entity wiring.
- Dual-lens operation still requires live CW500 hardware validation; SD-card playback and PTZ are not included.


## 0.3.13 — safe device removal after Rediscover

- Automatically prune device- and entity-registry records for Xiaomi cameras
  deselected in Rediscover once the remaining camera platforms have loaded.
  This also cleans up already-orphaned records after restart/reload.
- Implement `async_remove_config_entry_device` to permit deleting an orphaned
  camera from the Home Assistant device page. Active/selected cameras and
  devices belonging to other integration entries cannot be removed this way.
- Remove saved profiles for deselected cameras so re-adding them starts with
  clean defaults. Preserve the other cameras' profiles.
- Add offline regression tests for active-camera protection, orphan removal,
  foreign/shared-device protection, PTZ entity cleanup and repeat cleanup.
- No changes to Xiaomi transport, provisioning, stream handling or PTZ commands.


## 0.3.12 — `ip029a` PTZ promoted after hardware test

- Promote `chuangmi.camera.ip029a` into the verified PTZ model allowlist.
  All four step buttons are now available without the prior experimental switch.
- Record owner-reported physical left/right/up/down movement on **one**
  `ip029a` camera, confirmed working repeatedly on v0.3.11, plus video on
  two same-model cameras using China (`cn`) region (HA 2026.11.1).
- Keep saved experimental-option profiles compatible, while hiding the
  opt-in control for the now-verified model. No other models gain access.
- Add evidence and updated offline regression tests. Keep streaming and
  MISS `0x112` motor command implementations unchanged.

## 0.3.11 — experimental Chinese `chuangmi.camera.ip029a` support

- Recognize the Chinese Xiaomi Smart Camera PTZ Version 2K model ID.
- Expose native PTZ step buttons for this model **only after explicit opt-in**
  in its camera options. Default is disabled and verified models are unchanged.
- Keep MISS 0x112 motor commands, CS2 transport, stream decoding and Xiaomi
  cloud provisioning unchanged; streaming/PTZ remain unverified on ip029a.
- Add a diagnostic flag, English UI strings, compatibility instructions,
  regression checks, and align packaging/release metadata with 0.3.11.


## 0.3.10 — HACS resubmission documentation

- Link the three published PTZ recordings and review reply from the README,
  validation document and hardware report; remove stale upload instructions.
- Document the existing automatic camera IP recovery option and attributes.
- Update HACS publishing guidance for the closed #12439 and its replacement.
- Correct NOTICE and testing documentation to describe the seven shipped
  structural checks without claiming absent protocol/lifecycle test suites.
- Align manifest, runtime version, NOTICE, packaging checks and guarded release
  workflow at 0.3.10; retain every v0.3.9 review fix.

The tested motor implementation and three-model PTZ allowlist are unchanged.
No streaming, authentication, command payload or IP recovery behavior changed.

## 0.3.9 — HACS review fixes

- Document physical PTZ tests through Xiaomi Camera Native's Python control
  path on the three exactly whitelisted camera models (2026-10-24).
- Preserve the three-model PTZ whitelist; enable no additional models.
- Sync English translations to strings.json, restoring the auto_update_ip label.
- Align frontend/diagnostics VERSION and manifest on 0.3.9.
- Match root MIT license to bundled license with Kosztyk and Alexey Khit
  attribution and preserve NOTICE.
- Add static reviewer regression tests, and guarded release workflow.

No changes to command payloads, streaming, authentication or IP recovery.

## 0.3.8 — HACS publication preparation

- Add missing `documentation` and `issue_tracker` manifest fields.
- Normalize the display name in `hacs.json`.
- Add HACS, Hassfest and offline packaging validation workflows.
- Add basic packaging tests and a validation-status document.
- Clarify HACS installation, fix links in README and remove references to
  absent test files and development utilities.
- Preserve all existing Xiaomi streaming, cloud login, camera, PTZ and
  frontend implementation files unchanged.

This is a packaging/documentation update, not a camera protocol fix.
