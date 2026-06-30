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
from app.models import UserRegister, UserLogin, WorkerProfile, JobCreate, ContactForm
from app.translations import AR, EN

TRANSLATIONS = {"ar": AR, "en": EN}

import pathlib
import random
import httpx

SUPABASE_PROJECT_REF = "ubcpwhyjfzcphobjqtpl"
SUPABASE_STORAGE_URL = f"https://{SUPABASE_PROJECT_REF}.supabase.co/storage/v1"

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
    try:
        jobs_all = supabase_admin.table("jobs").select("*", count="exact").execute()
        total_jobs = jobs_all.count if hasattr(jobs_all, 'count') else len(jobs_all.data or [])
        today = datetime.utcnow().strftime("%Y-%m-%d")
        today_jobs = len([j for j in (jobs_all.data or []) if j.get("created_at","").startswith(today)])
        workers_count = len((supabase_admin.table("workers").select("id", count="exact").execute()).data or [])
        employers_count = len((supabase_admin.table("employers").select("id", count="exact").execute()).data or [])
        cats = supabase_admin.table("jobs").select("work_type", count="exact").execute()
        cat_counts = {}
        for j in (cats.data or []):
            wt = j.get("work_type", "أخرى")
            cat_counts[wt] = cat_counts.get(wt, 0) + 1
        cat_counts = dict(sorted(cat_counts.items(), key=lambda x: -x[1])[:14])
        emp_result = supabase_admin.table("employers").select("id,company_name,photo_url").limit(30).execute()
        employers_list = emp_result.data if emp_result and hasattr(emp_result, 'data') else []
    except:
        total_jobs = 0; today_jobs = 0; workers_count = 0; employers_count = 0; cat_counts = {}; employers_list = []
    return render_template(request, "index.html", user=user, total_jobs=total_jobs, today_jobs=today_jobs, workers_count=workers_count, employers_count=employers_count, cat_counts=cat_counts, employers=employers_list, work_types=WORK_TYPES, cities=CITIES)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_template(request, "auth/login.html")

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            auth_resp = await client.post(
                f"https://{SUPABASE_PROJECT_REF}.supabase.co/auth/v1/token?grant_type=password",
                headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                json={"email": email, "password": password}
            )
            if auth_resp.status_code >= 400:
                return render_template(request, "auth/login.html", error="البريد الإلكتروني أو كلمة المرور غير صحيحة", email=email)
            user_data = auth_resp.json()
            user_id = user_data.get("user", {}).get("id", "")
            user_email = user_data.get("user", {}).get("email", email)

        profile = await get_user_profile(user_id)
        role = "admin" if user_email == "admin@sanad.com" else (profile["type"] if profile else None)

        if not role:
            return render_template(request, "auth/login.html", error="هذا الحساب ليس لديه صلاحية دخول. الرجاء التواصل مع الدعم.", email=email)

        first_name = profile["data"].get("first_name", "") if (profile and profile.get("data")) else ""
        last_name = profile["data"].get("last_name", "") if (profile and profile.get("data")) else ""

        token = create_token({"sub": user_id, "email": user_email, "role": role, "first_name": first_name, "last_name": last_name})

        response = RedirectResponse("/admin/dashboard" if role == "admin" else f"/{role}/dashboard", status_code=302)
        response.set_cookie(key="token", value=token, httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES*60, samesite="lax")
        return response
    except Exception:
        return render_template(request, "auth/login.html", error="حدث خطأ في الاتصال، حاول مرة أخرى", email=email)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return render_template(request, "auth/register.html")

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    user = await get_current_user(request)
    return render_template(request, "about.html", user=user)

@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    user = await get_current_user(request)
    return render_template(request, "contact.html", user=user)

