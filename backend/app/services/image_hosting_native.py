from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_PATH = Path("/var/lib/aimagician/artifacts/image-host-cache.json")
DEFAULT_IMGCHR_UPLOAD_URL = "https://imgchr.com/api/1/upload"
DEFAULT_IMGCHR_JSON_URL = "https://imgchr.com/json"
DEFAULT_FREEIMAGE_UPLOAD_URL = "https://freeimage.host/api/1/upload"
DEFAULT_IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"
DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
PUBLIC_URL_TIMEOUT_SECONDS = 20


def host_asset_records(assets: list[dict[str, Any]], env: dict[str, str]) -> dict[str, Any]:
    if not assets:
        return {
            "status": "missing-assets",
            "provider_chain": _configured_provider_chain(env),
            "cache_file": str(_cache_path(env)),
            "errors": [],
            "items": [],
            "hosted_count": 0,
        }

    chain = _configured_provider_chain(env)
    if not any(_provider_ready(provider, env)[0] for provider in chain):
        return {
            "status": "providers-unconfigured",
            "provider_chain": chain,
            "cache_file": str(_cache_path(env)),
            "errors": [_provider_ready(provider, env)[1] for provider in chain],
            "items": [],
            "hosted_count": 0,
        }

    cache_path = _cache_path(env)
    cache = _load_cache(cache_path)
    hosted_items: list[dict[str, Any]] = []
    errors: list[str] = []
    hosted_count = 0

    for asset in assets:
        try:
            item = _host_single_asset(asset, env, cache)
        except SystemExit as exc:
            errors.append(str(exc))
            item = {
                "status": "failed",
                "source_asset": asset,
                "direct_url": "",
                "viewer_url": "",
                "provider": "",
                "cached": False,
                "errors": [str(exc)],
            }
        hosted_items.append(item)
        if item.get("status") == "hosted" and str(item.get("direct_url", "")).strip():
            hosted_count += 1

    _save_cache(cache_path, cache)
    status = "ok" if hosted_count == len(assets) else ("partial" if hosted_count else "failed")
    return {
        "status": status,
        "provider_chain": chain,
        "cache_file": str(cache_path),
        "errors": errors,
        "items": hosted_items,
        "hosted_count": hosted_count,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _cache_path(env: dict[str, str]) -> Path:
    raw = (
        env.get("AIMAGICIAN_IMAGE_HOST_CACHE_FILE")
        or env.get("OPENCLAW_IMAGE_HOST_CACHE_FILE")
        or ""
    ).strip()
    if not raw:
        return DEFAULT_CACHE_PATH
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else WORKSPACE_ROOT / candidate


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"files": {}}
    if not isinstance(payload, dict):
        return {"files": {}}
    if not isinstance(payload.get("files"), dict):
        payload["files"] = {}
    return payload


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _multipart_body(fields: dict[str, str], *, file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----AImagicianBoundary{uuid.uuid4().hex}"
    body = bytearray()
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), boundary


