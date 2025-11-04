import os
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document
from schemas import Student, Internship, MatchRequest

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static directory for uploaded resumes
UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class AuthResponse(BaseModel):
    name: str
    email: EmailStr
    preferences: List[str]
    resume_url: Optional[str] = None

@app.get("/")
def read_root():
    return {"message": "Inter-India Backend Running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_name"] = getattr(db, "name", "✅ Connected")
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

# Utility functions

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

# Auth + Profile (register or sign in + update preferences/resume)
@app.post("/auth/signin", response_model=AuthResponse)
async def signin(
    email: EmailStr = Form(...),
    password: str = Form(...),
    name: Optional[str] = Form(None),
    preferences: Optional[str] = Form(None),  # Comma separated
    resume: Optional[UploadFile] = File(None),
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    users = db["student"]
    user = users.find_one({"email": str(email)})

    pref_list: List[str] = []
    if preferences:
        pref_list = [p.strip() for p in preferences.split(",") if p.strip()]

    resume_url: Optional[str] = None

    # If user exists -> verify password and update profile
    if user:
        if not verify_password(password, user.get("password_hash", "")):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        update: dict = {}
        if name and name != user.get("name"):
            update["name"] = name
        if pref_list:
            update["preferences"] = pref_list
        if resume is not None:
            file_path = os.path.join(UPLOAD_DIR, f"{user['_id']}_{resume.filename}")
            with open(file_path, "wb") as f:
                f.write(await resume.read())
            resume_url = f"/uploads/{os.path.basename(file_path)}"
            update["resume_url"] = resume_url
        if update:
            update["updated_at"] = __import__("datetime").datetime.utcnow()
            users.update_one({"_id": user["_id"]}, {"$set": update})
            user.update(update)
        return AuthResponse(
            name=user.get("name", name or ""),
            email=email,
            preferences=user.get("preferences", pref_list),
            resume_url=user.get("resume_url", resume_url),
        )

    # New user -> create
    if not name:
        raise HTTPException(status_code=400, detail="Name is required for new users")
    password_hash = hash_password(password)
    new_user = Student(
        name=name,
        email=email,
        password_hash=password_hash,
        preferences=pref_list,
        resume_url=None,
        role="student",
    )
    user_id = create_document("student", new_user)

    if resume is not None:
        file_path = os.path.join(UPLOAD_DIR, f"{user_id}_{resume.filename}")
        with open(file_path, "wb") as f:
            f.write(await resume.read())
        resume_url = f"/uploads/{os.path.basename(file_path)}"
        users.update_one({"_id": ObjectId(user_id)}, {"$set": {"resume_url": resume_url}})

    return AuthResponse(name=name, email=email, preferences=pref_list, resume_url=resume_url)

# Seed internships for demo
@app.post("/seed/internships")
def seed_internships():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    col = db["internship"]
    if col.count_documents({}) > 0:
        return {"status": "ok", "message": "Internships already seeded"}
    samples: List[Internship] = [
        Internship(title="Data Analyst Intern", company="Insight Labs", description="Work with data pipelines and dashboards", location="Remote", stipend="₹15,000", skills=["python", "sql", "pandas", "analytics"]),
        Internship(title="Frontend Developer Intern", company="WebWorks", description="Build UI components with React", location="Delhi", stipend="₹12,000", skills=["react", "javascript", "css", "ui"]),
        Internship(title="Cybersecurity Intern", company="SecureNet", description="Assist in vulnerability assessments", location="Bangalore", stipend="₹18,000", skills=["security", "network", "linux", "python"]),
        Internship(title="Machine Learning Intern", company="AI Forge", description="Model training and experimentation", location="Remote", stipend="₹20,000", skills=["ml", "python", "scikit", "numpy"]),
        Internship(title="Backend Developer Intern", company="CloudStack", description="APIs and microservices", location="Hyderabad", stipend="₹17,000", skills=["python", "fastapi", "mongodb", "docker"]),
    ]
    for s in samples:
        create_document("internship", s)
    return {"status": "ok", "message": "Seeded internships"}

# Matching endpoint
class MatchResult(BaseModel):
    score: float
    internship: Internship

@app.post("/match/top", response_model=List[MatchResult])
def match_top(req: MatchRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    user = db["student"].find_one({"email": str(req.email)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_prefs: List[str] = [s.lower() for s in user.get("preferences", [])]

    internships = list(db["internship"].find({}))

    def score(intern: dict) -> float:
        skills = [s.lower() for s in intern.get("skills", [])]
        if not skills:
            return 0.0
        overlap = len(set(skills) & set(user_prefs))
        pref_cov = overlap / max(1, len(set(user_prefs))) if user_prefs else 0
        skill_cov = overlap / max(1, len(set(skills)))
        # Weighted: preferences 60%, skill coverage 40%
        return round(0.6 * pref_cov + 0.4 * skill_cov, 4)

    scored = [
        MatchResult(score=score(i), internship=Internship(
            title=i.get("title"),
            company=i.get("company"),
            description=i.get("description"),
            location=i.get("location"),
            stipend=i.get("stipend"),
            skills=i.get("skills", []),
        ))
        for i in internships
    ]

    scored.sort(key=lambda x: x.score, reverse=True)
    top = [s for s in scored if s.score > 0][: req.limit]
    return top

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
