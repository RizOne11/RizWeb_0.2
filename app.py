import csv
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from priceintel.runner import run_analysis
from priceintel.report_xlsx import build_xlsx

BASE = Path(__file__).resolve().parent
JOBS_DIR = BASE / "data" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"csv"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "120"))

app = Flask(__name__)
print("[PRICEINTEL] Serper API key configured:", bool(os.getenv("SERPER_API_KEY")), flush=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

_jobs = {}
_lock = threading.Lock()
_running_threads = set()


def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def set_job(job_id, **kwargs):
    with _lock:
        _jobs.setdefault(job_id, {}).update(kwargs)
        snapshot = dict(_jobs[job_id])
    try:
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        tmp = job_dir / "status.json.tmp"
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, job_dir / "status.json")
    except Exception:
        pass


def get_job(job_id):
    with _lock:
        if job_id in _jobs:
            return dict(_jobs[job_id])
    p = JOBS_DIR / job_id / "status.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            with _lock:
                _jobs[job_id] = dict(data)
            return data
        except Exception:
            return None
    return None


def _load_previous_jobs():
    for p in JOBS_DIR.glob("*/status.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            job_id = data.get("id") or p.parent.name
            # After process restart there is no thread left to own a stale running job.
            if data.get("status") in {"queued", "running"}:
                data["status"] = "interrupted"
                data["message"] = "Попередній процес перервався. Можна продовжити з checkpoint."
                data["resume_available"] = (p.parent / "checkpoint.json").exists()
            with _lock:
                _jobs[job_id] = data
            if data.get("status") == "interrupted":
                set_job(job_id, **data)
        except Exception:
            continue


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _job_fingerprint(input_path, supplier, selected_markets, limit):
    raw = "|".join([
        _file_sha256(input_path),
        supplier.strip().lower(),
        ",".join(sorted(selected_markets)),
        str(limit),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _find_active_duplicate(fingerprint):
    with _lock:
        items = list(_jobs.items())
    for job_id, job in items:
        if job.get("fingerprint") == fingerprint and job.get("status") in {"queued", "running"}:
            return job_id
    return None


def _thread_alive(job_id):
    with _lock:
        return job_id in _running_threads


def worker(job_id, input_path, limit, selected_markets, supplier):
    with _lock:
        if job_id in _running_threads:
            return
        _running_threads.add(job_id)

    def log(message):
        print(f"[PRICEINTEL {job_id}] {message}", flush=True)

    job_dir = JOBS_DIR / job_id
    results_path = job_dir / "market_analysis.csv"
    offers_path = job_dir / "market_analysis_offers.csv"
    xlsx_path = job_dir / "market_analysis.xlsx"
    checkpoint_path = job_dir / "checkpoint.json"

    def progress(current, total, name, extra=None):
        pct = round(current / total * 100, 1) if total else 0
        set_job(
            job_id,
            status="running",
            current=current,
            total=total,
            percent=pct,
            current_product=name,
            message=extra or "Аналізуємо ринок…",
            resume_available=True,
        )

    try:
        existing = get_job(job_id) or {}
        set_job(
            job_id,
            status="running",
            message="Читаємо каталог…",
            started_at=existing.get("started_at") or time.time(),
            resumed_at=time.time() if checkpoint_path.exists() else None,
            resume_available=True,
            cancel_requested=False,
        )

        def cancel_requested():
            job = get_job(job_id) or {}
            return bool(job.get("cancel_requested"))

        summary = run_analysis(
            str(input_path),
            str(results_path),
            str(offers_path),
            limit=limit,
            marketplaces=selected_markets,
            progress_cb=progress,
            log_cb=log,
            cancel_cb=cancel_requested,
            supplier=supplier,
            checkpoint_path=str(checkpoint_path),
        )
        build_xlsx(str(results_path), str(xlsx_path))
        if summary.get("canceled"):
            set_job(
                job_id,
                status="canceled",
                message="Аналіз зупинено. Можна продовжити з останнього checkpoint.",
                finished_at=time.time(),
                summary=summary,
                results_file=str(results_path),
                offers_file=str(offers_path),
                xlsx_file=str(xlsx_path),
                resume_available=checkpoint_path.exists(),
            )
        else:
            set_job(
                job_id,
                status="done",
                percent=100,
                message="Готово",
                finished_at=time.time(),
                summary=summary,
                results_file=str(results_path),
                offers_file=str(offers_path),
                xlsx_file=str(xlsx_path),
                resume_available=False,
            )
    except Exception as e:
        log(f"FATAL {type(e).__name__}: {e}")
        set_job(
            job_id,
            status="error",
            message=str(e),
            finished_at=time.time(),
            resume_available=checkpoint_path.exists(),
        )
    finally:
        with _lock:
            _running_threads.discard(job_id)


def _start_worker(job_id):
    job = get_job(job_id)
    if not job:
        return False
    if _thread_alive(job_id):
        return False
    input_path = JOBS_DIR / job_id / job["filename"]
    if not input_path.exists():
        return False
    t = threading.Thread(
        target=worker,
        args=(job_id, input_path, int(job["limit"]), list(job["marketplaces"]), job["supplier"]),
        daemon=True,
    )
    t.start()
    return True


_load_previous_jobs()


@app.get("/")
def index():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    return render_template("index.html", marketplaces=cfg["marketplaces"])


@app.post("/analyze")
def analyze():
    f = request.files.get("catalog")
    if not f or not f.filename:
        return render_template("error.html", message="Не вибрано CSV-файл."), 400
    if not allowed_file(f.filename):
        return render_template("error.html", message="Поки підтримується CSV."), 400

    supplier = (request.form.get("supplier") or "").strip()
    if not supplier:
        supplier = Path(f.filename).stem or "Не вказано"

    raw_limit = (request.form.get("limit") or "30").strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 30
    limit = max(1, min(limit, int(os.getenv("MAX_PRODUCTS_PER_JOB", "5000"))))

    selected = request.form.getlist("marketplaces")
    if not selected:
        cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        selected = [m["name"] for m in cfg["marketplaces"]]

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(f.filename) or "catalog.csv"
    input_path = job_dir / filename
    f.save(input_path)

    fingerprint = _job_fingerprint(input_path, supplier, selected, limit)
    duplicate_id = _find_active_duplicate(fingerprint)
    if duplicate_id:
        shutil.rmtree(job_dir, ignore_errors=True)
        return redirect(url_for("job_page", job_id=duplicate_id), code=303)

    set_job(
        job_id,
        id=job_id,
        status="queued",
        percent=0,
        current=0,
        total=0,
        message="Задача поставлена в чергу",
        filename=filename,
        supplier=supplier,
        marketplaces=selected,
        limit=limit,
        fingerprint=fingerprint,
        created_at=time.time(),
        resume_available=False,
    )
    _start_worker(job_id)

    # POST/Redirect/GET: F5 is now safe and cannot resubmit the catalog form.
    return redirect(url_for("job_page", job_id=job_id), code=303)


@app.get("/jobs/<job_id>")
def job_page(job_id):
    if not get_job(job_id):
        abort(404)
    return render_template("job.html", job_id=job_id)


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = get_job(job_id)
    if not job:
        abort(404)
    safe = {k: v for k, v in job.items() if k not in {"results_file", "offers_file", "xlsx_file", "fingerprint"}}
    safe["resume_available"] = bool(job.get("resume_available"))
    if job.get("status") in {"done", "canceled"}:
        if job.get("results_file"):
            safe["results_url"] = url_for("download_results", job_id=job_id)
            safe["offers_url"] = url_for("download_offers", job_id=job_id)
            safe["xlsx_url"] = url_for("download_xlsx", job_id=job_id)
            safe["preview_url"] = url_for("preview", job_id=job_id)
    return jsonify(safe)


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id):
    job = get_job(job_id)
    if not job:
        abort(404)
    if job.get("status") in {"done", "error", "canceled", "interrupted"}:
        return jsonify({"ok": False, "status": job.get("status")})
    set_job(job_id, cancel_requested=True, message="Зупиняємо аналіз…")
    return jsonify({"ok": True, "status": "cancel_requested"})


@app.post("/api/jobs/<job_id>/resume")
def resume_job(job_id):
    job = get_job(job_id)
    if not job:
        abort(404)
    if job.get("status") in {"queued", "running"} or _thread_alive(job_id):
        return jsonify({"ok": False, "status": job.get("status"), "message": "Job already running"}), 409
    checkpoint = JOBS_DIR / job_id / "checkpoint.json"
    if not checkpoint.exists():
        return jsonify({"ok": False, "message": "Checkpoint not found"}), 409
    set_job(job_id, status="queued", message="Відновлюємо аналіз з checkpoint…", cancel_requested=False)
    if not _start_worker(job_id):
        return jsonify({"ok": False, "message": "Не вдалося запустити worker"}), 500
    return jsonify({"ok": True, "status": "queued"})


@app.get("/jobs/<job_id>/preview")
def preview(job_id):
    job = get_job(job_id)
    if not job or job.get("status") not in {"done", "canceled"} or not job.get("results_file"):
        abort(404)
    path = Path(job["results_file"])
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for i, row in enumerate(reader):
            rows.append(row)
            if i >= 199:
                break
    return render_template("preview.html", job=job, rows=rows)


@app.get("/jobs/<job_id>/xlsx")
def download_xlsx(job_id):
    job = get_job(job_id)
    if not job or job.get("status") not in {"done", "canceled"}:
        abort(404)
    p = Path(job.get("xlsx_file") or "")
    if not p.exists():
        p = JOBS_DIR / job_id / "market_analysis.xlsx"
        build_xlsx(job["results_file"], str(p))
    return send_file(p, as_attachment=True, download_name="PriceIntel_market_report.xlsx")


@app.get("/jobs/<job_id>/results")
def download_results(job_id):
    job = get_job(job_id)
    if not job or job.get("status") not in {"done", "canceled"}:
        abort(404)
    return send_file(job["results_file"], as_attachment=True, download_name="market_analysis.csv")


@app.get("/jobs/<job_id>/offers")
def download_offers(job_id):
    job = get_job(job_id)
    if not job or job.get("status") not in {"done", "canceled"}:
        abort(404)
    p = Path(job["offers_file"])
    if not p.exists():
        p.write_text(
            "Код товара;Категория;Постачальник;Артикул;Маркетплейс;Название конкурента;"
            "Цена конкурента;Источник цены;Match %;URL\n",
            encoding="utf-8-sig",
        )
    return send_file(p, as_attachment=True, download_name="market_analysis_offers.csv")


@app.errorhandler(413)
def too_large(_):
    return render_template("error.html", message=f"Файл завеликий. Ліміт сервера: {MAX_UPLOAD_MB} МБ."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
