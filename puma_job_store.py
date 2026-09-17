from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any


_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class JobStore:
    """Local job files with an optional S3-compatible durable mirror.

    The local directory remains the runtime working set. When all PUMA_S3_*
    credentials are present, status/input/output files are mirrored to S3/R2
    and can be restored after an ephemeral-container restart.
    """

    def __init__(self, base_dir: Path, *, client: Any | None = None, env: dict[str, str] | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        cfg = os.environ if env is None else env
        self.bucket = (cfg.get("PUMA_S3_BUCKET") or "").strip()
        self.endpoint = (cfg.get("PUMA_S3_ENDPOINT") or "").strip()
        self.access_key = (cfg.get("PUMA_S3_ACCESS_KEY_ID") or "").strip()
        self.secret_key = (cfg.get("PUMA_S3_SECRET_ACCESS_KEY") or "").strip()
        self.region = (cfg.get("PUMA_S3_REGION") or "auto").strip() or "auto"
        self.prefix = (cfg.get("PUMA_S3_PREFIX") or "jobs").strip(" /") or "jobs"
        try:
            self.status_sync_seconds = max(0.0, float(cfg.get("PUMA_S3_STATUS_SYNC_SECONDS") or "5"))
        except ValueError:
            self.status_sync_seconds = 5.0
        self.enabled = bool(self.bucket and self.endpoint and self.access_key and self.secret_key)
        self._client = client
        self._last_status_sync: dict[str, float] = {}
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def mode(self) -> str:
        return "s3" if self.enabled else "local"

    def _s3(self):
        if not self.enabled:
            return None
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._client

    def _valid_job_id(self, job_id: str) -> str:
        value = str(job_id or "")
        if not _SAFE_JOB_ID.fullmatch(value):
            raise ValueError("invalid job id")
        return value

    def _key(self, job_id: str, filename: str) -> str:
        jid = self._valid_job_id(job_id)
        name = Path(filename).name
        if not name or name in {".", ".."}:
            raise ValueError("invalid filename")
        return f"{self.prefix}/{jid}/{name}"

    def local_path(self, job_id: str, filename: str) -> Path:
        return self.base_dir / self._valid_job_id(job_id) / Path(filename).name

    def upload_file(self, job_id: str, path: Path, *, remote_name: str | None = None) -> bool:
        if not self.enabled:
            return False
        source = Path(path)
        if not source.is_file():
            return False
        try:
            key = self._key(job_id, remote_name or source.name)
            with source.open("rb") as fh:
                self._s3().put_object(Bucket=self.bucket, Key=key, Body=fh)
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def ensure_file(self, job_id: str, filename: str) -> Path | None:
        destination = self.local_path(job_id, filename)
        if destination.is_file():
            return destination
        if not self.enabled:
            return None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            response = self._s3().get_object(Bucket=self.bucket, Key=self._key(job_id, filename))
            tmp = destination.with_suffix(destination.suffix + ".restore")
            with tmp.open("wb") as fh:
                shutil.copyfileobj(response["Body"], fh)
            os.replace(tmp, destination)
            self.last_error = None
            return destination
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return None

    def save_status(self, job_id: str, snapshot: dict[str, Any], *, force: bool = False) -> bool:
        if not self.enabled:
            return False
        now = time.monotonic()
        with self._lock:
            last = self._last_status_sync.get(job_id, 0.0)
            if not force and now - last < self.status_sync_seconds:
                return False
            self._last_status_sync[job_id] = now
        try:
            body = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
            self._s3().put_object(
                Bucket=self.bucket,
                Key=self._key(job_id, "status.json"),
                Body=body,
                ContentType="application/json; charset=utf-8",
            )
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def load_status(self, job_id: str) -> dict[str, Any] | None:
        local = self.local_path(job_id, "status.json")
        if local.is_file():
            try:
                return json.loads(local.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not self.enabled:
            return None
        try:
            response = self._s3().get_object(Bucket=self.bucket, Key=self._key(job_id, "status.json"))
            data = json.loads(response["Body"].read().decode("utf-8"))
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp = local.with_suffix(".json.restore")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, local)
            self.last_error = None
            return data
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def list_remote_job_ids(self) -> list[str]:
        if not self.enabled:
            return []
        prefix = f"{self.prefix}/"
        token: str | None = None
        found: set[str] = set()
        try:
            while True:
                kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
                if token:
                    kwargs["ContinuationToken"] = token
                response = self._s3().list_objects_v2(**kwargs)
                for item in response.get("Contents") or []:
                    key = str(item.get("Key") or "")
                    if not key.endswith("/status.json"):
                        continue
                    rest = key[len(prefix):]
                    job_id = rest.split("/", 1)[0]
                    if _SAFE_JOB_ID.fullmatch(job_id):
                        found.add(job_id)
                if not response.get("IsTruncated"):
                    break
                token = response.get("NextContinuationToken")
                if not token:
                    break
            self.last_error = None
            return sorted(found)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
