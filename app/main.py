from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader
import os
import asyncio
from datetime import datetime, timedelta
import jwt
from typing import Optional, Dict
import uuid

from app.config import SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, SUPABASE_MGMT_TOKEN
from app.database import supabase, supabase_admin
from app.models import UserRegister, UserLogin, WorkerProfile, JobCreate
from app.translations import AR, EN

TRANSLATIONS = {"ar": AR, "en": EN}

import pathlib
import random
import httpx

SUPABASE_PROJECT_REF = "ubcpwhyjfzcphobjqtpl"

_TEMPLATES_DIR = pathlib.Path("app/templates")
_JINJA_ENV = Environment(loader=FileSystemLoader("app/templates"))

def render_template(request, name, **context):
    source = _TEMPLATES_DIR.joinpath(name).read_text(encoding="utf-8")
    template = _JINJA_ENV.from_string(source)
    lang = request.cookies.get("lang", "ar")
    if lang not in TRANSLATIONS:
        lang = "ar"
    t_data = TRANSLATIONS[lang]
    return HTMLResponse(template.render({"request": request, "lang": lang, "t": t_data, **context}))

app = FastAPI(title="Sanad - سند", docs_url=None, redoc_url=None, debug=False)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.exception_handler(404)
async def not_found(request, exc):
    return render_template(request, "errors/404.html")

@app.exception_handler(500)
async def server_error(request, exc):
    return render_template(request, "errors/500.html")

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    return Response(content="""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://sanad-job.onrender.com/</loc><priority>1.0</priority></url>
  <url><loc>https://sanad-job.onrender.com/login</loc><priority>0.6</priority></url>
  <url><loc>https://sanad-job.onrender.com/register</loc><priority>0.8</priority></url>
</urlset>""", media_type="application/xml")

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Sanad is running"}

CITIES = ["دمشق", "حلب", "حمص", "حماة", "اللاذقية", "طرطوس", "إدلب", "دير الزور", "الرقة", "الحسكة", "درعا", "السويداء", "القنيطرة", "ريف دمشق"]
WORK_TYPES = ["بناء وصيانة", "نظافة وخدمات منزلية", "توصيل وشحن", "سائق", "كهرباء", "سباكة", "نجارة", "حدادة و لحام", "دهان و ديكور", "تبريد و تكييف", "حدائق و زراعة", "حرف يدوية", "حراسة و أمن", "أخرى"]

