import csv
import hashlib
import hmac
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from priceintel.io import read_catalog
from puma_scouts.production import run_sync

BASE = Path(__file__).resolve().parent
JOBS_DIR = BASE / "data" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_ANALYSIS_EXTENSIONS = {"xlsx","csv","yml","xml"}
ALLOWED_CONTENT_EXTENSIONS = {"csv", "yml", "xml"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "120"))
ENGINE_BUILD = (os.getenv("RENDER_GIT_COMMIT") or "dev")[:12]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


def _env_flag(name, default="0"):
    return os.getenv(name, default).strip().casefold() in {"1", "true", "yes", "on"}


def _auth_token():
    return os.getenv("PUMA_AUTH_TOKEN", "").strip()


def _auth_user():
    return os.getenv("PUMA_AUTH_USER", "puma").strip() or "puma"


def _auth_required():
    return _env_flag("PUMA_REQUIRE_AUTH") or bool(_auth_token())


def _request_token():
    header = (request.headers.get("Authorization") or "").strip()
    if header.casefold().startswith("bearer "):
        return header[7:].strip()

    basic = request.authorization
    if basic and (basic.type or "").casefold() == "basic":
        expected_user = _auth_user()
        if hmac.compare_digest(str(basic.username or ""), expected_user):
            return str(basic.password or "")

    return (request.headers.get("X-PUMA-Token") or "").strip()


def _unauthorized_response():
    if request.path.startswith("/api/"):
        response = jsonify({"ok": False, "error": "authentication_required"})
    else:
        response = Response("Authentication required", status=401, mimetype="text/plain")
    response.status_code = 401
    response.headers["WWW-Authenticate"] = 'Basic realm="PUMA", charset="UTF-8"'
    response.headers["Cache-Control"] = "no-store"
    return response


@app.before_request
def require_auth():
    if request.endpoint == "static" or request.path == "/healthz":
        return None
    if not _auth_required():
        return None

    expected = _auth_token()
    if not expected:
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "auth_not_configured"}), 503
        return Response("Authentication is required but not configured.", status=503, mimetype="text/plain")

    supplied = _request_token()
    if supplied and hmac.compare_digest(supplied, expected):
        return None
    return _unauthorized_response()
_jobs = {}
_lock = threading.Lock()
_running_threads = set()

def allowed_file(name, allowed): return "." in name and name.rsplit(".",1)[1].lower() in allowed

def set_job(job_id, **kwargs):
    with _lock:
        _jobs.setdefault(job_id,{}).update(kwargs); snapshot=dict(_jobs[job_id])
    try:
        d=JOBS_DIR/job_id; d.mkdir(parents=True,exist_ok=True); tmp=d/"status.json.tmp"; tmp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding="utf-8"); os.replace(tmp,d/"status.json")
    except Exception: pass

def get_job(job_id):
    with _lock:
        if job_id in _jobs:return dict(_jobs[job_id])
    p=JOBS_DIR/job_id/"status.json"
    if p.exists():
        try:
            data=json.loads(p.read_text(encoding="utf-8"));
            with _lock:_jobs[job_id]=dict(data)
            return data
        except Exception:return None
    return None

def _load_previous_jobs():
    for p in JOBS_DIR.glob("*/status.json"):
        try:
            data=json.loads(p.read_text(encoding="utf-8"));jid=data.get("id") or p.parent.name
            if data.get("status") in {"queued","running"}:
                checkpoint=p.parent/"checkpoint.json"
                data["status"]="interrupted"
                data["resume_available"]=checkpoint.exists() and (data.get("engine_build") or ENGINE_BUILD)==ENGINE_BUILD
                data["message"]="Попередній процес перервався. Можна продовжити з останньої контрольної точки." if data["resume_available"] else "Попередній процес перервався. Запусти аналіз повторно."
            with _lock:_jobs[jid]=data
        except Exception:continue