def _json_request(url: str, *, data: bytes, headers: dict[str, str]) -> dict[str, Any]:
    req = request.Request(url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise SystemExit(str(exc.reason)) from exc


def _configured_provider_chain(env: dict[str, str]) -> list[str]:
    chain: list[str] = []
    for item in [
        (env.get("AIMAGICIAN_IMAGE_HOST_PRIMARY") or env.get("OPENCLAW_IMAGE_HOST_PRIMARY") or "imgchr_api").strip(),
        (env.get("AIMAGICIAN_IMAGE_HOST_SECONDARY") or env.get("OPENCLAW_IMAGE_HOST_SECONDARY") or "freeimage_api").strip(),
        (env.get("AIMAGICIAN_IMAGE_HOST_TERTIARY") or env.get("OPENCLAW_IMAGE_HOST_TERTIARY") or "imgbb_api").strip(),
    ]:
        if item and item not in chain:
            chain.append(item)
    return chain


def _probe_public_image_url(url: str) -> tuple[bool, str]:
    candidate = str(url or "").strip()
    if not candidate:
        return (False, "empty-url")
    req = request.Request(
        candidate,
        headers={"User-Agent": DEFAULT_BROWSER_UA, "Accept": "image/*,*/*;q=0.8", "Range": "bytes=0-0"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=PUBLIC_URL_TIMEOUT_SECONDS) as response:
            content_type = str(response.headers.get("Content-Type", "") or "").lower()
            status = getattr(response, "status", 200)
            if status not in {200, 206}:
                return (False, f"http-{status}")
            if not content_type.startswith("image/"):
                return (False, f"unexpected-content-type:{content_type or 'unknown'}")
            return (True, content_type)
    except error.HTTPError as exc:
        return (False, f"http-{exc.code}")
    except error.URLError as exc:
        return (False, f"urlerror:{exc.reason}")


def _url_requires_revalidation(url: str, provider: str) -> bool:
    candidate = str(url or "").strip().lower()
    if not candidate:
        return True
    if provider == "imgchr_api":
        return True
    return "/content/images/" in candidate


def _cache_entry_valid(cached_entry: dict[str, Any]) -> tuple[bool, str]:
    direct_url = str(cached_entry.get("direct_url", "") or "").strip()
    provider = str(cached_entry.get("provider", "") or "").strip()
    if not direct_url:
        return (False, "missing-direct-url")
    if "/content/images/" in direct_url.lower():
        return (False, "unstable-content-images-hotlink")
    if not _url_requires_revalidation(direct_url, provider):
        return (True, "")
    return _probe_public_image_url(direct_url)


def _validated_upload(upload: dict[str, Any]) -> dict[str, Any]:
    direct_url = str(upload.get("direct_url", "") or "").strip()
    if "/content/images/" in direct_url.lower():
        raise SystemExit(f"public-url-unstable-hotlink:{direct_url}")
    ok, reason = _probe_public_image_url(direct_url)
    if not ok:
        raise SystemExit(f"public-url-invalid:{reason}:{direct_url}")
    upload["validated_direct_url"] = direct_url
    upload["validated_at"] = _now_iso()
    return upload


def _provider_ready(provider: str, env: dict[str, str]) -> tuple[bool, str]:
    if provider == "imgchr_api":
        api_key = (env.get("IMGCHR_API_KEY", "") or "").strip()
        auth_token = (env.get("IMGCHR_AUTH_TOKEN", "") or "").strip()
        owner = (env.get("IMGCHR_OWNER", "") or "").strip()
        cookie = (env.get("IMGCHR_COOKIE", "") or "").strip()
        if api_key or (auth_token and owner and cookie):
            return (True, "")
        return (False, "missing IMGCHR_API_KEY or IMGCHR_AUTH_TOKEN/IMGCHR_OWNER/IMGCHR_COOKIE")
    if provider == "imgbb_api":
        return (bool((env.get("IMGBB_API_KEY", "") or "").strip()), "missing IMGBB_API_KEY")
    if provider == "freeimage_api":
        return (bool((env.get("FREEIMAGE_API_KEY", "") or "").strip()), "missing FREEIMAGE_API_KEY")
    return (False, f"unsupported provider: {provider}")


def _imgchr_session_headers(env: dict[str, str]) -> dict[str, str]:
    owner = (env.get("IMGCHR_OWNER", "") or "").strip()
    referer = (env.get("IMGCHR_REFERER", "") or "").strip() or (f"https://imgchr.com/{owner}" if owner else "")
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://imgchr.com",
        "Referer": referer or "https://imgchr.com/",
        "User-Agent": (env.get("IMGCHR_USER_AGENT", "") or DEFAULT_BROWSER_UA).strip(),
        "Cookie": (env.get("IMGCHR_COOKIE", "") or "").strip(),
    }


def _upload_imgchr_session(file_path: Path, env: dict[str, str]) -> dict[str, Any]:
    auth_token = (env.get("IMGCHR_AUTH_TOKEN", "") or "").strip()
    owner = (env.get("IMGCHR_OWNER", "") or "").strip()
    cookie = (env.get("IMGCHR_COOKIE", "") or "").strip()
    if not auth_token or not owner or not cookie:
        raise SystemExit("missing IMGCHR_AUTH_TOKEN/IMGCHR_OWNER/IMGCHR_COOKIE")
    body, boundary = _multipart_body(
        {"action": "upload", "type": "file", "what": (env.get("IMGCHR_UPLOAD_WHAT") or "background").strip(), "owner": owner, "auth_token": auth_token},
        file_field="source",
        file_path=file_path,
    )
    payload = _json_request(
        (env.get("IMGCHR_JSON_URL", "") or DEFAULT_IMGCHR_JSON_URL).strip(),
        data=body,
        headers={**_imgchr_session_headers(env), "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    success = payload.get("success", {}) if isinstance(payload.get("success"), dict) else {}
    image = success.get("image", {}) if isinstance(success.get("image"), dict) else {}
    direct_url = str(image.get("url") or "").strip()
    if not direct_url:
        raise SystemExit(f"imgchr_session response missing image URL: {payload}")
    return {"provider": "imgchr_api", "auth_mode": "session", "direct_url": direct_url, "viewer_url": str(image.get("url_viewer") or image.get("url") or "").strip(), "delete_url": str(image.get("delete_url") or "").strip(), "raw": payload}


def _upload_imgchr_api(file_path: Path, env: dict[str, str]) -> dict[str, Any]:
    api_key = (env.get("IMGCHR_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing IMGCHR_API_KEY")
    body, boundary = _multipart_body({"key": api_key, "action": "upload", "format": "json"}, file_field="source", file_path=file_path)
    payload = _json_request((env.get("IMGCHR_API_BASE_URL", "") or DEFAULT_IMGCHR_UPLOAD_URL).strip(), data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    image = payload.get("image", {}) if isinstance(payload.get("image"), dict) else {}
    direct_url = str(image.get("url") or image.get("display_url") or ((image.get("thumb") or {}).get("url") if isinstance(image.get("thumb"), dict) else "") or "").strip()
    if not direct_url:
        raise SystemExit(f"imgchr_api response missing image URL: {payload}")
    return {"provider": "imgchr_api", "auth_mode": "api_key", "direct_url": direct_url, "viewer_url": str(image.get("url_viewer") or "").strip(), "delete_url": str(image.get("delete_url") or "").strip(), "raw": payload}


def _upload_imgbb_api(file_path: Path, env: dict[str, str]) -> dict[str, Any]:
    api_key = (env.get("IMGBB_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing IMGBB_API_KEY")
    form = parse.urlencode({"key": api_key, "name": file_path.stem, "image": base64.b64encode(file_path.read_bytes()).decode("ascii")}).encode("utf-8")
    payload = _json_request((env.get("IMGBB_API_BASE_URL", "") or DEFAULT_IMGBB_UPLOAD_URL).strip(), data=form, headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    direct_url = str(data.get("url") or data.get("display_url") or "").strip()
    if not direct_url:
        raise SystemExit(f"imgbb_api response missing image URL: {payload}")
    return {"provider": "imgbb_api", "direct_url": direct_url, "viewer_url": str(data.get("url_viewer") or "").strip(), "delete_url": str(data.get("delete_url") or "").strip(), "raw": payload}


def _upload_freeimage_api(file_path: Path, env: dict[str, str]) -> dict[str, Any]:
    api_key = (env.get("FREEIMAGE_API_KEY", "") or "").strip()
    if not api_key:
        raise SystemExit("missing FREEIMAGE_API_KEY")
    body, boundary = _multipart_body({"key": api_key, "action": "upload", "format": "json"}, file_field="source", file_path=file_path)
    payload = _json_request((env.get("FREEIMAGE_API_BASE_URL", "") or DEFAULT_FREEIMAGE_UPLOAD_URL).strip(), data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    image = payload.get("image", {}) if isinstance(payload.get("image"), dict) else {}
    direct_url = str(image.get("url") or image.get("display_url") or ((image.get("thumb") or {}).get("url") if isinstance(image.get("thumb"), dict) else "") or "").strip()
    if not direct_url:
        raise SystemExit(f"freeimage_api response missing image URL: {payload}")
    return {"provider": "freeimage_api", "direct_url": direct_url, "viewer_url": str(image.get("url_viewer") or "").strip(), "delete_url": str(image.get("delete_url") or "").strip(), "raw": payload}


def _upload_file(file_path: Path, env: dict[str, str]) -> dict[str, Any]:
    errors: list[str] = []
    for provider in _configured_provider_chain(env):
        for attempt in range(1, 3):
            ready, reason = _provider_ready(provider, env)
            if not ready:
                errors.append(f"{provider}: {reason}")
                break
            try:
                if provider == "imgchr_api":
                    return _validated_upload(_upload_imgchr_api(file_path, env) if (env.get("IMGCHR_API_KEY", "") or "").strip() else _upload_imgchr_session(file_path, env))
                if provider == "imgbb_api":
                    return _validated_upload(_upload_imgbb_api(file_path, env))
                if provider == "freeimage_api":
                    return _validated_upload(_upload_freeimage_api(file_path, env))
                errors.append(f"{provider}: unsupported provider")
            except SystemExit as exc:
                errors.append(f"{provider}: attempt {attempt}: {exc}")
                if attempt < 2:
                    time.sleep(3)
    raise SystemExit(" | ".join(errors) if errors else "no image host providers configured")


def _host_single_asset(asset: dict[str, Any], env: dict[str, str], cache: dict[str, Any]) -> dict[str, Any]:
    path_raw = str(asset.get("path", "") or "").strip()
    direct_url = str(asset.get("url") or asset.get("direct_url") or "").strip()
    viewer_url = str(asset.get("viewer_url") or "").strip()
    if direct_url and not path_raw:
        ok, reason = _probe_public_image_url(direct_url)
        if not ok:
            return {"status": "invalid-external-url", "source_asset": asset, "direct_url": "", "viewer_url": viewer_url, "provider": "external_url", "cached": False, "errors": [reason]}
        return {"status": "hosted", "source_asset": asset, "direct_url": direct_url, "viewer_url": viewer_url or direct_url, "provider": "external_url", "cached": True, "errors": []}
    if not path_raw:
        return {"status": "missing-path", "source_asset": asset, "direct_url": "", "viewer_url": "", "provider": "", "cached": False, "errors": []}
    file_path = Path(path_raw)
    if not file_path.exists():
        return {"status": "missing-file", "source_asset": asset, "direct_url": "", "viewer_url": "", "provider": "", "cached": False, "errors": [f"file not found: {file_path}"]}

    digest = _file_digest(file_path)
    cached_entry = cache.get("files", {}).get(digest, {})
    if isinstance(cached_entry, dict) and str(cached_entry.get("direct_url", "")).strip():
        cache_ok, _cache_reason = _cache_entry_valid(cached_entry)
        if cache_ok:
            return {"status": "hosted", "source_asset": asset, "direct_url": str(cached_entry.get("direct_url", "")).strip(), "viewer_url": str(cached_entry.get("viewer_url", "")).strip(), "provider": str(cached_entry.get("provider", "")).strip(), "cached": True, "errors": [], "digest": digest}
        cache.get("files", {}).pop(digest, None)

    upload = _upload_file(file_path, env)
    cache.setdefault("files", {})[digest] = {
        "provider": upload["provider"],
        "auth_mode": upload.get("auth_mode", ""),
        "direct_url": upload["direct_url"],
        "viewer_url": upload["viewer_url"],
        "delete_url": upload.get("delete_url", ""),
        "filename": file_path.name,
        "source_path": str(file_path),
        "updated_at": _now_iso(),
        "validated_at": upload.get("validated_at", ""),
    }
    return {"status": "hosted", "source_asset": asset, "direct_url": upload["direct_url"], "viewer_url": upload["viewer_url"], "provider": upload["provider"], "cached": False, "errors": [], "digest": digest}
