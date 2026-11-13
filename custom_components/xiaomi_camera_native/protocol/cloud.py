"""Mi Home login, RC4 request signing and per-connection MISS provisioning.

Adapted from AlexxIT/go2rtc's Xiaomi client, under MIT (see NOTICE).
Passwords are retained only during an interactive login, never in entry data.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from .crypto import b64, encrypt_cloud_request, generate_keypair, rc4_drop1024
from .errors import AuthenticationError, CloudError, LoginChallenge, ProtocolError

REGIONS = {
    "cn": "China",
    "de": "Europe",
    "i2": "India",
    "ru": "Russia",
    "sg": "Singapore",
    "us": "United States",
}
ACCOUNT = "https://account.xiaomi.com"
TIMEOUT = aiohttp.ClientTimeout(total=20)


@dataclass(repr=False)
class Credentials:
    user_id: str = ""
    pass_token: str = ""
    service_token: str = ""
    c_user_id: str = ""
    security: bytes = b""

    def persistent(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "pass_token": self.pass_token,
            "service_token": self.service_token,
            "c_user_id": self.c_user_id,
            "security": b64(self.security),
        }

    def missing(self) -> list[str]:
        """Names only; safe to include in an authentication error."""
        return [
            name
            for name, value in (
                ("userId", self.user_id),
                ("serviceToken", self.service_token),
                ("ssecurity", self.security),
                ("passToken", self.pass_token),
            )
            if not value
        ]


@dataclass
class CameraDevice:
    did: str
    name: str
    model: str
    host: str
    mac: str = ""
    online: bool = True

    @classmethod
    def from_cloud(cls, data: dict[str, Any]) -> CameraDevice:
        return cls(
            did=str(data["did"]),
            name=str(data.get("name") or data.get("model") or "Xiaomi camera"),
            model=str(data.get("model", "")),
            host=str(data.get("localip") or ""),
            mac=str(data.get("mac") or ""),
            online=bool(data.get("isOnline", True)),
        )


@dataclass(repr=False)
class Provisioning:
    public: bytes
    private: bytes
    device_public: bytes
    signature: str
    vendor: str


class XiaomiCloud:
    """One account and one cloud region. HTTP sessions are injected."""

    def __init__(self, session: aiohttp.ClientSession, region: str = "de") -> None:
        if region not in REGIONS:
            raise ValueError("Unsupported Xiaomi region")
        self.session = session
        self.region = region
        self.credentials = Credentials()
        self._refresh_lock = asyncio.Lock()
        self._auth: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        prefix = "" if self.region == "cn" else f"{self.region}."
        return f"https://{prefix}api.io.mi.com/app"

    async def _login_request(
        self,
        method: str,
        url: str,
        *,
        form: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        image: bool = False,
    ) -> tuple[Any, dict[str, str]]:
        try:
            async with self.session.request(
                method,
                url,
                data=form,
                params=params,
                cookies=cookies,
                timeout=TIMEOUT,
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise CloudError("Xiaomi login service is unavailable")
                body = await response.read()
                received = {name: value.value for name, value in response.cookies.items()}
                if not image:
                    self._take_login_response(response)
        except (aiohttp.ClientError, TimeoutError):
            raise CloudError("Cannot connect to Xiaomi login service") from None
        if image:
            if len(body) > 1024 * 1024:
                raise CloudError("Xiaomi CAPTCHA image is too large")
            return body, received
        if not body.startswith(b"&&&START&&&"):
            raise CloudError("Unexpected Xiaomi login response")
        try:
            decoded = json.loads(body[11:])
            if not isinstance(decoded, dict):
                raise ValueError
            return decoded, received
        except (ValueError, UnicodeError):
            raise CloudError("Invalid Xiaomi login response") from None

    async def login(self, username: str, password: str) -> None:
        self._auth = {"username": username, "password": password}
        await self._password_login()

    async def _password_login(self) -> None:
        first, _ = await self._login_request(
            "GET", ACCOUNT + "/pass/serviceLogin", params={"_json": "true", "sid": "xiaomiio"}
        )
        required = ("sid", "callback", "_sign", "qs")
        if not all(key in first for key in required):
            raise AuthenticationError("Xiaomi login initialization failed")
        form = {key: str(first[key]) for key in required}
        form.update(
            {
                "_json": "true",
                "user": self._auth["username"],
                "hash": hashlib.md5(self._auth["password"].encode()).hexdigest().upper(),
            }
        )
        cookies = {"deviceId": secrets.token_hex(8)}
        if self._auth.get("captcha_code"):
            form["captCode"] = self._auth["captcha_code"]
            cookies["ick"] = self._auth.get("ick", "")
        result, _ = await self._login_request(
            "POST", ACCOUNT + "/pass/serviceLoginAuth2", form=form, cookies=cookies
        )
        if result.get("captchaURL"):
            await self._captcha(str(result["captchaURL"]))
        if result.get("notificationUrl"):
            await self._start_verification(str(result["notificationUrl"]))
        self._take_login_fields(result)
        if not result.get("location"):
            raise AuthenticationError("Xiaomi rejected the account login")
        await self._finish_auth(str(result["location"]))
        self._auth.clear()

    def _take_login_fields(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise AuthenticationError("Invalid Xiaomi authentication fields")
        for source, target in (
            ("userId", "user_id"),
            ("passToken", "pass_token"),
            ("cUserId", "c_user_id"),
            ("serviceToken", "service_token"),
        ):
            if data.get(source):
                setattr(self.credentials, target, str(data[source]))
        if data.get("ssecurity"):
            try:
                self.credentials.security = base64.b64decode(data["ssecurity"], validate=True)
            except (ValueError, TypeError):
                raise AuthenticationError("Invalid Xiaomi authentication keys") from None

    def _take_login_response(self, response: Any) -> None:
        """Read credentials wherever Xiaomi places them along the login chain."""
        for name, target in (
            ("userId", "user_id"),
            ("cUserId", "c_user_id"),
            ("serviceToken", "service_token"),
            ("passToken", "pass_token"),
        ):
            if name in response.cookies and response.cookies[name].value:
                # Empty/deletion cookies must not erase a valid credential
                # collected from the login JSON or an earlier redirect.
                setattr(self.credentials, target, response.cookies[name].value)
        extra = response.headers.get("Extension-Pragma")
        if extra:
            try:
                self._take_login_fields(json.loads(extra))
            except (ValueError, TypeError):
                raise AuthenticationError("Invalid Xiaomi authentication headers") from None

    async def _captcha(self, path: str) -> None:
        url = urljoin(ACCOUNT, path)
        if urlsplit(url).hostname != "account.xiaomi.com":
            raise CloudError("Unexpected Xiaomi CAPTCHA address")
        image, cookies = await self._login_request("GET", url, image=True)
        self._auth["ick"] = cookies.get("ick", "")
        raise LoginChallenge("captcha", image="data:image/jpeg;base64," + b64(image))

    async def submit_captcha(self, answer: str) -> None:
        if not self._auth.get("ick"):
            raise AuthenticationError("The Xiaomi login challenge expired")
        self._auth["captcha_code"] = answer.strip()
        if self._auth.get("flag"):
            await self._send_ticket()
        else:
            await self._password_login()

    async def _start_verification(self, notification_url: str) -> None:
        url = notification_url.replace("/fe/service/identity/authStart", "/identity/list", 1)
        if urlsplit(url).hostname != "account.xiaomi.com":
            raise AuthenticationError("Unsupported Xiaomi account verification")
        result, cookies = await self._login_request("GET", url)
        flag = str(result.get("flag", ""))
        if flag not in {"4", "8"} or not cookies.get("identity_session"):
            raise AuthenticationError("This Xiaomi account verification method is unsupported")
        self._auth["flag"] = flag
        self._auth["identity_session"] = cookies["identity_session"]
        await self._send_ticket()

    def _verification_name(self) -> str:
        return "Phone" if self._auth.get("flag") == "4" else "Email"

    async def _send_ticket(self) -> None:
        name = self._verification_name()
        cookies = {"identity_session": self._auth["identity_session"]}
        details, _ = await self._login_request(
            "GET",
            ACCOUNT + "/identity/auth/verify" + name,
            params={"_flag": self._auth["flag"], "_json": "true"},
            cookies=cookies,
        )
        if self._auth.get("ick"):
            cookies["ick"] = self._auth["ick"]
        result, _ = await self._login_request(
            "POST",
            ACCOUNT + "/identity/auth/send" + name + "Ticket",
            form={"_json": "true", "icode": self._auth.get("captcha_code", ""), "retry": "0"},
            cookies=cookies,
        )
        if result.get("captchaURL"):
            await self._captcha(str(result["captchaURL"]))
        if result.get("code") != 0:
            raise AuthenticationError("Xiaomi could not send a verification code")
        self._auth.pop("captcha_code", None)
        raise LoginChallenge(
            "verification",
            destination=str(
                details.get("maskedPhone") or details.get("maskedEmail") or "your account"
            ),
        )

    async def submit_verification(self, ticket: str) -> None:
        if not self._auth.get("identity_session"):
            raise AuthenticationError("The Xiaomi login challenge expired")
        result, _ = await self._login_request(
            "POST",
            ACCOUNT + "/identity/auth/verify" + self._verification_name(),
            params={
                "_flag": self._auth["flag"],
                "ticket": ticket.strip(),
                "trust": "false",
                "_json": "true",
            },
            cookies={"identity_session": self._auth["identity_session"]},
        )
        if not result.get("location"):
            raise AuthenticationError("Xiaomi rejected the verification code")
        await self._finish_auth(str(result["location"]))
        self._auth.clear()

    async def _finish_auth(self, location: str) -> None:
        for _ in range(10):
            parsed = urlsplit(location)
            hostname = parsed.hostname or ""
            if parsed.scheme != "https" or not any(
                hostname == domain or hostname.endswith("." + domain)
                for domain in ("xiaomi.com", "mi.com")
            ):
                raise AuthenticationError("Unexpected Xiaomi login redirect")
            try:
                async with self.session.get(
                    location, timeout=TIMEOUT, allow_redirects=False
                ) as response:
                    self._take_login_response(response)
                    if response.status in (301, 302, 303, 307, 308):
                        location = urljoin(location, response.headers.get("Location", ""))
                        continue
                    if response.status != 200:
                        raise AuthenticationError("Xiaomi authentication callback failed")
                    break
            except (aiohttp.ClientError, TimeoutError):
                raise CloudError("Cannot finish Xiaomi authentication") from None
        else:
            raise AuthenticationError("Too many Xiaomi login redirects")
        if missing := self.credentials.missing():
            raise AuthenticationError(
                "Xiaomi did not return complete authentication credentials "
                f"(missing: {', '.join(missing)})"
            )

    async def authenticate(self, saved: dict[str, Any]) -> None:
        """Restore a working login; old entries with only passToken still work."""
        try:
            security = base64.b64decode(saved.get("security", ""), validate=True)
        except (ValueError, TypeError):
            security = b""
        self.credentials = Credentials(
            user_id=str(saved.get("user_id") or ""),
            pass_token=str(saved.get("pass_token") or ""),
            service_token=str(saved.get("service_token") or ""),
            c_user_id=str(saved.get("c_user_id") or ""),
            security=security,
        )
        if not self.credentials.missing():
            try:
                # Verify cached credentials with Xiaomi before accepting them.
                # Transient connection errors propagate as setup retries.
                await self.request("/v2/home/device_list_page", {"limit": 1}, retry=False)
                return
            except AuthenticationError:
                pass
        await self.login_with_token(self.credentials.user_id, self.credentials.pass_token)

    async def login_with_token(self, user_id: str, pass_token: str) -> None:
        # A refresh must not mix an old serviceToken/key with new credentials.
        self.credentials = Credentials(user_id=user_id.strip(), pass_token=pass_token.strip())
        result, _ = await self._login_request(
            "GET",
            ACCOUNT + "/pass/serviceLogin",
            params={"_json": "true", "sid": "xiaomiio"},
            cookies={"userId": self.credentials.user_id, "passToken": self.credentials.pass_token},
        )
        if not result.get("location"):
            raise AuthenticationError("Xiaomi account credential expired; sign in again")
        self._take_login_fields(result)
        await self._finish_auth(str(result["location"]))

    async def request(self, path: str, params: dict[str, Any], *, retry: bool = True) -> Any:
        if not self.credentials.service_token:
            raise AuthenticationError("Xiaomi account is not authenticated")
        body, signed = encrypt_cloud_request(
            self.credentials.security, path, json.dumps(params, separators=(",", ":"))
        )
        creds = self.credentials
        try:
            async with self.session.post(
                self.base_url + path,
                data=body,
                cookies={
                    "userId": creds.user_id,
                    "cUserId": creds.c_user_id,
                    "serviceToken": creds.service_token,
                },
                headers={"MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4", "Accept-Encoding": "identity"},
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    result = {"code": -10001}
                elif response.status != 200:
                    raise CloudError(f"Xiaomi cloud HTTP error {response.status}")
                else:
                    raw = await response.read()
                    try:
                        result = json.loads(
                            rc4_drop1024(signed, base64.b64decode(raw, validate=True))
                        )
                    except (ValueError, UnicodeError):
                        # Some authentication errors are returned unencrypted.
                        try:
                            result = json.loads(raw)
                        except (ValueError, UnicodeError):
                            raise CloudError("Invalid Xiaomi cloud response") from None
        except (aiohttp.ClientError, TimeoutError):
            raise CloudError("Cannot connect to Xiaomi cloud") from None
        if not isinstance(result, dict):
            raise CloudError("Unexpected Xiaomi cloud response")
        code = result.get("code")
        if code in {-10001, -10000, -10004, 3}:
            if retry:
                async with self._refresh_lock:
                    await self.login_with_token(creds.user_id, creds.pass_token)
                return await self.request(path, params, retry=False)
            raise AuthenticationError("Xiaomi account needs to be authenticated again")
        if code != 0:
            raise CloudError(
                f"Xiaomi cloud rejected the request (code {code if isinstance(code, int) else 'unknown'})"
            )
        return result.get("result")

    async def set_miot_property(self, did: str, siid: int, piid: int, value: Any) -> None:
        """Write one MIoT property through Xiaomi's authenticated cloud API."""
        result = await self.request(
            "/miotspec/prop/set",
            {"params": [{"did": did, "siid": siid, "piid": piid, "value": value}]},
        )
        if not isinstance(result, list) or len(result) != 1:
            raise CloudError("Xiaomi returned an invalid MIoT property response")
        item = result[0]
        if not isinstance(item, dict) or item.get("code") != 0:
            raise CloudError("Xiaomi rejected the MIoT property update")

    async def get_miot_property(self, did: str, siid: int, piid: int) -> Any:
        """Read one MIoT property through Xiaomi's authenticated cloud API."""
        result = await self.request(
            "/miotspec/prop/get",
            {"params": [{"did": did, "siid": siid, "piid": piid}]},
        )
        if not isinstance(result, list) or len(result) != 1:
            raise CloudError("Xiaomi returned an invalid MIoT property response")
        item = result[0]
        if not isinstance(item, dict) or item.get("code") != 0 or "value" not in item:
            raise CloudError("Xiaomi could not read the MIoT property")
        return item["value"]

    async def devices(self) -> list[CameraDevice]:
        devices: dict[str, CameraDevice] = {}
        start = ""
        for _ in range(100):
            result = await self.request(
                "/v2/home/device_list_page", {"start_did": start, "limit": 200}
            )
            if not isinstance(result, dict):
                raise CloudError("Invalid Xiaomi device list")
            for raw in result.get("list", []):
                if (
                    isinstance(raw, dict)
                    and raw.get("did")
                    and any(
                        token in str(raw.get("model", "")) for token in (".camera.", ".cateye.")
                    )
                ):
                    device = CameraDevice.from_cloud(raw)
                    devices[device.did] = device
            next_start = str(result.get("next_start_did") or "")
            if not result.get("has_more") or not next_start or next_start == start:
                return list(devices.values())
            start = next_start
        raise CloudError("Xiaomi device list pagination limit exceeded")

    async def provision(self, device: CameraDevice) -> Provisioning:
        if ".cateye." in device.model:
            # Battery cameras may need waking before session keys are issued.
            await self.request(
                "/home/rpc/" + device.did, {"id": 1, "method": "wakeup", "params": {"video": "1"}}
            )
        public, private = generate_keypair()
        result = await self.request(
            "/v2/device/miss_get_vendor",
            {
                "app_pubkey": public.hex(),
                "did": device.did,
                "support_vendors": "TUTK_CS2_MTP",
            },
        )
        if not isinstance(result, dict):
            raise ProtocolError("Invalid Xiaomi camera provisioning response")
        vendor = result.get("vendor", {})
        if not isinstance(vendor, dict) or vendor.get("vendor") != 4:
            raise ProtocolError(
                "This camera does not offer CS2; TUTK and legacy cameras are not supported yet"
            )
        try:
            key = bytes.fromhex(result["public_key"])
            signature = str(result["sign"])
            if len(key) != 32 or not signature:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ProtocolError("Xiaomi returned invalid camera session keys") from None
        return Provisioning(public, private, key, signature, "cs2")