def _file_sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def _job_fingerprint(path,supplier,markets,limit):return hashlib.sha256("|".join([_file_sha256(path),supplier.strip().lower(),",".join(sorted(markets)),str(limit)]).encode()).hexdigest()
def _find_active_duplicate(fp):
    with _lock:items=list(_jobs.items())
    return next((jid for jid,j in items if j.get("fingerprint")==fp and j.get("status") in {"queued","running"}),None)
def _thread_alive(jid):
    with _lock:return jid in _running_threads

def worker(job_id,input_path,limit,selected_markets,supplier):
    with _lock:
        if job_id in _running_threads:return
        _running_threads.add(job_id)
    d=JOBS_DIR/job_id
    xlsx=d/"PUMA_doPUMAgatel_market_report.xlsx"
    classic_xlsx=d/"PUMA_classic_analytical_report.xlsx"
    checkpoint=d/"checkpoint.json"
    def progress(current,total,name,extra=None):
        set_job(
            job_id,status="running",current=current,total=total,
            percent=round(current/max(1,total)*100,1),current_product=name,
            message=extra or "Аналізуємо ринок…",
            resume_available=checkpoint.exists(),
        )
    try:
        previous=get_job(job_id) or {}
        same_build=(previous.get("engine_build") or ENGINE_BUILD)==ENGINE_BUILD
        resuming=checkpoint.exists() and same_build
        started_at=previous.get("started_at") or time.time()
        resume_count=int(previous.get("resume_count") or 0)+(1 if resuming else 0)
        set_job(
            job_id,status="running",
            message="Відновлюємо аналіз з контрольної точки…" if resuming else "Читаємо каталог…",
            started_at=started_at,resumed_at=time.time() if resuming else previous.get("resumed_at"),
            resume_count=resume_count,resume_available=resuming,engine_build=ENGINE_BUILD,
        )
        summary=run_sync(
            str(input_path),str(xlsx),limit=limit,selected=selected_markets,
            progress_cb=progress,classic_output_path=str(classic_xlsx),supplier=supplier,
            checkpoint_path=str(checkpoint),checkpoint_token=ENGINE_BUILD,
        )
        set_job(
            job_id,status="done",percent=100,message="Готово",finished_at=time.time(),
            summary=summary,xlsx_file=str(xlsx),classic_xlsx_file=str(classic_xlsx),
            resume_available=False,engine_build=ENGINE_BUILD,
        )
        checkpoint.unlink(missing_ok=True)
    except Exception as e:
        set_job(
            job_id,status="error",message=f"{type(e).__name__}: {e}",finished_at=time.time(),
            resume_available=checkpoint.exists(),engine_build=ENGINE_BUILD,
        )
    finally:
        with _lock:_running_threads.discard(job_id)

def _start_worker(jid):
    j=get_job(jid)
    if not j or _thread_alive(jid):return False
    p=JOBS_DIR/jid/j["filename"]
    if not p.exists():return False
    threading.Thread(target=worker,args=(jid,p,int(j["limit"]),list(j["marketplaces"]),j["supplier"]),daemon=True).start();return True
_load_previous_jobs()
def _ui_cfg():return json.loads((BASE/"config.json").read_text(encoding="utf-8"))
@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "puma", "engine_build": ENGINE_BUILD})

@app.get("/")
def index():
    c=_ui_cfg();return render_template("index.html",app_name=c.get("app_name","PUMA Platform"),app_version=c.get("app_version","v1.3"),brand_line=c.get("brand_line","Made by Пума (Чернявський А.)"))
@app.get("/analysis")
def analysis_page():
    c=_ui_cfg();return render_template("analysis.html",marketplaces=c.get("marketplaces",[]),app_name=c.get("app_name","PUMA Platform"),app_version="v1.3",brand_line=c.get("brand_line","Made by Пума (Чернявський А.)"))
@app.get("/content")
def content_page():
    c=_ui_cfg();return render_template("content.html",app_name=c.get("app_name","PUMA Platform"),app_version=c.get("app_version","v1.1"),brand_line=c.get("brand_line","Made by Пума (Чернявський А.)"))
