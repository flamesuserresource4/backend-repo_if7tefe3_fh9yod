from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional

class Student(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="BCrypt password hash")
    preferences: List[str] = Field(default_factory=list, description="Preferred skills or domains")
    resume_url: Optional[str] = Field(None, description="Public URL for uploaded resume")
    role: str = Field("student", description="Role of the user")

class Internship(BaseModel):
    title: str
    company: str
    description: Optional[str] = None
    location: Optional[str] = None
    stipend: Optional[str] = None
    skills: List[str] = Field(default_factory=list, description="Required skills/keywords")

class MatchRequest(BaseModel):
    email: EmailStr
    limit: int = 5
