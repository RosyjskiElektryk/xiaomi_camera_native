# Xiaomi Camera Native 0.3.16

## CW500 Dual night vision and fill light

- Add a night-vision mode selector for Off, IR, Auto, Auto full-colour, Always full-colour and Smart full-colour.
- Add a separate Fill light switch.
- Controls are exposed once on the CW500 Dual device, not separately for both lens entities.
- Selecting Off also disables the fill light.
- Settings use Xiaomi's authenticated cloud MIoT property API. The published MIoT specification lists the properties as writable; physical operation still requires validation against the camera and firmware in use.

No installation or merge is performed by this change.