@app.post("/content/preview")
def content_preview():
    f=request.files.get("catalog")
    if not f or not f.filename:return render_template("error.html",message="Не вибрано YML/CSV-файл."),400
    if not allowed_file(f.filename,ALLOWED_CONTENT_EXTENSIONS):return render_template("error.html",message="Для контенту підтримуються YML, XML та CSV."),400
    supplier=(request.form.get("supplier") or "Hubber").strip() or "Hubber"
    try:limit=max(1,min(int(request.form.get("limit") or 20),200))
    except ValueError:limit=20
    d=JOBS_DIR/("content_"+uuid.uuid4().hex[:12]);d.mkdir(parents=True,exist_ok=True);fn=secure_filename(f.filename) or "catalog.yml";p=d/fn;f.save(p)
    try:rows=read_catalog(str(p),include_content=True,limit=limit)
    except Exception as e:shutil.rmtree(d,ignore_errors=True);return render_template("error.html",message=f"Не вдалося прочитати каталог: {e}"),400
    c=_ui_cfg();shutil.rmtree(d,ignore_errors=True);return render_template("content_preview.html",rows=rows,supplier=supplier,app_version=c.get("app_version","v1.1"),brand_line=c.get("brand_line","Made by Пума (Чернявський А.)"))
@app.post("/analyze")
def analyze():
    f=request.files.get("catalog")
    if not f or not f.filename:return render_template("error.html",message="Не вибрано файл каталогу."),400
    if not allowed_file(f.filename,ALLOWED_ANALYSIS_EXTENSIONS):return render_template("error.html",message="доПУМАгатель v1.3 приймає XLSX, CSV, YML та XML."),400
    supplier=(request.form.get("supplier") or Path(f.filename).stem or "Не вказано").strip();
    try:limit=int((request.form.get("limit") or "30").strip())
    except ValueError:limit=30
    limit=max(1,min(limit,int(os.getenv("MAX_PRODUCTS_PER_JOB","5000"))));selected=request.form.getlist("marketplaces") or ["prom","epicentr","hotline","web_shops"]
    allowed={"prom","epicentr","hotline","web_shops"};selected=[x for x in selected if x in allowed] or list(allowed)
    jid=uuid.uuid4().hex[:12];d=JOBS_DIR/jid;d.mkdir(parents=True,exist_ok=True);fn=secure_filename(f.filename) or "catalog.xlsx";p=d/fn;f.save(p);fp=_job_fingerprint(p,supplier,selected,limit);dup=_find_active_duplicate(fp)
    if dup:shutil.rmtree(d,ignore_errors=True);return redirect(url_for("job_page",job_id=dup),code=303)
    set_job(jid,id=jid,status="queued",percent=0,current=0,total=0,message="Задача поставлена в чергу",filename=fn,supplier=supplier,marketplaces=selected,limit=limit,fingerprint=fp,created_at=time.time(),resume_available=False,engine_build=ENGINE_BUILD);_start_worker(jid);return redirect(url_for("job_page",job_id=jid),code=303)
@app.get("/jobs/<job_id>")
def job_page(job_id):
    if not get_job(job_id):abort(404)
    c=_ui_cfg();return render_template("job.html",job_id=job_id,app_version="v1.3",brand_line=c.get("brand_line","Made by Пума (Чернявський А.)"))
@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    j=get_job(job_id)
    if not j:abort(404)
    safe={k:v for k,v in j.items() if k not in {"xlsx_file","classic_xlsx_file","fingerprint"}}
    safe["current_engine_build"]=ENGINE_BUILD
    safe["stale_build"]=(j.get("engine_build") or "legacy")!=ENGINE_BUILD
    if j.get("status")=="done":
        safe["xlsx_url"]=url_for("download_xlsx",job_id=job_id)
        safe["classic_xlsx_url"]=url_for("download_classic_xlsx",job_id=job_id)
    return jsonify(safe)
