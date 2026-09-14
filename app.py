import csv
import json
import os
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from priceintel.runner import run_analysis

BASE = Path(__file__).resolve().parent
JOBS_DIR = BASE / "data" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"csv"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "120"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

_jobs = {}
_lock = threading.Lock()


def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def set_job(job_id, **kwargs):
    with _lock:
        _jobs.setdefault(job_id, {}).update(kwargs)
        snapshot = dict(_jobs[job_id])
    try:
        (JOBS_DIR / job_id / "status.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def get_job(job_id):
    with _lock:
        if job_id in _jobs:
            return dict(_jobs[job_id])
    p = JOBS_DIR / job_id / "status.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def worker(job_id, input_path, limit, selected_markets):
    job_dir = JOBS_DIR / job_id
    results_path = job_dir / "market_analysis.csv"
    offers_path = job_dir / "market_analysis_offers.csv"

    def progress(current, total, name, extra=None):
        pct = round(current / total * 100, 1) if total else 0
        set_job(job_id, status="running", current=current, total=total,
                percent=pct, current_product=name, message=extra or "Аналізуємо ринок…")

    try:
        set_job(job_id, status="running", message="Читаємо каталог…", started_at=time.time())
        summary = run_analysis(
            str(input_path),
            str(results_path),
            str(offers_path),
            limit=limit,
            marketplaces=selected_markets,
            progress_cb=progress,
        )
        set_job(job_id, status="done", percent=100, message="Готово",
                finished_at=time.time(), summary=summary,
                results_file=str(results_path), offers_file=str(offers_path))
    except Exception as e:
        set_job(job_id, status="error", message=str(e), finished_at=time.time())


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

    set_job(job_id, id=job_id, status="queued", percent=0, current=0, total=0,
            message="Задача поставлена в чергу", filename=filename,
            marketplaces=selected, limit=limit, created_at=time.time())

    t = threading.Thread(target=worker, args=(job_id, input_path, limit, selected), daemon=True)
    t.start()
    return render_template("job.html", job_id=job_id)


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = get_job(job_id)
    if not job:
        abort(404)
    safe = {k: v for k, v in job.items() if k not in {"results_file", "offers_file"}}
    if job.get("status") == "done":
        safe["results_url"] = url_for("download_results", job_id=job_id)
        safe["offers_url"] = url_for("download_offers", job_id=job_id)
        safe["preview_url"] = url_for("preview", job_id=job_id)
    return jsonify(safe)


@app.get("/jobs/<job_id>/preview")
def preview(job_id):
    job = get_job(job_id)
    if not job or job.get("status") != "done":
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


@app.get("/jobs/<job_id>/results")
def download_results(job_id):
    job = get_job(job_id)
    if not job or job.get("status") != "done": abort(404)
    return send_file(job["results_file"], as_attachment=True, download_name="market_analysis.csv")


@app.get("/jobs/<job_id>/offers")
def download_offers(job_id):
    job = get_job(job_id)
    if not job or job.get("status") != "done": abort(404)
    p = Path(job["offers_file"])
    if not p.exists():
        p.write_text("Код товара;Артикул;Маркетплейс;Название конкурента;Цена конкурента;Match %;URL\n", encoding="utf-8-sig")
    return send_file(p, as_attachment=True, download_name="market_analysis_offers.csv")


@app.errorhandler(413)
def too_large(_):
    return render_template("error.html", message=f"Файл завеликий. Ліміт сервера: {MAX_UPLOAD_MB} МБ."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
