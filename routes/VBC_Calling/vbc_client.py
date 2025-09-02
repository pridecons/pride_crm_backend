# routes/VBC_Calling/vbc_client.py
from __future__ import annotations

import os
import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Callable

import httpx


# =========================================================
# Environment / Config
# =========================================================
@dataclass
class VBCEnv:
    # account/app creds (env-driven)
    account_id: str = "self"
    client_id: str = ""
    client_secret: str = ""

    # token endpoints / base API
    scope: str = "openid"
    grant_type: str = "password"
    get_token_url: str = "https://api.vonage.com/token"
    api_url: str = "https://api.vonage.com/t"
    api_env: str = "vbc.prod"

    # user creds (usually provided by DB getters, can be blank here)
    vbc_user_username: Optional[str] = None
    vbc_user_password: Optional[str] = None

    # token state
    token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None  # UTC

    # optional defaults used by convenience methods
    cr_start_gte: Optional[str] = None  # "YYYY-MM-DDTHH:MM:SSZ"
    cr_start_lte: Optional[str] = None
    reports_start_gte: Optional[str] = None  # "YYYY-MM-DD HH:MM:SS"
    reports_start_lte: Optional[str] = None

    @staticmethod
    def from_env(
        account_id_var: str = "VBC_ACCOUNT_ID",
        client_id_var: str = "API_CLIENT_ID",
        client_secret_var: str = "API_CLIENT_SECRET",
        api_env_var: str = "VBC_API_ENV",  # optional override (default vbc.prod)
        api_url_var: str = "VBC_API_URL",  # optional override (default https://api.vonage.com/t)
        token_url_var: str = "VBC_TOKEN_URL",  # optional override (default https://api.vonage.com/token)
    ) -> "VBCEnv":
        account_id = os.getenv(account_id_var, "self")
        client_id = os.getenv(client_id_var, "")
        client_secret = os.getenv(client_secret_var, "")
        api_env = os.getenv(api_env_var, "vbc.prod")
        api_url = os.getenv(api_url_var, "https://api.vonage.com/t")
        token_url = os.getenv(token_url_var, "https://api.vonage.com/token")

        if not client_id or not client_secret:
            raise RuntimeError(
                f"Missing API client credentials. Set {client_id_var} and {client_secret_var} env vars."
            )

        return VBCEnv(
            account_id=account_id,
            client_id=client_id,
            client_secret=client_secret,
            api_env=api_env,
            api_url=api_url,
            get_token_url=token_url,
        )

    @staticmethod
    def from_postman_env(env_json: Dict[str, Any]) -> "VBCEnv":
        kv = {item["key"]: item.get("value") for item in env_json.get("values", [])}
        return VBCEnv(
            account_id=kv.get("account_id", "self"),
            client_id=kv["client_id"],
            client_secret=kv["client_secret"],
            scope=kv.get("scope", "openid"),
            grant_type=kv.get("grant_type", "password"),
            get_token_url=kv.get("get_token_url", "https://api.vonage.com/token"),
            api_url=kv.get("api_url", "https://api.vonage.com/t"),
            api_env=kv.get("api_env", "vbc.prod"),
            token=kv.get("token") or None,
            refresh_token=kv.get("refresh_token") or None,
            cr_start_gte=kv.get("cr_start_gte") or None,
            cr_start_lte=kv.get("cr_start_lte") or None,
            reports_start_gte=kv.get("reports_start_gte") or None,
            reports_start_lte=kv.get("reports_start_lte") or None,
        )

    def to_json_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["token_expires_at"] = self.token_expires_at.isoformat() if self.token_expires_at else None
        return d

    @staticmethod
    def from_json_dict(d: Dict[str, Any]) -> "VBCEnv":
        iso = d.get("token_expires_at")
        d = {**d}
        if iso:
            d["token_expires_at"] = datetime.fromisoformat(iso)
        return VBCEnv(**d)  # type: ignore[arg-type]


# Types for DB getters you’ll provide
CredGetter = Callable[[], tuple[str, str]]     # returns (username, password)
ExtGetter = Callable[[], str]                  # returns extension like "611"