@app.post("/api/jobs/<job_id>/rerun")
def rerun_job(job_id):
    j=get_job(job_id)
    if not j:abort(404)
    src=JOBS_DIR/job_id/(j.get("filename") or "")
    if not src.exists():return jsonify({"ok":False,"message":"Вхідний файл цього job більше не доступний."}),404
    supplier=j.get("supplier") or src.stem or "Не вказано"
    selected=list(j.get("marketplaces") or ["prom","epicentr","hotline","web_shops"])
    requested_limit=request.args.get("limit")
    try:limit=int(requested_limit) if requested_limit is not None else int(j.get("limit") or 30)
    except (TypeError,ValueError):limit=int(j.get("limit") or 30)
    limit=max(1,min(limit,int(os.getenv("MAX_PRODUCTS_PER_JOB","5000"))))
    fp=_job_fingerprint(src,supplier,selected,limit);dup=_find_active_duplicate(fp)
    if dup:return jsonify({"ok":True,"job_id":dup,"url":url_for("job_page",job_id=dup),"reused":True})
    jid=uuid.uuid4().hex[:12];d=JOBS_DIR/jid;d.mkdir(parents=True,exist_ok=True);fn=secure_filename(src.name) or "catalog.xlsx";dst=d/fn;shutil.copy2(src,dst)
    set_job(jid,id=jid,status="queued",percent=0,current=0,total=0,message="Повторний аналіз поставлено в чергу",filename=fn,supplier=supplier,marketplaces=selected,limit=limit,fingerprint=fp,created_at=time.time(),resume_available=False,engine_build=ENGINE_BUILD,parent_job=job_id)
    _start_worker(jid)
    return jsonify({"ok":True,"job_id":jid,"url":url_for("job_page",job_id=jid),"reused":False})
@app.get("/jobs/<job_id>/xlsx")
def download_xlsx(job_id):
    j=get_job(job_id)
    if not j or j.get("status")!="done":abort(404)
    p=Path(j.get("xlsx_file") or JOBS_DIR/job_id/"PUMA_doPUMAgatel_market_report.xlsx")
    if not p.exists():abort(404)
    return send_file(p,as_attachment=True,download_name="PUMA_doPUMAgatel_market_report.xlsx")
@app.get("/jobs/<job_id>/classic-xlsx")
def download_classic_xlsx(job_id):
    j=get_job(job_id)
    if not j or j.get("status")!="done":abort(404)
    p=Path(j.get("classic_xlsx_file") or JOBS_DIR/job_id/"PUMA_classic_analytical_report.xlsx")
    if not p.exists():abort(404)
    return send_file(p,as_attachment=True,download_name="PUMA_classic_analytical_report.xlsx")
@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id):return jsonify({"ok":False,"message":"Production v1.3 runs bounded parallel products; cancel will return in the next build."}),409
@app.post("/api/jobs/<job_id>/resume")
def resume_job(job_id):
    j=get_job(job_id)
    if not j:abort(404)
    if j.get("status")=="done":return jsonify({"ok":False,"message":"Job already completed."}),409
    if _thread_alive(job_id):return jsonify({"ok":True,"job_id":job_id,"reused":True,"resume_from_checkpoint":True})
    src=JOBS_DIR/job_id/(j.get("filename") or "")
    if not src.exists():return jsonify({"ok":False,"message":"Вхідний файл цього job більше не доступний."}),404
    checkpoint=JOBS_DIR/job_id/"checkpoint.json"
    same_build=(j.get("engine_build") or ENGINE_BUILD)==ENGINE_BUILD
    resume_from_checkpoint=checkpoint.exists() and same_build
    if checkpoint.exists() and not same_build:
        checkpoint.unlink(missing_ok=True)
    set_job(
        job_id,status="queued",message="Відновлення поставлено в чергу",
        resume_available=resume_from_checkpoint,engine_build=ENGINE_BUILD,
    )
    started=_start_worker(job_id)
    if not started:return jsonify({"ok":False,"message":"Не вдалося запустити відновлення."}),409
    return jsonify({"ok":True,"job_id":job_id,"reused":False,"resume_from_checkpoint":resume_from_checkpoint})
@app.errorhandler(413)
def too_large(_):return render_template("error.html",message=f"Файл завеликий. Ліміт сервера: {MAX_UPLOAD_MB} МБ."),413
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")),debug=False)
