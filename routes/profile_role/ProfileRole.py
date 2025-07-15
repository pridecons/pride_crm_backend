from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import UserRoleEnum

router = APIRouter(
    prefix="/profile-role",
    tags=["Profile Role"],
)

@router.get("/", response_model=List[str])
def get_all_permissions(db: Session = Depends(get_db)):
    """
    Returns a list of all user roles.
    """
    return [role.value for role in UserRoleEnum]