# =========================================================
# Client
# =========================================================
class VBCClient:
    def __init__(
        self,
        env: VBCEnv,
        timeout: float = 30.0,
        cred_getter: Optional[CredGetter] = None,
        ext_getter: Optional[ExtGetter] = None,
        token_cache_path: Optional[str] = None,   # NEW: persistent cache per user
    ):
        self.env = env
        self.http = httpx.Client(timeout=timeout, follow_redirects=False)
        self.cred_getter = cred_getter
        self.ext_getter = ext_getter
        self.token_cache_path = token_cache_path

        # NEW: prevent parallel refresh stampede
        self._lock = threading.Lock()

        # auto-load cached tokens if provided
        if self.token_cache_path:
            self.load_tokens(self.token_cache_path)

    # ---------- Token management ----------
    def _ensure_user_creds(self) -> None:
        # get creds from DB if missing or you want to refresh every time
        if self.cred_getter:
            username, password = self.cred_getter()
            self.env.vbc_user_username = username
            self.env.vbc_user_password = password

        if not self.env.vbc_user_username or not self.env.vbc_user_password:
            raise RuntimeError("Missing VBC user credentials. Provide via DB getter or set on VBCEnv.")

    def _set_tokens(self, data: Dict[str, Any]) -> None:
        self.env.token = data.get("access_token")
        self.env.refresh_token = data.get("refresh_token", self.env.refresh_token)
        expires_in = data.get("expires_in", 3600)
        self.env.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # auto-save if cache path configured
        if self.token_cache_path:
            try:
                self.save_tokens(self.token_cache_path)
            except Exception:
                # do not break request if disk write fails
                pass

    def authenticate(self) -> None:
        self._ensure_user_creds()
        payload = {
            "grant_type": self.env.grant_type,
            "scope": self.env.scope,
            "username": f"{self.env.vbc_user_username}@{self.env.api_env}",
            "password": self.env.vbc_user_password,
            "client_id": self.env.client_id,
            "client_secret": self.env.client_secret,
        }
        r = self.http.post(
            self.env.get_token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        self._set_tokens(r.json())

    def refresh_auth(self) -> None:
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.env.client_id,
            "client_secret": self.env.client_secret,
            "refresh_token": self.env.refresh_token or "",
        }
        r = self.http.post(
            self.env.get_token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        self._set_tokens(r.json())

    def ensure_token(self, skew_seconds: int = 120) -> None:
        """
        Ensure a valid token exists. Refresh a little before real expiry (skew).
        Thread-safe to avoid multiple refreshes in parallel.
        """
        now = datetime.now(timezone.utc)
        needs_refresh = (
            not self.env.token
            or not self.env.token_expires_at
            or (self.env.token_expires_at - now).total_seconds() < skew_seconds
        )
        if not needs_refresh:
            return

        with self._lock:
            # re-check under lock
            now = datetime.now(timezone.utc)
            if (
                self.env.token
                and self.env.token_expires_at
                and (self.env.token_expires_at - now).total_seconds() >= skew_seconds
            ):
                return

            if self.env.refresh_token:
                try:
                    self.refresh_auth()
                    return
                except httpx.HTTPError:
                    pass
            self.authenticate()

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.env.token}"}

    def _base(self) -> str:
        return f"{self.env.api_url}/{self.env.api_env}"

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        self.ensure_token()
        url = f"{self._base()}{path}"
        headers = kwargs.pop("headers", {}) or {}
        headers.update(self._headers())
        resp = self.http.request(method, url, headers=headers, **kwargs)

        if resp.status_code != 401:
            resp.raise_for_status()
            return resp

        # If 401, try one refresh/re-auth (race-safe)
        with self._lock:
            try:
                if self.env.refresh_token:
                    self.refresh_auth()
                else:
                    self.authenticate()
            except httpx.HTTPError:
                resp.raise_for_status()

            headers = kwargs.get("headers", {}) or {}
            headers.update(self._headers())
            resp2 = self.http.request(method, url, headers=headers, **kwargs)
            resp2.raise_for_status()
            return resp2

    # ---------- Helpers ----------
    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[Dict[str, Any]] = None, data: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return self._request("POST", path, json=json, data=data)

    def put(self, path: str, json: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return self._request("PUT", path, json=json)

    def delete(self, path: str, json: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return self._request("DELETE", path, json=json)

    # ---------- Persistence (optional) ----------
    def save_tokens(self, filepath: str) -> None:
        data = {
            "token": self.env.token,
            "refresh_token": self.env.refresh_token,
            "token_expires_at": self.env.token_expires_at.isoformat() if self.env.token_expires_at else None,
        }
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_tokens(self, filepath: str) -> None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.env.token = d.get("token")
            self.env.refresh_token = d.get("refresh_token")
            iso = d.get("token_expires_at")
            self.env.token_expires_at = datetime.fromisoformat(iso) if iso else None
        except FileNotFoundError:
            pass

    # ---------- Convenience methods (map your Postman collection) ----------

    # Auth (explicit if you want to force refresh)
    def get_token(self) -> Dict[str, Any]:
        self.authenticate()
        return {"access_token": self.env.token, "refresh_token": self.env.refresh_token}

    def refresh_token(self) -> Dict[str, Any]:
        self.refresh_auth()
        return {"access_token": self.env.token, "refresh_token": self.env.refresh_token}

    # Provisioning
    def provisioning_account(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/provisioning/api/accounts/{aid}").json()

    def provisioning_locations(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/provisioning/api/accounts/{aid}/locations").json()

    def provisioning_location(self, location_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/provisioning/api/accounts/{aid}/locations/{location_id}").json()

    def provisioning_extensions(self, account_id: Optional[str] = None, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/provisioning/api/accounts/{aid}/extensions", params=filters or None).json()

    def provisioning_extension(self, extension_number: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/provisioning/api/accounts/{aid}/extensions/{extension_number}").json()

    def provisioning_users(self, account_id: Optional[str] = None, page_size: int = 200, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        params = {"page_size": page_size, **(filters or {})}
        return self.get(f"/provisioning/api/accounts/{aid}/users", params=params).json()

    def provisioning_user(self, user_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/provisioning/api/accounts/{aid}/users/{user_id}").json()

    # Reports: Call Logs
    def reports_call_logs(
        self,
        account_id: Optional[str] = None,
        start_gte: Optional[str] = None,
        start_lte: Optional[str] = None,
        **filters,
    ) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        start_gte = start_gte or self.env.reports_start_gte
        start_lte = start_lte or self.env.reports_start_lte
        if not start_gte or not start_lte:
            raise ValueError("start_gte and start_lte are required (YYYY-MM-DD HH:mm:ss)")
        params = {"start:gte": start_gte, "start:lte": start_lte, **(filters or {})}
        return self.get(f"/reports/accounts/{aid}/call-logs", params=params).json()

    # Telephony
    def telephony_click2dial(
        self,
        to_destination: str,
        *,
        from_destination: Optional[str] = None,
        from_type: str = "extension",
        to_type: str = "pstn",
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        If from_destination is not provided, we'll fetch it via ext_getter() from DB.
        """
        if not from_destination:
            if not self.ext_getter:
                raise ValueError("from_destination is missing and no ext_getter was provided.")
            from_destination = self.ext_getter()

        aid = account_id or self.env.account_id
        payload = {
            "from": {"destination": str(from_destination), "type": from_type},
            "to": {"destination": str(to_destination), "type": to_type},
            "type": "click2dial",
        }
        return self.post(f"/telephony/v3/cc/accounts/{aid}/calls", json=payload).json()

    def telephony_calls(self, account_id: Optional[str] = None, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/telephony/v3/cc/accounts/{aid}/calls", params=filters or None).json()

    def telephony_call(self, call_id: str, account_id: Optional[str] = None, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}", params=filters or None).json()

    def telephony_call_update(self, call_id: str, payload: Dict[str, Any], account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.put(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}", json=payload).json()

    def telephony_call_delete(self, call_id: str, payload: Dict[str, Any], account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.delete(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}", json=payload).json()

    def telephony_call_legs(self, call_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}/legs").json()

    def telephony_call_leg(self, call_id: str, leg_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}/legs/{leg_id}").json()

    def telephony_call_leg_put(self, call_id: str, leg_id: str, payload: Dict[str, Any], account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.put(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}/legs/{leg_id}", json=payload).json()

    def telephony_call_leg_delete(self, call_id: str, leg_id: str, payload: Dict[str, Any], account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.delete(f"/telephony/v3/cc/accounts/{aid}/calls/{call_id}/legs/{leg_id}", json=payload).json()

    def telephony_devices(self, account_id: Optional[str] = None, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/telephony/v3/registration/accounts/{aid}/devices", params=filters or None).json()

    def telephony_device(self, device_id: str, account_id: Optional[str] = None, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/telephony/v3/registration/accounts/{aid}/devices/{device_id}", params=filters or None).json()

    # Call Recording - Company
    def cr_company_list(self, account_id: Optional[str] = None, start_gte: Optional[str] = None, start_lte: Optional[str] = None,
                        page_size: int = 20, page: int = 1, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        start_gte = start_gte or self.env.cr_start_gte
        start_lte = start_lte or self.env.cr_start_lte
        if not start_gte or not start_lte:
            raise ValueError("start_gte and start_lte are required (YYYY-MM-DDTHH:MM:SSZ)")
        params = {"start:gte": start_gte, "start:lte": start_lte, "page_size": page_size, "page": page, **(filters or {})}
        return self.get(f"/call_recording/api/accounts/{aid}/company_call_recordings", params=params).json()

    def cr_company_get(self, recording_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/call_recording/api/accounts/{aid}/company_call_recordings/{recording_id}").json()

    def cr_company_delete(self, recording_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.delete(f"/call_recording/api/accounts/{aid}/company_call_recordings/{recording_id}").json()

    def cr_company_export(self, account_id: Optional[str] = None, start_gte: Optional[str] = None, start_lte: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        start_gte = start_gte or self.env.cr_start_gte
        start_lte = start_lte or self.env.cr_start_lte
        payload = {"start:gte": start_gte, "start:lte": start_lte}
        return self.post(f"/call_recording/api/accounts/{aid}/company_call_recordings/export", json=payload).json()

    def cr_company_audio(self, recording_id: str) -> bytes:
        r = self.get(f"/call_recording/api/audio/recording/{recording_id}")
        return r.content

    # Call Recording - On-Demand (per user)
    def cr_user_list(self, user_id: str, account_id: Optional[str] = None, start_gte: Optional[str] = None, start_lte: Optional[str] = None,
                     page_size: int = 20, page: int = 1, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        start_gte = start_gte or self.env.cr_start_gte
        start_lte = start_lte or self.env.cr_start_lte
        params = {"start:gte": start_gte, "start:lte": start_lte, "page_size": page_size, "page": page, **(filters or {})}
        return self.get(f"/call_recording/api/accounts/{aid}/users/{user_id}/call_recordings", params=params).json()

    def cr_user_get(self, user_id: str, recording_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/call_recording/api/accounts/{aid}/users/{user_id}/call_recordings/{recording_id}").json()

    def cr_user_delete(self, user_id: str, recording_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.delete(f"/call_recording/api/accounts/{aid}/users/{user_id}/call_recordings/{recording_id}").json()

    def cr_user_export(self, user_id: str, account_id: Optional[str] = None, start_gte: Optional[str] = None, start_lte: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        start_gte = start_gte or self.env.cr_start_gte
        start_lte = start_lte or self.env.cr_start_lte
        payload = {"start:gte": start_gte, "start:lte": start_lte}
        return self.post(f"/call_recording/api/accounts/{aid}/users/{user_id}/call_recordings/export", json=payload).json()

    def cr_user_jobs(self, user_id: str = "self", account_id: Optional[str] = None, **filters) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/call_recording/api/accounts/{aid}/users/{user_id}/call_recordings/jobs", params=filters or None).json()

    def cr_user_job(self, job_id: str, user_id: str = "self", account_id: Optional[str] = None) -> Dict[str, Any]:
        aid = account_id or self.env.account_id
        return self.get(f"/call_recording/api/accounts/{aid}/users/{user_id}/call_recordings/jobs/{job_id}").json()

    # VIS
    def vis_events(self, **filters) -> Dict[str, Any]:
        return self.get("/vis/v1/self/events", params=filters or None).json()

    def vis_webhook_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.post("/vis/v1/self/webhooks", json=payload).json()

    def vis_webhooks(self) -> Dict[str, Any]:
        return self.get("/vis/v1/self/webhooks").json()

    def vis_webhook_renew(self, webhook_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.put(f"/vis/v1/self/webhooks/{webhook_id}/renew", json=payload).json()

    def vis_calls_list(self, **filters) -> Dict[str, Any]:
        return self.get("/vis/v1/self/calls", params=filters or None).json()

    def vis_call_get(self, call_id: str, **filters) -> Dict[str, Any]:
        return self.get(f"/vis/v1/self/calls/{call_id}", params=filters or None).json()

    def vis_make_call(self, phone_number: str) -> Dict[str, Any]:
        return self.post("/vis/v1/self/calls", json={"phoneNumber": phone_number}).json()


# =========================================================
# Glue helpers: SQLAlchemy getters (use your own Session)
# =========================================================
def sqlalchemy_cred_getter(session_factory, employee_code: str) -> CredGetter:
    from db.models import UserDetails  # adjust import path if needed

    def _getter() -> tuple[str, str]:
        with session_factory() as db:
            user = db.query(UserDetails).filter(UserDetails.employee_code == employee_code).first()
            if not user or not user.vbc_user_username or not user.vbc_user_password:
                raise RuntimeError(f"Missing VBC creds in DB for {employee_code}")
            return user.vbc_user_username, user.vbc_user_password

    return _getter


def sqlalchemy_extension_getter(session_factory, employee_code: str) -> ExtGetter:
    from db.models import UserDetails  # adjust import path if needed

    def _getter() -> str:
        with session_factory() as db:
            user = db.query(UserDetails).filter(UserDetails.employee_code == employee_code).first()
            ext = getattr(user, "vbc_extension_id", None) if user else None
            if not ext:
                raise RuntimeError(f"Missing extension for {employee_code}")
            return str(ext)

    return _getter
