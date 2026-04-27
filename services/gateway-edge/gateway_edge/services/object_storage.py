from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
from urllib.parse import quote, urlencode, urlparse

import httpx


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _amz_date(now: datetime) -> tuple[str, str]:
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    object_key: str
    size_bytes: int
    sha256: str
    content_type: str | None


class MinioObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        force_path_style: bool = True,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = "us-east-1" if region == "auto" else region
        self._force_path_style = force_path_style
        parsed = urlparse(self._endpoint)
        self._scheme = parsed.scheme or "http"
        self._host = parsed.netloc

    async def put_object(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        now = datetime.now(UTC)
        amz_datetime, datestamp = _amz_date(now)
        canonical_uri = self._canonical_uri(object_key)
        payload_hash = _sha256_hex(payload)
        canonical_headers = (
            f"host:{self._host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_datetime}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = (
            "PUT\n"
            f"{canonical_uri}\n\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )
        scope = f"{datestamp}/{self._region}/s3/aws4_request"
        string_to_sign = (
            "AWS4-HMAC-SHA256\n"
            f"{amz_datetime}\n"
            f"{scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        signing_key = self._signing_key(datestamp)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {
            "host": self._host,
            "x-amz-date": amz_datetime,
            "x-amz-content-sha256": payload_hash,
            "Authorization": (
                "AWS4-HMAC-SHA256 "
                f"Credential={self._access_key}/{scope}, "
                f"SignedHeaders={signed_headers}, "
                f"Signature={signature}"
            ),
        }
        if content_type:
            headers["Content-Type"] = content_type
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.put(
                f"{self._endpoint}{canonical_uri}",
                content=payload,
                headers=headers,
            )
            response.raise_for_status()
        return StoredObject(
            bucket=self._bucket,
            object_key=object_key,
            size_bytes=len(payload),
            sha256=payload_hash,
            content_type=content_type,
        )

    async def get_object(self, *, object_key: str) -> bytes:
        url = self.presign_get(object_key=object_key)
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    def presign_get(self, *, object_key: str, expires_seconds: int = 900) -> str:
        now = datetime.now(UTC)
        amz_datetime, datestamp = _amz_date(now)
        canonical_uri = self._canonical_uri(object_key)
        scope = f"{datestamp}/{self._region}/s3/aws4_request"
        params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self._access_key}/{scope}",
            "X-Amz-Date": amz_datetime,
            "X-Amz-Expires": str(expires_seconds),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_query = urlencode(sorted(params.items()))
        canonical_request = (
            "GET\n"
            f"{canonical_uri}\n"
            f"{canonical_query}\n"
            f"host:{self._host}\n\n"
            "host\n"
            "UNSIGNED-PAYLOAD"
        )
        string_to_sign = (
            "AWS4-HMAC-SHA256\n"
            f"{amz_datetime}\n"
            f"{scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        signature = hmac.new(
            self._signing_key(datestamp),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["X-Amz-Signature"] = signature
        return f"{self._endpoint}{canonical_uri}?{urlencode(sorted(params.items()))}"

    def _canonical_uri(self, object_key: str) -> str:
        quoted_key = quote(object_key.lstrip("/"), safe="/-_.~")
        if self._force_path_style:
            return f"/{self._bucket}/{quoted_key}"
        return f"/{quoted_key}"

    def _signing_key(self, datestamp: str) -> bytes:
        k_date = _sign(f"AWS4{self._secret_key}".encode("utf-8"), datestamp)
        k_region = _sign(k_date, self._region)
        k_service = _sign(k_region, "s3")
        return _sign(k_service, "aws4_request")