@app.post("/api/contact")
async def contact_form(data: ContactForm):
    try:
        print(f"Contact form: {data.name} <{data.email}>: {data.message[:50]}...")
        return {"success": True, "message": "{{ t.contact_success }}"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

# ==================== Auth Routes ====================

@app.post("/api/auth/register")
async def register(data: UserRegister):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            auth_resp = await client.post(
                f"https://{SUPABASE_PROJECT_REF}.supabase.co/auth/v1/admin/users",
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json"
                },
                json={"email": data.email, "password": data.password, "email_confirm": True}
            )
            if auth_resp.status_code >= 400:
                err_body = auth_resp.text
                if "already" in err_body.lower() or "duplicate" in err_body.lower():
                    return JSONResponse({"success": False, "message": "البريد الإلكتروني مسجل مسبقاً"}, status_code=400)
                return JSONResponse({"success": False, "message": err_body}, status_code=400)

            user_id = auth_resp.json()["id"]

        profile_data = {
            "user_id": user_id, "email": data.email,
            "first_name": data.first_name, "last_name": data.last_name,
            "phone": data.phone, "gender": data.gender,
            "nationality": data.nationality, "city": data.city
        }

        if data.role == "worker":
            profile_data["is_approved"] = False
            supabase_admin.table("workers").insert(profile_data).execute()
        else:
            supabase_admin.table("employers").insert(profile_data).execute()

        supabase_admin.table("wallets").insert({"user_id": user_id, "balance": 0}).execute()

        return {"success": True, "message": "تم إنشاء الحساب بنجاح"}
    except httpx.TimeoutException:
        return JSONResponse({"success": False, "message": "خطأ في الاتصال بقاعدة البيانات، حاول مرة أخرى"}, status_code=502)
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
        async with httpx.AsyncClient(timeout=15) as client:
            auth_resp = await client.post(
                f"https://{SUPABASE_PROJECT_REF}.supabase.co/auth/v1/token?grant_type=password",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json"
                },
                json={"email": data.email, "password": data.password}
            )
            if auth_resp.status_code >= 400:
                return JSONResponse({"success": False, "message": "البريد الإلكتروني أو كلمة المرور غير صحيحة"}, status_code=401)
            user_data = auth_resp.json()
            user_id = user_data.get("user", {}).get("id", "")
            email = user_data.get("user", {}).get("email", data.email)

        profile = await get_user_profile(user_id)
        role = "admin" if email == "admin@sanad.com" else (profile["type"] if profile else None)

        if not role:
            return JSONResponse({"success": False, "message": "هذا الحساب ليس لديه صلاحية دخول"}, status_code=403)

        first_name = profile["data"].get("first_name", "") if (profile and profile.get("data")) else ""
        last_name = profile["data"].get("last_name", "") if (profile and profile.get("data")) else ""

        token = create_token({"sub": user_id, "email": email, "role": role, "first_name": first_name, "last_name": last_name})

        response = JSONResponse({"success": True, "role": role, "redirect": "/admin/dashboard" if role == "admin" else f"/{role}/dashboard"})
        response.set_cookie(key="token", value=token, httponly=True, max_age=ACCESS_TOKEN_EXPIRE_MINUTES*60, samesite="lax")
        return response
    except Exception:
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
async def worker_jobs(request: Request, q: str = "", work_type: str = "", city: str = ""):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    worker = profile["data"]
    if not worker.get("is_approved"):
        return render_template(request, "worker/pending.html", user=user)
    query = supabase.table("jobs").select("*").eq("status", "open")
    if city:
        query = query.eq("city", city)
    if work_type:
        query = query.eq("work_type", work_type)
    result = query.order("created_at", desc=True).execute()
    jobs = result.data
    if q:
        ql = q.lower()
        jobs = [j for j in jobs if ql in j.get("title", "").lower() or ql in j.get("description", "").lower()]
    return render_template(request, "worker/jobs.html", user=user, jobs=jobs, worker=worker, work_types=WORK_TYPES, cities=CITIES, q=q, sel_work_type=work_type, sel_city=city)

