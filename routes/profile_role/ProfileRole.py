from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import RecommendationType

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, constr
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, asc, desc

# ---- import your app bits ----------------------------------------------------
# Adjust these imports to your project layout
from db.connection import get_db
from db.models import Department, ProfileRole  # your models from the snippet

# -----------------------------------------------------------------------------
# Pydantic Schemas
# -----------------------------------------------------------------------------
# Department
class DepartmentBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=2, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = True
    available_permissions: Optional[List[str]] = Field(default_factory=list)

class DepartmentCreate(DepartmentBase):
    pass

class DepartmentUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=2, max_length=100)] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    available_permissions: Optional[List[str]] = None

class DepartmentOut(DepartmentBase):
    id: int

    class Config:
        from_attributes = True


# ProfileRole
class ProfileRoleBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=2, max_length=100)
    department_id: int
    hierarchy_level: int = Field(..., ge=1)
    default_permissions: Optional[List[str]] = Field(default_factory=list)
    description: Optional[str] = None
    is_active: Optional[bool] = True

class ProfileRoleCreate(ProfileRoleBase):
    pass

class ProfileRoleUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=2, max_length=100)] = None
    department_id: Optional[int] = None
    hierarchy_level: Optional[int] = Field(default=None, ge=1)
    default_permissions: Optional[List[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class ProfileRoleOut(ProfileRoleBase):
    id: int

    class Config:
        from_attributes = True


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def apply_ordering(query, model, order_by: Optional[str]):
    """
    order_by pattern: "field" (asc) or "-field" (desc).
    Example: "name" or "-created_at"
    """
    if not order_by:
        return query

    field_name = order_by.lstrip("-")
    is_desc = order_by.startswith("-")

    if not hasattr(model, field_name):
        return query  # ignore unknown fields

    column = getattr(model, field_name)
    return query.order_by(desc(column) if is_desc else asc(column))


# -----------------------------------------------------------------------------
# Routers
# -----------------------------------------------------------------------------
departments_router = APIRouter(prefix="/departments", tags=["departments"])
profiles_router = APIRouter(prefix="/profile-role", tags=["profiles"])


# =============================================================================
# Departments CRUD
# =============================================================================
@departments_router.get("/", response_model=List[DepartmentOut])
def list_departments(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(default=None, description="Search in name/description"),
    is_active: Optional[bool] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    order_by: Optional[str] = Query(default="name", description='e.g., "name" or "-created_at"'),
):
    q = db.query(Department)

    if search:
        s = f"%{search}%"
        q = q.filter(or_(Department.name.ilike(s), Department.description.ilike(s)))

    if is_active is not None:
        q = q.filter(Department.is_active == is_active)

    q = apply_ordering(q, Department, order_by)
    return q.offset(skip).limit(limit).all()


@departments_router.get("/{dept_id}", response_model=DepartmentOut)
def get_department(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(Department).get(dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


@departments_router.post("/", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db)):
    # unique name guard (DB has unique=True, but we give nicer error)
    if db.query(Department).filter(Department.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Department name already exists")

    dept = Department(
        name=payload.name.strip(),
        description=payload.description,
        is_active=True if payload.is_active is None else payload.is_active,
        available_permissions=payload.available_permissions or [],
    )

    db.add(dept)
    try:
        db.commit()
        db.refresh(dept)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Integrity error creating Department")

    return dept


@departments_router.patch("/{dept_id}", response_model=DepartmentOut)
def update_department(dept_id: int, payload: DepartmentUpdate, db: Session = Depends(get_db)):
    dept = db.query(Department).get(dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    if payload.name and payload.name.strip() != dept.name:
        if db.query(Department).filter(Department.name == payload.name.strip()).first():
            raise HTTPException(status_code=400, detail="Department name already exists")

    for field, value in payload.dict(exclude_unset=True).items():
        setattr(dept, field, value if field != "name" else value.strip())

    try:
        db.commit()
        db.refresh(dept)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Integrity error updating Department")

    return dept


@departments_router.delete("/{dept_id}")
def delete_department(
    dept_id: int,
    db: Session = Depends(get_db),
    hard_delete: bool = Query(default=False, description="If true, permanently delete; else soft delete (is_active=False)"),
):
    dept = db.query(Department).get(dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    if hard_delete:
        # optionally you can protect if it has profiles/users
        db.delete(dept)
    else:
        dept.is_active = False

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Integrity error deleting Department")

    return {"message": "Department deleted" if hard_delete else "Department deactivated"}


# =============================================================================
# ProfileRole CRUD
# =============================================================================
@profiles_router.get("/", response_model=List[ProfileRoleOut])
def list_profiles(
    db: Session = Depends(get_db),
    department_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None, description="Search in name/description"),
    is_active: Optional[bool] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    order_by: Optional[str] = Query(default="hierarchy_level", description='e.g., "hierarchy_level" or "-created_at"'),
):
    q = db.query(ProfileRole)

    if department_id is not None:
        q = q.filter(ProfileRole.department_id == department_id)

    if search:
        s = f"%{search}%"
        q = q.filter(or_(ProfileRole.name.ilike(s), ProfileRole.description.ilike(s)))

    if is_active is not None:
        q = q.filter(ProfileRole.is_active == is_active)

    q = apply_ordering(q, ProfileRole, order_by)
    return q.offset(skip).limit(limit).all()


@profiles_router.get("/{profile_id}", response_model=ProfileRoleOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    pr = db.query(ProfileRole).get(profile_id)
    if not pr:
        raise HTTPException(status_code=404, detail="ProfileRole not found")
    return pr


@profiles_router.post("/", response_model=ProfileRoleOut, status_code=status.HTTP_201_CREATED)
def create_profile(payload: ProfileRoleCreate, db: Session = Depends(get_db)):
    # Department must exist & be active (optional active check)
    dept = db.query(Department).get(payload.department_id)
    if not dept:
        raise HTTPException(status_code=400, detail="Invalid department_id")

    # Unique name guard
    if db.query(ProfileRole).filter(ProfileRole.name == payload.name.strip()).first():
        raise HTTPException(status_code=400, detail="ProfileRole name already exists")

    pr = ProfileRole(
        name=payload.name.strip(),
        department_id=payload.department_id,
        hierarchy_level=payload.hierarchy_level,
        default_permissions=payload.default_permissions or [],
        description=payload.description,
        is_active=True if payload.is_active is None else payload.is_active,
    )

    db.add(pr)
    try:
        db.commit()
        db.refresh(pr)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Integrity error creating ProfileRole")

    return pr


@profiles_router.patch("/{profile_id}", response_model=ProfileRoleOut)
def update_profile(profile_id: int, payload: ProfileRoleUpdate, db: Session = Depends(get_db)):
    pr = db.query(ProfileRole).get(profile_id)
    if not pr:
        raise HTTPException(status_code=404, detail="ProfileRole not found")

    data = payload.dict(exclude_unset=True)

    # name change check
    if "name" in data and data["name"] and data["name"].strip() != pr.name:
        if db.query(ProfileRole).filter(ProfileRole.name == data["name"].strip()).first():
            raise HTTPException(status_code=400, detail="ProfileRole name already exists")

    # department change check
    if "department_id" in data and data["department_id"] is not None:
        dept = db.query(Department).get(data["department_id"])
        if not dept:
            raise HTTPException(status_code=400, detail="Invalid department_id")

    # apply changes
    for field, value in data.items():
        if field == "name" and value:
            setattr(pr, field, value.strip())
        else:
            setattr(pr, field, value)

    try:
        db.commit()
        db.refresh(pr)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Integrity error updating ProfileRole")

    return pr


@profiles_router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    hard_delete: bool = Query(default=False, description="If true, permanently delete; else soft delete (is_active=False)"),
):
    pr = db.query(ProfileRole).get(profile_id)
    if not pr:
        raise HTTPException(status_code=404, detail="ProfileRole not found")

    if hard_delete:
        # Optional: prevent delete if has child profiles
        if getattr(pr, "child_profiles", None):
            if len(pr.child_profiles) > 0:
                raise HTTPException(status_code=400, detail="Cannot hard delete profile with child profiles")
        db.delete(pr)
    else:
        pr.is_active = False

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Integrity error deleting ProfileRole")

    return {"message": "ProfileRole deleted" if hard_delete else "ProfileRole deactivated"}


# -----------------------------------------------------------------------------
# (Optional) Utility endpoints
# -----------------------------------------------------------------------------
@profiles_router.get("/{profile_id}/children", response_model=List[ProfileRoleOut])
def list_children_profiles(profile_id: int, db: Session = Depends(get_db)):
    pr = db.query(ProfileRole).get(profile_id)
    if not pr:
        raise HTTPException(status_code=404, detail="ProfileRole not found")
    return pr.get_all_child_profiles(db)


@profiles_router.get("/recommendation-type", response_model=List[str])
def get_all_permissions(db: Session = Depends(get_db)):
    """
    Returns a list of all user roles.
    """
    return [role.value for role in RecommendationType]


