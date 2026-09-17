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

from priceintel.io import read_catalog
from puma_scouts.production import run_sync

BASE = Path(__file__).resolve().parent
JOBS_DIR = BASE / "data" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_ANALYSIS_EXTENSIONS = {"xlsx","csv","yml","xml"}
ALLOWED_CONTENT_EXTENSIONS = {"csv", "yml", "xml"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "120"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
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
            if data.get("status") in {"queued","running"}:data["status"]="interrupted";data["message"]="Попередній процес перервався. Запусти аналіз повторно."
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
    def progress(current,total,name,extra=None):set_job(job_id,status="running",current=current,total=total,percent=round(current/max(1,total)*100,1),current_product=name,message=extra or "Аналізуємо ринок…")
    try:
        set_job(job_id,status="running",message="Читаємо каталог…",started_at=time.time())
        summary=run_sync(str(input_path),str(xlsx),limit=limit,selected=selected_markets,progress_cb=progress,classic_output_path=str(classic_xlsx),supplier=supplier)
        set_job(job_id,status="done",percent=100,message="Готово",finished_at=time.time(),summary=summary,xlsx_file=str(xlsx),classic_xlsx_file=str(classic_xlsx),resume_available=False)
    except Exception as e:set_job(job_id,status="error",message=f"{type(e).__name__}: {e}",finished_at=time.time(),resume_available=False)
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
    set_job(jid,id=jid,status="queued",percent=0,current=0,total=0,message="Задача поставлена в чергу",filename=fn,supplier=supplier,marketplaces=selected,limit=limit,fingerprint=fp,created_at=time.time(),resume_available=False);_start_worker(jid);return redirect(url_for("job_page",job_id=jid),code=303)
@app.get("/jobs/<job_id>")
def job_page(job_id):
    if not get_job(job_id):abort(404)
    c=_ui_cfg();return render_template("job.html",job_id=job_id,app_version="v1.3",brand_line=c.get("brand_line","Made by Пума (Чернявський А.)"))
@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    j=get_job(job_id)
    if not j:abort(404)
    safe={k:v for k,v in j.items() if k not in {"xlsx_file","classic_xlsx_file","fingerprint"}}
    if j.get("status")=="done":
        safe["xlsx_url"]=url_for("download_xlsx",job_id=job_id)
        safe["classic_xlsx_url"]=url_for("download_classic_xlsx",job_id=job_id)
    return jsonify(safe)
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
def resume_job(job_id):return jsonify({"ok":False,"message":"Production v1.3: restart the analysis with the same catalog file."}),409
@app.errorhandler(413)
def too_large(_):return render_template("error.html",message=f"Файл завеликий. Ліміт сервера: {MAX_UPLOAD_MB} МБ."),413
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")),debug=False)
