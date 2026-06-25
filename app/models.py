from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class UserRegister(BaseModel):
    email: str
    password: str
    role: str = Field(pattern="^(worker|employer)$")
    first_name: str
    last_name: str
    phone: str
    gender: str = Field(pattern="^(ذكر|أنثى)$")
    nationality: str
    city: str

class UserLogin(BaseModel):
    email: str
    password: str

class WorkerProfile(BaseModel):
    first_name: str
    last_name: str
    age: int = Field(ge=18, le=100)
    gender: str = Field(pattern="^(ذكر|أنثى)$")
    nationality: str
    phone: str
    city: str

class JobCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    work_type: str
    duration: str
    pay: float = Field(gt=0)
    phone: str
    address: str
    city: str
    notes: Optional[str] = ""