def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[Dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None

async def get_current_user(request: Request):
    token = request.cookies.get("token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    return payload

async def get_user_profile(user_id: str):
    worker = supabase.table("workers").select("*").eq("user_id", user_id).execute()
    if worker.data:
        return {"type": "worker", "data": worker.data[0]}
    employer = supabase.table("employers").select("*").eq("user_id", user_id).execute()
    if employer.data:
        return {"type": "employer", "data": employer.data[0]}
    return None

async def get_wallet(user_id: str):
    try:
        result = supabase_admin.table("wallets").select("*").eq("user_id", user_id).execute()
        if result.data:
            return result.data[0]
        supabase_admin.table("wallets").insert({"user_id": user_id, "balance": 0}).execute()
        return {"user_id": user_id, "balance": 0}
    except Exception:
        return {"user_id": user_id, "balance": 0}

# ==================== Pages Routes ====================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = await get_current_user(request)
    return render_template(request, "index.html", user=user)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_template(request, "auth/login.html")

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return render_template(request, "auth/register.html")

# ==================== Auth Routes ====================

@app.post("/api/auth/register")
async def register(data: UserRegister):
    try:
        loop = asyncio.get_event_loop()
        auth_result = await loop.run_in_executor(None, lambda: supabase_admin.auth.admin.create_user({
            "email": data.email,
            "password": data.password,
            "email_confirm": True
        }))
        user_id = auth_result.user.id

        profile_data = {
            "user_id": user_id, "email": data.email,
            "first_name": data.first_name, "last_name": data.last_name,
            "phone": data.phone, "gender": data.gender,
            "nationality": data.nationality, "city": data.city
        }

        if data.role == "worker":
            profile_data["is_approved"] = False
            await loop.run_in_executor(None, lambda: supabase_admin.table("workers").insert(profile_data).execute())
        else:
            await loop.run_in_executor(None, lambda: supabase_admin.table("employers").insert(profile_data).execute())

        await loop.run_in_executor(None, lambda: supabase_admin.table("wallets").insert({"user_id": user_id, "balance": 0}).execute())

        return {"success": True, "message": "تم إنشاء الحساب بنجاح"}
    except Exception as e:
        err_msg = str(e)
        if "already" in err_msg.lower() or "duplicate" in err_msg.lower():
            return JSONResponse({"success": False, "message": "البريد الإلكتروني مسجل مسبقاً"}, status_code=400)
        if "timeout" in err_msg.lower() or "connect" in err_msg.lower():
            return JSONResponse({"success": False, "message": "خطأ في الاتصال بقاعدة البيانات، حاول مرة أخرى"}, status_code=502)
        return JSONResponse({"success": False, "message": err_msg}, status_code=400)

@app.post("/api/auth/login")
async def login(data: UserLogin):
    try:
        auth_result = supabase.auth.sign_in_with_password({"email": data.email, "password": data.password})
        user = auth_result.user

        profile = await get_user_profile(user.id)
        role = "admin" if user.email == "admin@sanad.com" else (profile["type"] if profile else "unknown")

        token = create_token({"sub": user.id, "email": user.email, "role": role})

        response = JSONResponse({"success": True, "role": role, "redirect": "/admin/dashboard" if role == "admin" else f"/{role}/dashboard"})
        response.set_cookie(key="token", value=token, httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES*60, samesite="lax")
        return response
    except Exception as e:
        return JSONResponse({"success": False, "message": "البريد الإلكتروني أو كلمة المرور غير صحيحة"}, status_code=401)

@app.get("/api/auth/logout")
async def logout():
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("token")
    return response

@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    profile = await get_user_profile(user["sub"])
    return {"authenticated": True, "user_id": user["sub"], "email": user["email"], "profile": profile}

# ==================== Worker Routes ====================

@app.get("/worker/dashboard", response_class=HTMLResponse)
async def worker_dashboard(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    wallet = await get_wallet(user["sub"])
    return render_template(request, "worker/dashboard.html", user=user, worker=profile["data"], wallet=wallet)

@app.get("/worker/profile", response_class=HTMLResponse)
async def worker_profile_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    return render_template(request, "worker/profile.html", user=user, worker=profile["data"], cities=CITIES)

@app.post("/api/worker/profile")
async def save_worker_profile(request: Request, first_name: str = Form(...), last_name: str = Form(...), age: int = Form(...), gender: str = Form(...), nationality: str = Form(...), phone: str = Form(...), city: str = Form(...)):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        supabase_admin.table("workers").update({
            "first_name": first_name, "last_name": last_name, "age": age,
            "gender": gender, "nationality": nationality, "phone": phone, "city": city
        }).eq("user_id", user["sub"]).execute()
        return {"success": True, "message": "تم حفظ الملف الشخصي"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/worker/upload-id")
async def upload_id(request: Request, file: UploadFile = File(...), side: str = Form(...)):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        ext = file.filename.split(".")[-1]
        filename = f"ids/{user['sub']}_{side}_{uuid.uuid4()}.{ext}"
        content = await file.read()
        result = supabase_admin.storage.from_("ids").upload(filename, content, {"content-type": file.content_type})
        url = f"{SUPABASE_URL}/storage/v1/object/public/ids/{filename}"
        supabase_admin.table("workers").update({f"id_image_{side}": url}).eq("user_id", user["sub"]).execute()
        return {"success": True, "url": url}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/worker/jobs", response_class=HTMLResponse)
async def worker_jobs(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    worker = profile["data"]
    if not worker.get("is_approved"):
        return render_template(request, "worker/pending.html", user=user)
    jobs = supabase.table("jobs").select("*").eq("city", worker["city"]).eq("status", "open").order("created_at", desc=True).execute()
    return render_template(request, "worker/jobs.html", user=user, jobs=jobs.data, worker=worker, work_types=WORK_TYPES)

@app.get("/worker/jobs/{job_id}", response_class=HTMLResponse)
async def job_details(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    job = supabase.table("jobs").select("*").eq("id", job_id).single().execute()
    if not job.data: return RedirectResponse("/worker/jobs", status_code=302)
    employer = supabase.table("employers").select("*").eq("id", job.data["employer_id"]).single().execute()
    return render_template(request, "worker/job_detail.html", user=user, job=job.data, employer=employer.data if employer.data else None)

@app.post("/api/worker/apply/{job_id}")
async def apply_job(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": raise HTTPException(403)
    existing = supabase.table("applications").select("*").eq("job_id", job_id).eq("worker_id", profile["data"]["id"]).execute()
    if existing.data:
        return JSONResponse({"success": False, "message": "لقد تقدمت لهذه الفرصة مسبقاً"}, status_code=400)
    supabase_admin.table("applications").insert({
        "job_id": job_id, "worker_id": profile["data"]["id"], "status": "pending"
    }).execute()
    return {"success": True, "message": "تم التقديم على الفرصة بنجاح"}

@app.post("/api/worker/save-job/{job_id}")
async def save_job(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": raise HTTPException(403)
    try:
        existing = supabase_admin.table("saved_jobs").select("*").eq("worker_id", profile["data"]["id"]).eq("job_id", job_id).execute()
        if existing.data:
            supabase_admin.table("saved_jobs").delete().eq("worker_id", profile["data"]["id"]).eq("job_id", job_id).execute()
            return {"success": True, "saved": False, "message": "تم إزالة الإعجاب"}
        supabase_admin.table("saved_jobs").insert({"worker_id": profile["data"]["id"], "job_id": job_id}).execute()
        return {"success": True, "saved": True, "message": "تم حفظ الفرصة"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/worker/saved-jobs", response_class=HTMLResponse)
async def saved_jobs_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    worker = profile["data"]
    if not worker.get("is_approved"):
        return render_template(request, "worker/pending.html", user=user)
    saved = supabase_admin.table("saved_jobs").select("*, jobs(*)").eq("worker_id", worker["id"]).order("created_at", desc=True).execute()
    return render_template(request, "worker/saved_jobs.html", user=user, saved_jobs=saved.data, worker=worker)

@app.get("/worker/applications", response_class=HTMLResponse)
async def my_applications(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    apps = supabase.table("applications").select("*, jobs(*)").eq("worker_id", profile["data"]["id"]).order("created_at", desc=True).execute()
    return render_template(request, "worker/applications.html", user=user, applications=apps.data)

# ==================== Employer Routes ====================

@app.get("/employer/dashboard", response_class=HTMLResponse)
async def employer_dashboard(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": return RedirectResponse("/", status_code=302)
    jobs = supabase.table("jobs").select("*").eq("employer_id", profile["data"]["id"]).order("created_at", desc=True).execute()
    wallet = await get_wallet(user["sub"])
    return render_template(request, "employer/dashboard.html", user=user, employer=profile["data"], jobs=jobs.data, wallet=wallet)

@app.get("/employer/post-job", response_class=HTMLResponse)
async def post_job_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": return RedirectResponse("/", status_code=302)
    return render_template(request, "employer/post_job.html", user=user, cities=CITIES, work_types=WORK_TYPES)

@app.post("/api/employer/job")
async def create_job(request: Request, title: str = Form(...), description: str = Form(""), work_type: str = Form(...), duration: str = Form(...), pay: float = Form(...), phone: str = Form(...), address: str = Form(...), city: str = Form(...), notes: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        supabase_admin.table("jobs").insert({
            "employer_id": profile["data"]["id"], "title": title, "description": description,
            "work_type": work_type, "duration": duration, "pay": pay,
            "phone": phone, "address": address, "city": city, "notes": notes, "status": "open"
        }).execute()
        return {"success": True, "message": "تم نشر فرصة العمل بنجاح"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/employer/job/{job_id}/delete")
async def delete_job(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        supabase_admin.table("jobs").delete().eq("id", job_id).eq("employer_id", profile["data"]["id"]).execute()
        return {"success": True, "message": "تم حذف فرصة العمل"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/employer/edit-job/{job_id}", response_class=HTMLResponse)
async def edit_job_page(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": return RedirectResponse("/", status_code=302)
    job = supabase.table("jobs").select("*").eq("id", job_id).eq("employer_id", profile["data"]["id"]).single().execute()
    if not job.data: return RedirectResponse("/employer/dashboard", status_code=302)
    return render_template(request, "employer/post_job.html", user=user, job=job.data, work_types=WORK_TYPES, cities=CITIES)

@app.post("/api/employer/job/{job_id}/update")
async def update_job(request: Request, job_id: str, title: str = Form(...), description: str = Form(""), work_type: str = Form(...), duration: str = Form(...), pay: float = Form(...), phone: str = Form(...), address: str = Form(...), city: str = Form(...), notes: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        supabase_admin.table("jobs").update({
            "title": title, "description": description, "work_type": work_type,
            "duration": duration, "pay": pay, "phone": phone,
            "address": address, "city": city, "notes": notes
        }).eq("id", job_id).eq("employer_id", profile["data"]["id"]).execute()
        return {"success": True, "message": "تم تحديث فرصة العمل"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/employer/jobs/{job_id}/applicants", response_class=HTMLResponse)
async def view_applicants(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    job = supabase.table("jobs").select("*").eq("id", job_id).single().execute()
    if not job.data: return RedirectResponse("/employer/dashboard", status_code=302)
    apps = supabase.table("applications").select("*, workers(*)").eq("job_id", job_id).execute()
    return render_template(request, "employer/applicants.html", user=user, job=job.data, applications=apps.data)

@app.post("/api/employer/accept-application/{application_id}")
async def accept_application(request: Request, application_id: str):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer":
        raise HTTPException(403)
    try:
        supabase_admin.table("applications").update({"status": "accepted"}).eq("id", application_id).execute()
        return {"success": True, "message": "تم قبول المتقدم"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/employer/reject-application/{application_id}")
async def reject_application(request: Request, application_id: str):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer":
        raise HTTPException(403)
    try:
        supabase_admin.table("applications").update({"status": "rejected"}).eq("id", application_id).execute()
        return {"success": True, "message": "تم رفض المتقدم"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

# ==================== Admin Routes ====================

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    if user.get("email") != "admin@sanad.com":
        return RedirectResponse("/", status_code=302)
    workers = supabase.table("workers").select("*").order("created_at", desc=True).execute()
    jobs = supabase.table("jobs").select("*").order("created_at", desc=True).execute()
    employers = supabase.table("employers").select("*").order("created_at", desc=True).execute()
    applications = supabase.table("applications").select("*").execute()
    total_workers = len(workers.data)
    total_employers = len(employers.data)
    total_jobs = len(jobs.data)
    total_applications = len(applications.data)
    return render_template(request, "admin/dashboard.html", user=user, workers=workers.data, jobs=jobs.data, employers=employers.data, total_workers=total_workers, total_employers=total_employers, total_jobs=total_jobs, total_applications=total_applications)

@app.post("/api/admin/approve-worker/{worker_id}")
async def approve_worker(request: Request, worker_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com":
        raise HTTPException(403)
    supabase_admin.table("workers").update({"is_approved": True}).eq("id", worker_id).execute()
    return {"success": True, "message": "تم الموافقة على العامل"}

@app.post("/api/admin/reject-worker/{worker_id}")
async def reject_worker(request: Request, worker_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com":
        raise HTTPException(403)
    supabase_admin.table("workers").update({"is_approved": False}).eq("id", worker_id).execute()
    return {"success": True, "message": "تم رفض العامل"}

@app.post("/api/admin/close-job/{job_id}")
async def close_job(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com":
        raise HTTPException(403)
    supabase_admin.table("jobs").update({"status": "closed"}).eq("id", job_id).execute()
    return {"success": True, "message": "تم إغلاق فرصة العمل"}

# ==================== Reviews & Wallets Initialization ====================

CREATE_REVIEWS_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  reviewer_name TEXT NOT NULL,
  reviewer_role TEXT NOT NULL CHECK (reviewer_role IN ('worker','employer')),
  target_role TEXT NOT NULL CHECK (target_role IN ('worker','employer')),
  rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

CREATE_WALLETS_SQL = """
CREATE TABLE IF NOT EXISTS wallets (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL UNIQUE,
  balance INTEGER DEFAULT 0,
  currency TEXT DEFAULT 'SYP',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS wallet_transactions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  wallet_id UUID REFERENCES wallets(id),
  amount INTEGER NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('deposit','withdrawal','payment','refund')),
  description TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

CREATE_SAVED_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS saved_jobs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  worker_id UUID REFERENCES workers(id),
  job_id UUID REFERENCES jobs(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(worker_id, job_id)
);
"""

WORKER_NAMES = [
    "أحمد الخطيب", "محمود الحسن", "علي خالد", "حسن مراد", "خالد العلي",
    "عمران العبد", "باسل زيدان", "نور الدين", "سامر عبود", "وائل السيد",
    "محمد جابر", "حسام الدين", "مصطفى كريم", "يزن محمود", "عبد الرحمن",
    "بسام الرفاعي", "غسان نعيم", "رامي شوقي", "حازم نور", "قتيبة زاهر",
    "مهند الصالح", "أيمن فؤاد", "أنس خليل", "همام بشار", "عماد جمال",
    "ديما السيد", "رؤى عمر", "سارة علي", "نورا حسان", "ميرا عبد الله",
    "لينا سامر", "سلمى كمال", "رنا زاهر", "هدى إبراهيم", "فاطمة عادل"
]
EMPLOYER_NAMES = [
    "شركة الأمل للتجارة", "مؤسسة النور", "مجموعة الفيحاء", "شركة قاسيون",
    "مكتب السلام العقاري", "مطعم دمشق القديم", "مستشفى الشفاء", "شركة آراد",
    "بنك سورية الدولي", "جامعة القلمون", "فندق شيراتون دمشق", "مركز سما",
    "مؤسسة الينابيع", "شركة أوغاريت", "مجموعة العلي", "مكتب المحامي الدرويش",
    "مطعم جبل العرب", "مخبز الياسمين", "شركة سورية أونلاين", "مستوصف الخير",
    "مؤسسة ركن الشام", "شركة التاج الذهبي", "مكتب المهندس جواد", "فندق صحارى",
    "معمل سجاد حمص", "شركة البركة", "مؤسسة النجاح", "مركز التدريب المهني",
    "مطعم وادي العذيب", "شركة السورية للتأمين", "مجموعة الإخاء", "مكتب السياحة"
]
REVIEWS_WORKER_TEMPLATES = [
    "عامل ممتاز ونظيف جداً، التزم بالمواعيد وأنهى العمل بكفاءة عالية. أنصح به بشدة.",
    "تعاملت مع هذا العامل وكان محترفاً جداً. عمل دقيق ونظافة ممتازة. سأتعامل معه مرة أخرى.",
    "عمل رائع! العامل كان خلوقاً ومحترماً وأنهى كل المهام المطلوبة في الوقت المحدد.",
    "تجربة ممتازة، العامل محترف وأدواته كاملة. النتيجة كانت أفضل مما توقعت.",
    "ممتاز! تعامل محترف وسعر معقول. العامل كان محترماً جداً وأنهى العمل بسرعة.",
    "أشكر هذا العامل على جهوده، عمل متقن ونظافة رائعة. أوصي به لكل من يبحث عن عامل محترف.",
    "العامل كان خلوقاً جداً وأنجز العمل بشكل ممتاز. المنصة سهّلت عملية التواصل.",
    "أول مرة استخدم فيها المنصة وكانت تجربة رائعة. العامل محترف والنتيجة ممتازة.",
    "من أفضل العمال الذين تعاملت معهم. دقة في العمل واحترام في التعامل.",
    "تجربة ناجحة، العامل ملتزم ومواعيده مضبوطة. شكراً لكم."
]
REVIEWS_EMPLOYER_TEMPLATES = [
    "صاحب عمل محترم جداً، دفع الأجر كاملاً وفي الوقت المحدد. عمل معه أكثر من مرة.",
    "تعامل مع صاحب العمل وكان مثالياً. أوضح المطلوب بدقة وكان كريماً في التقييم.",
    "صاحب عمل خلوق ويراعي ظروف العمال. تجربة عمل ممتعة وأتمنى العمل معه مرة أخرى.",
    "ممتاز! صاحب العمل وفّر كل المستلزمات اللازمة وكان التعامل راقياً جداً.",
    "تجربة ممتازة مع صاحب عمل محترف. فهم طبيعة العمل وكان عادلاً في التقييم.",
    "صاحب العمل كان متفاهماً جداً وسهل التعامل. دفع الأجر فور انتهاء العمل.",
    "أفضل صاحب عمل تعاملت معه. محترم وكريم ويعامل العامل باحترام.",
    "تجربة ممتازة! أوصي بالعمل مع هذا الشخص لأي عامل. بيئة عمل مريحة.",
    "صاحب عمل منظم وواضح. الشرح كان دقيقاً والمطلوب كان واضحاً منذ البداية.",
    "تعاملت معه لأكثر من مرة. شخص محترم وملتزم بوعوده. شكراً لك."
]

async def ensure_reviews_table():
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, lambda: supabase_admin.table("reviews").select("id", count="exact").limit(1).execute()), timeout=15)
        return True
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT_REF}/database/query",
                headers={
                    "Authorization": f"Bearer {SUPABASE_MGMT_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={"query": CREATE_REVIEWS_SQL}
            )
            if resp.status_code >= 400:
                print(f"WARN: Failed to create reviews table: {resp.status_code} {resp.text[:200]}")
                return False
            print("Created reviews table successfully")
            return True
    except Exception as e:
        print(f"WARN: Could not create reviews table: {e}")
        return False

async def seed_reviews(target_role, names, templates, count=500):
    batch_size = 50
    batch = []
    for i in range(count):
        name = random.choice(names)
        rating = random.choices([5, 4, 3, 2, 1], weights=[55, 30, 10, 3, 2])[0]
        content = random.choice(templates)
        batch.append({
            "reviewer_name": name,
            "reviewer_role": "employer" if target_role == "worker" else "worker",
            "target_role": target_role,
            "rating": rating,
            "content": content
        })
        if len(batch) >= batch_size:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: supabase_admin.table("reviews").insert(batch).execute())
                print(f"  Seeded {len(batch)} {target_role} reviews")
            except Exception as e:
                print(f"  WARN: insert batch failed: {e}")
            batch = []
    if batch:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: supabase_admin.table("reviews").insert(batch).execute())
            print(f"  Seeded final {len(batch)} {target_role} reviews")
        except Exception as e:
            print(f"  WARN: insert final batch failed: {e}")

@app.on_event("startup")
async def init_database():
    print("Startup complete - server ready")

@app.get("/api/reviews/all")
async def get_all_reviews(limit: int = 60):
    try:
        result = supabase_admin.table("reviews").select("*").limit(limit).execute()
        random.shuffle(result.data)
        return {"data": result.data}
    except Exception:
        return {"data": []}

@app.get("/api/reviews/{target_role}")
async def get_reviews(target_role: str, limit: int = 20):
    try:
        result = supabase_admin.table("reviews").select("*").eq("target_role", target_role).order("created_at", desc=True).limit(limit).execute()
        return {"data": result.data}
    except Exception:
        return {"data": []}

# ==================== Wallet Routes ====================

@app.get("/api/wallet")
async def get_wallet_api(request: Request):
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    wallet = await get_wallet(user["sub"])
    transactions = supabase_admin.table("wallet_transactions").select("*").eq("wallet_id", wallet["id"]).order("created_at", desc=True).limit(10).execute()
    return {"balance": wallet.get("balance", 0), "currency": wallet.get("currency", "SYP"), "transactions": transactions.data}

@app.post("/api/wallet/deposit")
async def deposit_wallet(request: Request, amount: int = Form(...), description: str = Form("")):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(401)
    if amount <= 0:
        return JSONResponse({"success": False, "message": "المبلغ يجب أن يكون أكبر من صفر"}, status_code=400)
    wallet = await get_wallet(user["sub"])
    new_balance = wallet.get("balance", 0) + amount
    supabase_admin.table("wallets").update({"balance": new_balance}).eq("user_id", user["sub"]).execute()
    if wallet.get("id"):
        supabase_admin.table("wallet_transactions").insert({
            "wallet_id": wallet["id"], "amount": amount, "type": "deposit", "description": description or "إيداع"
        }).execute()
    return {"success": True, "balance": new_balance}

@app.get("/api/set-lang/{lang}")
async def set_lang(lang: str):
    response = RedirectResponse(url="/")
    if lang in ("ar", "en"):
        response.set_cookie(key="lang", value=lang, max_age=365*24*3600, path="/")
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
