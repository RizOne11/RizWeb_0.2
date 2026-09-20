import io
import json
from pathlib import Path

from puma_job_store import JobStore


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        data = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.objects[(Bucket, Key)] = data
        return {"ETag": "fake"}

    def get_object(self, Bucket, Key):
        key = (Bucket, Key)
        if key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[key])}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000, ContinuationToken=None):
        contents = [
            {"Key": key}
            for (bucket, key), _ in sorted(self.objects.items())
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}


def _env():
    return {
        "PUMA_S3_BUCKET": "puma-tests",
        "PUMA_S3_ENDPOINT": "https://example.r2.cloudflarestorage.com",
        "PUMA_S3_ACCESS_KEY_ID": "test-key",
        "PUMA_S3_SECRET_ACCESS_KEY": "test-secret",
        "PUMA_S3_PREFIX": "jobs",
        "PUMA_S3_STATUS_SYNC_SECONDS": "0",
    }


def test_store_is_local_only_without_complete_credentials(tmp_path):
    store = JobStore(tmp_path, env={})
    assert store.mode == "local"
    assert store.enabled is False
    assert store.list_remote_job_ids() == []


def test_s3_store_round_trips_job_files_and_status(tmp_path):
    fake = FakeS3()
    store = JobStore(tmp_path, client=fake, env=_env())
    assert store.mode == "s3"

    job_id = "abc123def456"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    input_file = job_dir / "catalog.xlsx"
    input_file.write_bytes(b"catalog-bytes")

    assert store.upload_file(job_id, input_file)
    input_file.unlink()
    restored = store.ensure_file(job_id, "catalog.xlsx")
    assert restored == input_file
    assert restored.read_bytes() == b"catalog-bytes"

    status = {"id": job_id, "status": "done", "filename": "catalog.xlsx"}
    assert store.save_status(job_id, status, force=True)
    local_status = job_dir / "status.json"
    local_status.unlink(missing_ok=True)
    loaded = store.load_status(job_id)
    assert loaded == status
    assert json.loads(local_status.read_text(encoding="utf-8")) == status
    assert store.list_remote_job_ids() == [job_id]


def test_store_rejects_path_traversal_job_ids(tmp_path):
    store = JobStore(tmp_path, client=FakeS3(), env=_env())
    try:
        store.local_path("../oops", "status.json")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal job id must be rejected")



def test_remote_status_read_bypasses_stale_local_copy(tmp_path):
    fake = FakeS3()
    store = JobStore(tmp_path, client=fake, env=_env())
    job_id = "fresh123"

    local = store.local_path(job_id, "status.json")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({"id": job_id, "status": "queued"}), encoding="utf-8")

    fake.put_object(
        Bucket=store.bucket,
        Key=store._key(job_id, "status.json"),
        Body=json.dumps({"id": job_id, "status": "done"}).encode("utf-8"),
    )

    assert store.load_status(job_id)["status"] == "queued"
    assert store.load_remote_status(job_id)["status"] == "done"
    assert json.loads(local.read_text(encoding="utf-8"))["status"] == "done"