@app.get("/worker/jobs/{job_id}", response_class=HTMLResponse)
async def job_details(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    job = supabase.table("jobs").select("*").eq("id", job_id).single().execute()
    if not job.data: return RedirectResponse("/worker/jobs", status_code=302)
    employer = supabase.table("employers").select("*").eq("id", job.data["employer_id"]).single().execute()
    return render_template(request, "worker/job_detail.html", user=user, job=job.data, employer=employer.data if employer.data else None)

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

@app.post("/api/employer/upload-image")
async def upload_job_image(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        os.makedirs("app/static/uploads", exist_ok=True)
        ext = pathlib.Path(file.filename).suffix if file.filename else ".jpg"
        filename = f"job_{uuid.uuid4().hex[:12]}{ext}"
        content = await file.read()
        with open(f"app/static/uploads/{filename}", "wb") as f:
            f.write(content)
        return {"success": True, "url": f"/static/uploads/{filename}"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/employer/job")
async def create_job(request: Request, title: str = Form(...), description: str = Form(""), work_type: str = Form(...), duration: str = Form(...), pay: float = Form(...), phone: str = Form(...), address: str = Form(...), city: str = Form(...), notes: str = Form(""), image_url: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        job_data = {
            "employer_id": profile["data"]["id"], "title": title, "description": description,
            "work_type": work_type, "duration": duration, "pay": pay,
            "phone": phone, "address": address, "city": city, "notes": notes, "status": "open"
        }
        if image_url:
            job_data["image_url"] = image_url
        supabase_admin.table("jobs").insert(job_data).execute()
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
async def update_job(request: Request, job_id: str, title: str = Form(...), description: str = Form(""), work_type: str = Form(...), duration: str = Form(...), pay: float = Form(...), phone: str = Form(...), address: str = Form(...), city: str = Form(...), notes: str = Form(""), image_url: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        update_data = {
            "title": title, "description": description, "work_type": work_type,
            "duration": duration, "pay": pay, "phone": phone,
            "address": address, "city": city, "notes": notes
        }
        if image_url:
            update_data["image_url"] = image_url
        supabase_admin.table("jobs").update(update_data).eq("id", job_id).eq("employer_id", profile["data"]["id"]).execute()
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

@app.get("/admin/workers-pending", response_class=HTMLResponse)
async def admin_workers_pending(request: Request):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": return RedirectResponse("/", status_code=302)
    workers = supabase.table("workers").select("*").eq("is_approved", False).order("created_at", desc=True).execute()
    return render_template(request, "admin/workers_pending.html", user=user, pending=workers.data)

@app.get("/admin/clients", response_class=HTMLResponse)
async def admin_clients_page(request: Request):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": return RedirectResponse("/", status_code=302)
    return render_template(request, "admin/clients.html", user=user)

@app.get("/admin/jobs", response_class=HTMLResponse)
async def admin_jobs_page(request: Request):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": return RedirectResponse("/", status_code=302)
    jobs = supabase.table("jobs").select("*").order("created_at", desc=True).execute()
    return render_template(request, "admin/jobs.html", user=user, jobs=jobs.data)

@app.get("/admin/payment-methods", response_class=HTMLResponse)
async def admin_payment_methods_page(request: Request):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": return RedirectResponse("/", status_code=302)
    return render_template(request, "admin/payment_methods.html", user=user)

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
    worker = supabase_admin.table("workers").select("user_id").eq("id", worker_id).execute()
    if worker.data:
        uid = worker.data[0]["user_id"]
        supabase_admin.table("applications").delete().eq("worker_id", uid).execute()
        supabase_admin.table("saved_jobs").delete().eq("worker_id", worker_id).execute()
        supabase_admin.table("wallets").delete().eq("user_id", uid).execute()
        supabase_admin.table("notifications").delete().eq("user_id", uid).execute()
        supabase_admin.table("workers").delete().eq("id", worker_id).execute()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(
                    f"https://{SUPABASE_PROJECT_REF}.supabase.co/auth/v1/admin/users/{uid}",
                    headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY}
                )
        except: pass
    return {"success": True}

@app.post("/api/admin/close-job/{job_id}")
async def close_job(request: Request, job_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com":
        raise HTTPException(403)
    supabase_admin.table("jobs").update({"status": "closed"}).eq("id", job_id).execute()
    return {"success": True, "message": "تم إغلاق فرصة العمل"}

# ==================== Reviews & Wallets Initialization ====================

# ==================== Database Init ====================

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  reviewer_name TEXT NOT NULL,
  reviewer_role TEXT NOT NULL CHECK (reviewer_role IN ('worker','employer')),
  target_role TEXT NOT NULL CHECK (target_role IN ('worker','employer')),
  rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
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
CREATE TABLE IF NOT EXISTS saved_jobs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  worker_id UUID REFERENCES workers(id),
  job_id UUID REFERENCES jobs(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(worker_id, job_id)
);
CREATE TABLE IF NOT EXISTS notifications (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  type TEXT DEFAULT 'info',
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS messages (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  sender_id TEXT NOT NULL,
  sender_name TEXT DEFAULT '',
  receiver_id TEXT NOT NULL,
  job_id TEXT,
  content TEXT NOT NULL,
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE workers ADD COLUMN IF NOT EXISTS bio TEXT;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS photo_url TEXT;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS skills JSONB DEFAULT '[]';
ALTER TABLE workers ADD COLUMN IF NOT EXISTS experience JSONB DEFAULT '[]';
ALTER TABLE workers ADD COLUMN IF NOT EXISTS education JSONB DEFAULT '[]';
ALTER TABLE workers ADD COLUMN IF NOT EXISTS cv_url TEXT;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS available_for_freelance BOOLEAN DEFAULT FALSE;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS hourly_rate INTEGER DEFAULT 0;
ALTER TABLE workers ADD COLUMN IF NOT EXISTS freelance_desc TEXT;
ALTER TABLE employers ADD COLUMN IF NOT EXISTS company_name TEXT;
ALTER TABLE employers ADD COLUMN IF NOT EXISTS company_logo TEXT;
ALTER TABLE employers ADD COLUMN IF NOT EXISTS company_description TEXT;
ALTER TABLE employers ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS image_url TEXT;
CREATE TABLE IF NOT EXISTS payment_methods (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  currency TEXT NOT NULL,
  network TEXT NOT NULL,
  wallet_address TEXT NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

async def execute_sql(query: str):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT_REF}/database/query",
                headers={
                    "Authorization": f"Bearer {SUPABASE_MGMT_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={"query": query}
            )
            if resp.status_code >= 400:
                print(f"  SQL status={resp.status_code}: {resp.text[:150]}")
            return resp
    except Exception as e:
        print(f"  SQL error: {e}")
        return None

async def create_notification(user_id: str, title: str, message: str, type: str = "info"):
    try:
        supabase_admin.table("notifications").insert({
            "user_id": user_id, "title": title, "message": message, "type": type
        }).execute()
    except Exception:
        pass

@app.on_event("startup")
async def init_database():
    for stmt in CREATE_TABLES_SQL.split(";"):
        s = stmt.strip()
        if s:
            await execute_sql(s + ";")
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

# ==================== Enhanced Worker Profile Routes ====================

@app.post("/api/worker/profile/save")
async def save_worker_profile_full(request: Request, first_name: str = Form(...), last_name: str = Form(...), age: int = Form(...), gender: str = Form(...), nationality: str = Form(...), phone: str = Form(...), city: str = Form(...), bio: str = Form(""), skills: str = Form("[]"), experience: str = Form("[]"), education: str = Form("[]")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        import json as j
        skills_data = j.loads(skills) if isinstance(skills, str) else skills
        exp_data = j.loads(experience) if isinstance(experience, str) else experience
        edu_data = j.loads(education) if isinstance(education, str) else education
        supabase_admin.table("workers").update({
            "first_name": first_name, "last_name": last_name, "age": age,
            "gender": gender, "nationality": nationality, "phone": phone, "city": city,
            "bio": bio, "skills": skills_data, "experience": exp_data, "education": edu_data
        }).eq("user_id", user["sub"]).execute()
        return {"success": True, "message": "تم حفظ الملف الشخصي"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/worker/profile/upload-photo")
async def upload_worker_photo(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        os.makedirs("app/static/uploads", exist_ok=True)
        ext = pathlib.Path(file.filename).suffix or ".jpg"
        filename = f"photo_{user['sub'][:8]}_{uuid.uuid4().hex[:8]}{ext}"
        content = await file.read()
        with open(f"app/static/uploads/{filename}", "wb") as f:
            f.write(content)
        url = f"/static/uploads/{filename}"
        supabase_admin.table("workers").update({"photo_url": url}).eq("user_id", user["sub"]).execute()
        return {"success": True, "url": url}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/worker/profile/upload-cv")
async def upload_worker_cv(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        os.makedirs("app/static/uploads", exist_ok=True)
        ext = pathlib.Path(file.filename).suffix or ".pdf"
        filename = f"cv_{user['sub'][:8]}_{uuid.uuid4().hex[:8]}{ext}"
        content = await file.read()
        with open(f"app/static/uploads/{filename}", "wb") as f:
            f.write(content)
        url = f"/static/uploads/{filename}"
        supabase_admin.table("workers").update({"cv_url": url}).eq("user_id", user["sub"]).execute()
        return {"success": True, "url": url}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/worker/profile/delete-cv")
async def delete_worker_cv(request: Request):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        supabase_admin.table("workers").update({"cv_url": None}).eq("user_id", user["sub"]).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/api/worker/stats")
async def worker_stats(request: Request):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": raise HTTPException(403)
    wid = profile["data"]["id"]
    apps = supabase.table("applications").select("id", count="exact").eq("worker_id", wid).execute()
    saved = supabase_admin.table("saved_jobs").select("id", count="exact").eq("worker_id", wid).execute()
    w = profile["data"]
    fields = [w.get("bio"), w.get("photo_url"), w.get("skills"), w.get("experience"), w.get("education"), w.get("id_image_front"), w.get("id_image_back")]
    filled = sum(1 for f in fields if f and f != "[]" and f != [])
    pct = min(100, int(filled / len(fields) * 100))
    skills_count = len(w.get("skills", [])) if isinstance(w.get("skills"), (list, tuple)) else 0
    return {"applications": len(apps.data or []), "saved_jobs": len(saved.data or []), "completion": pct, "skills_count": skills_count}

# ==================== Freelance Services ====================

@app.get("/worker/freelance", response_class=HTMLResponse)
async def worker_freelance_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "worker": return RedirectResponse("/", status_code=302)
    return render_template(request, "worker/freelance.html", user=user, worker=profile["data"])

@app.post("/api/worker/freelance/save")
async def save_freelance_settings(request: Request, available: bool = Form(False), hourly_rate: int = Form(0), freelance_desc: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        supabase_admin.table("workers").update({
            "available_for_freelance": available, "hourly_rate": hourly_rate,
            "freelance_desc": freelance_desc
        }).eq("user_id", user["sub"]).execute()
        return {"success": True, "message": "تم حفظ الإعدادات"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/api/workers/freelance")
async def get_freelance_workers(skill: str = "", city: str = ""):
    try:
        query = supabase.table("workers").select("*").eq("is_approved", True).eq("available_for_freelance", True)
        if city:
            query = query.eq("city", city)
        result = query.order("created_at", desc=True).execute()
        workers = result.data or []
        if skill:
            sl = skill.lower()
            workers = [w for w in workers if sl in str(w.get("skills", [])).lower()]
        return {"data": workers}
    except Exception as e:
        return JSONResponse({"data": [], "error": str(e)})

@app.get("/employer/find-workers", response_class=HTMLResponse)
async def find_workers_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": return RedirectResponse("/", status_code=302)
    return render_template(request, "employer/find_workers.html", user=user, employer=profile["data"], cities=CITIES)

# ==================== Employer Profile Routes ====================

@app.get("/employer/profile", response_class=HTMLResponse)
async def employer_profile_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": return RedirectResponse("/", status_code=302)
    return render_template(request, "employer/profile.html", user=user, employer=profile["data"])

@app.post("/api/employer/profile/save")
async def save_employer_profile(request: Request, company_name: str = Form(""), company_description: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        supabase_admin.table("employers").update({
            "company_name": company_name, "company_description": company_description
        }).eq("user_id", user["sub"]).execute()
        return {"success": True, "message": "تم حفظ الملف الشخصي"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/employer/profile/upload-logo")
async def upload_employer_logo(request: Request, file: UploadFile = File(...)):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    try:
        os.makedirs("app/static/uploads", exist_ok=True)
        ext = pathlib.Path(file.filename).suffix or ".png"
        filename = f"logo_{user['sub'][:8]}_{uuid.uuid4().hex[:8]}{ext}"
        content = await file.read()
        with open(f"app/static/uploads/{filename}", "wb") as f:
            f.write(content)
        url = f"/static/uploads/{filename}"
        supabase_admin.table("employers").update({"company_logo": url}).eq("user_id", user["sub"]).execute()
        return {"success": True, "url": url}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

# ==================== Notifications Routes ====================

@app.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    notifs = supabase_admin.table("notifications").select("*").eq("user_id", user["sub"]).order("created_at", desc=True).limit(50).execute()
    return render_template(request, "notifications.html", user=user, notifications=notifs.data or [])

@app.get("/api/notifications/unread")
async def unread_notifications(request: Request):
    user = await get_current_user(request)
    if not user: return {"count": 0}
    result = supabase_admin.table("notifications").select("id", count="exact").eq("user_id", user["sub"]).eq("is_read", False).execute()
    return {"count": result.count or 0}

@app.get("/api/notifications")
async def get_notifications(request: Request):
    user = await get_current_user(request)
    if not user: return {"data": []}
    result = supabase_admin.table("notifications").select("*").eq("user_id", user["sub"]).order("created_at", desc=True).limit(50).execute()
    return {"data": result.data or []}

@app.post("/api/notifications/mark-read")
async def mark_notifications_read(request: Request):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    supabase_admin.table("notifications").update({"is_read": True}).eq("user_id", user["sub"]).execute()
    return {"success": True}

# ==================== Messages Routes ====================

@app.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    return render_template(request, "messages.html", user=user)

@app.get("/api/messages/conversations")
async def get_conversations(request: Request):
    user = await get_current_user(request)
    if not user: return {"data": []}
    sent = supabase_admin.table("messages").select("*").eq("sender_id", user["sub"]).order("created_at", desc=True).execute()
    received = supabase_admin.table("messages").select("*").eq("receiver_id", user["sub"]).order("created_at", desc=True).execute()
    return {"data": (sent.data or []) + (received.data or [])}

@app.post("/api/messages/send")
async def send_message(request: Request, receiver_id: str = Form(...), content: str = Form(...), job_id: str = Form("")):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    name = ""
    if profile and profile.get("data"):
        p = profile["data"]
        name = p.get("first_name", "") + " " + p.get("last_name", "") if profile["type"] == "worker" else p.get("company_name", "") or (p.get("first_name", "") + " " + p.get("last_name", ""))
    try:
        supabase_admin.table("messages").insert({
            "sender_id": user["sub"], "sender_name": name.strip(),
            "receiver_id": receiver_id, "job_id": job_id or None,
            "content": content
        }).execute()
        # notify receiver
        await create_notification(receiver_id, "رسالة جديدة", f"لديك رسالة جديدة من {name.strip() or 'مستخدم'}", "message")
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.get("/api/messages/{user_id}")
async def get_messages_with(request: Request, user_id: str):
    user = await get_current_user(request)
    if not user: return {"data": []}
    result = supabase_admin.table("messages").select("*").or_(
        f"and(sender_id.eq.{user['sub']},receiver_id.eq.{user_id})",
        f"and(sender_id.eq.{user_id},receiver_id.eq.{user['sub']})"
    ).order("created_at").execute()
    supabase_admin.table("messages").update({"is_read": True}).eq("sender_id", user_id).eq("receiver_id", user["sub"]).execute()
    return {"data": result.data or []}

# ==================== Add notifications to existing routes ====================

# Override apply to include notification
@app.post("/api/worker/apply/{job_id}")
async def apply_job_with_notif(request: Request, job_id: str):
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
    # Notify employer
    job = supabase.table("jobs").select("*, employers(*)").eq("id", job_id).single().execute()
    if job.data and job.data.get("employers") and job.data["employers"].get("user_id"):
        wname = f"{profile['data'].get('first_name','')} {profile['data'].get('last_name','')}"
        await create_notification(job.data["employers"]["user_id"], "تقدم جديد", f"تقدم {wname.strip() or 'عامل'} لفرصة '{job.data.get('title','')}'", "application")
    return {"success": True, "message": "تم التقديم على الفرصة بنجاح"}

@app.post("/api/employer/accept-application/{application_id}")
async def accept_application_with_notif(request: Request, application_id: str):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        app_data = supabase.table("applications").select("*, workers(*), jobs(*)").eq("id", application_id).single().execute()
        if app_data.data:
            supabase_admin.table("applications").update({"status": "accepted"}).eq("id", application_id).execute()
            if app_data.data.get("workers") and app_data.data["workers"].get("user_id"):
                await create_notification(app_data.data["workers"]["user_id"], "تم قبول طلبك", f"تم قبول طلبك لفرصة '{app_data.data.get('jobs',{}).get('title','')}'", "success")
        return {"success": True, "message": "تم قبول المتقدم"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/employer/reject-application/{application_id}")
async def reject_application_with_notif(request: Request, application_id: str):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    try:
        app_data = supabase.table("applications").select("*, workers(*), jobs(*)").eq("id", application_id).single().execute()
        if app_data.data:
            supabase_admin.table("applications").update({"status": "rejected"}).eq("id", application_id).execute()
            if app_data.data.get("workers") and app_data.data["workers"].get("user_id"):
                await create_notification(app_data.data["workers"]["user_id"], "تم رفض طلبك", f"نأسف، تم رفض طلبك لفرصة '{app_data.data.get('jobs',{}).get('title','')}'", "error")
        return {"success": True, "message": "تم رفض المتقدم"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

# ==================== Enhanced Admin Routes ====================

@app.post("/api/admin/verify-employer/{employer_id}")
async def verify_employer(request: Request, employer_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    supabase_admin.table("employers").update({"is_verified": True}).eq("id", employer_id).execute()
    return {"success": True}

@app.post("/api/admin/unverify-employer/{employer_id}")
async def unverify_employer(request: Request, employer_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    supabase_admin.table("employers").update({"is_verified": False}).eq("id", employer_id).execute()
    return {"success": True}

@app.post("/api/admin/delete-employer/{employer_id}")
async def delete_employer(request: Request, employer_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    try:
        supabase_admin.table("jobs").delete().eq("employer_id", employer_id).execute()
        supabase_admin.table("employers").delete().eq("id", employer_id).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

# ==================== Admin Client Management ====================

@app.get("/api/admin/clients")
async def admin_clients(request: Request):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    workers = supabase.table("workers").select("*").order("created_at", desc=True).execute()
    employers = supabase.table("employers").select("*").order("created_at", desc=True).execute()
    all_clients = []
    for w in workers.data or []:
        wb = supabase_admin.table("wallets").select("balance").eq("user_id", w["user_id"]).execute()
        all_clients.append({
            "id": w["id"], "user_id": w["user_id"],
            "email": w.get("email", ""), "name": f"{w.get('first_name','')} {w.get('last_name','')}".strip(),
            "type": "worker", "is_approved": w.get("is_approved", False),
            "phone": w.get("phone", ""), "city": w.get("city", ""),
            "created_at": w.get("created_at", ""),
            "wallet_balance": wb.data[0]["balance"] if wb.data else 0,
            "has_id_front": bool(w.get("id_image_front")), "has_id_back": bool(w.get("id_image_back")),
            "id_image_front": w.get("id_image_front",""), "id_image_back": w.get("id_image_back",""),
            "profile": {"gender": w.get("gender",""), "nationality": w.get("nationality",""), "bio": w.get("bio",""), "age": w.get("age","")}
        })
    for e in employers.data or []:
        eb = supabase_admin.table("wallets").select("balance").eq("user_id", e["user_id"]).execute()
        all_clients.append({
            "id": e["id"], "user_id": e["user_id"],
            "email": e.get("email", ""), "name": e.get("company_name", "") or f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
            "type": "employer", "is_verified": e.get("is_verified", False),
            "phone": e.get("phone", ""), "city": e.get("city", ""),
            "created_at": e.get("created_at", ""),
            "wallet_balance": eb.data[0]["balance"] if eb.data else 0
        })
    return {"data": all_clients}

@app.post("/api/admin/delete-client/{user_id}")
async def admin_delete_client(request: Request, user_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    try:
        jobs = supabase_admin.table("jobs").select("id").eq("employer_id", user_id).execute()
        job_ids = [j["id"] for j in (jobs.data or [])]
        for jid in job_ids:
            supabase_admin.table("applications").delete().eq("job_id", jid).execute()
        supabase_admin.table("jobs").delete().eq("employer_id", user_id).execute()
        supabase_admin.table("applications").delete().eq("worker_id", user_id).execute()
        workers_del = supabase_admin.table("workers").select("id").eq("user_id", user_id).execute()
        if workers_del.data:
            for w in workers_del.data:
                supabase_admin.table("saved_jobs").delete().eq("worker_id", w["id"]).execute()
        supabase_admin.table("workers").delete().eq("user_id", user_id).execute()
        supabase_admin.table("employers").delete().eq("user_id", user_id).execute()
        supabase_admin.table("wallets").delete().eq("user_id", user_id).execute()
        supabase_admin.table("notifications").delete().eq("user_id", user_id).execute()
        supabase_admin.table("messages").delete().or_(f"sender_id.eq.{user_id},receiver_id.eq.{user_id}").execute()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(
                    f"https://{SUPABASE_PROJECT_REF}.supabase.co/auth/v1/admin/users/{user_id}",
                    headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY}
                )
        except:
            pass
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

# ==================== Payment Methods ====================

@app.get("/api/admin/payment-methods")
async def get_payment_methods(request: Request):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    result = supabase_admin.table("payment_methods").select("*").order("created_at", desc=True).execute()
    return {"data": result.data or []}

@app.post("/api/admin/payment-methods")
async def add_payment_method(request: Request, currency: str = Form(...), network: str = Form(...), wallet_address: str = Form(...)):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    try:
        supabase_admin.table("payment_methods").insert({
            "currency": currency, "network": network, "wallet_address": wallet_address
        }).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

@app.post("/api/admin/payment-methods/{pm_id}/delete")
async def delete_payment_method(request: Request, pm_id: str):
    user = await get_current_user(request)
    if not user or user.get("email") != "admin@sanad.com": raise HTTPException(403)
    supabase_admin.table("payment_methods").delete().eq("id", pm_id).execute()
    return {"success": True}

@app.get("/api/payment-methods")
async def get_payment_methods_public():
    result = supabase_admin.table("payment_methods").select("*").eq("is_active", True).execute()
    return {"data": result.data or []}

# ==================== Employer Stats API ====================

@app.get("/api/employer/stats")
async def employer_stats_api(request: Request):
    user = await get_current_user(request)
    if not user: raise HTTPException(401)
    profile = await get_user_profile(user["sub"])
    if not profile or profile["type"] != "employer": raise HTTPException(403)
    eid = profile["data"]["id"]
    jobs = supabase.table("jobs").select("*").eq("employer_id", eid).execute()
    active = [j for j in (jobs.data or []) if j.get("status") == "open"]
    total_apps = 0
    pending_apps = 0
    for j in jobs.data or []:
        apps = supabase.table("applications").select("id,status").eq("job_id", j["id"]).execute()
        total_apps += len(apps.data or [])
        pending_apps += sum(1 for a in (apps.data or []) if a.get("status") == "pending")
    return {"active_jobs": len(active), "total_applications": total_apps, "pending_applications": pending_apps}

@app.get("/api/set-lang/{lang}")
async def set_lang(lang: str):
    response = RedirectResponse(url="/")
    if lang in ("ar", "en"):
        response.set_cookie(key="lang", value=lang, max_age=365*24*3600, path="/")
    return response

@app.get("/deposit", response_class=HTMLResponse)
async def deposit_page(request: Request):
    user = await get_current_user(request)
    if not user: return RedirectResponse("/login", status_code=302)
    methods = supabase_admin.table("payment_methods").select("*").eq("is_active", True).execute()
    wallet = await get_wallet(user["sub"])
    return render_template(request, "deposit.html", user=user, wallet=wallet, payment_methods=methods.data or [])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
