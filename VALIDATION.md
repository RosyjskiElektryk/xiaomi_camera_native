# Xiaomi Camera Native — validation status

This document distinguishes packaging checks from functional hardware testing.

## Packaging validation (0.3.14)

Run from the root of the repository:

```bash
python3 tools/validate_package.py
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components
```

The bundled offline tests validate HACS layout, JSON metadata, bundled files,
English translation parity, version/license consistency, the four-model hardware-verified PTZ
allowlist, the fact that `ip029a` works without the old experimental option,
and device-registry reconciliation/removal policy using offline test doubles. Compilation checks Python syntax. **Offline checks do not validate streaming, authentication or physical movement**.

Once published to GitHub, review the results of the `HACS Validation` and
`Hassfest Validation` jobs under GitHub Actions. Their result cannot be
confirmed by local packaging checks.

## Hardware and runtime compatibility

On **2026-10-24** the owner tested actual Xiaomi cameras using the native
Home Assistant Xiaomi Camera Native v0.3.8 buttons, **not go2rtc**. Screen
recordings show the scene moving during PTZ button presses. Home Assistant's
recorder logged the same native button entities at the corresponding times.

| Camera | Verified model ID | Recording start (EEST) |
| --- | --- | --- |
| Mi 360 Home Security Camera 2K | `chuangmi.camera.029a02` | 21:55:21 |
| Xiaomi Smart Camera C200 | `chuangmi.camera.046c04` | 21:48:09 |
| Xiaomi Smart Camera C301 | `mxiang.camera.c301` | 22:05:16 |

Detailed timestamp evidence: [PTZ verification report](docs/PTZ_HARDWARE_VERIFICATION_2026-10-24.md).
The three videos and report are publicly attached to the owner's
[review reply on #12439](https://github.com/hacs/default/pull/12439#issuecomment-6388692080)
and remain available after that PR was closed. Direct recording links are in
the report. The tested motor command implementation is unchanged in v0.3.9
through v0.3.14. Firmware identifiers were not available in the HA device registry.
Recorder events alone do not prove motor movement; the changes in the video
provide that separate observation. This does not verify other firmware versions
or provide a motor position/command acknowledgement.

On **2026-11-12**, a separate owner of `chuangmi.camera.ip029a` tested **v0.3.11**
from the integration-only ZIP using Home Assistant **2026.11.1** and Mi Home
**China (`cn`)** account region. The user confirmed actual physical movement
left, right, up and down, including repeated presses, on **one camera**.
Streaming worked on **two** cameras of the model, using CS2/UDP and incoming
H.265 video with H.264 output; **PTZ on the second was not tested**.
The report contained `last_ptz_error: null` and `last_error: null`.
This is **user-reported physical movement, not an independently reviewed video**.
It supports model-level PTZ promotion but cannot guarantee every firmware.
See the [dated ip029a report](docs/PTZ_HARDWARE_VERIFICATION_2026-11-12_ip029a.md).

HACS and Hassfest CI check packaging/integration rules only, not motors.
Audio, HomeKit end-to-end playback and multi-client performance remain
unverified.

## Historical testing reference

Earlier README revisions referred to 73 Python tests, 9 JavaScript DOM tests,
and standalone test tools. Those historical test sources are **not present**
in the published 0.3.7 repository and have not been reconstructed here.
The current `tests/` folder contains offline structural checks, not
the historical protocol, lifecycle or JavaScript test suites.

## Security and troubleshooting

Do not attach Mi Home passwords, passTokens, authorization cookies, personal
endpoint URLs or session keys to public bug reports. Use sanitized HA logs.
