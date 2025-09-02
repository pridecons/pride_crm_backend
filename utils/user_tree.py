# services/user_tree.py
from typing import List, Optional
from sqlalchemy.orm import Session, aliased
from sqlalchemy import select
from db.models import UserDetails

def get_subordinate_ids(
    db: Session,
    root_employee_code: str,
    include_inactive: bool = False,
) -> List[str]:
    """
    Return ALL descendant employee_codes under `root_employee_code`
    using a recursive CTE on crm_user_details.senior_profile_id.

    Example chain:
      a <- b <- c <- d <- e
    get_subordinate_ids(a) -> [b, c, d, e]
    get_subordinate_ids(b) -> [c, d, e]
    """
    # Seed: direct reports of root
    seed = (
        select(UserDetails.employee_code)
        .where(UserDetails.senior_profile_id == root_employee_code)
    )
    if not include_inactive:
        seed = seed.where(UserDetails.is_active.is_(True))

    # Recursive step: people whose senior_profile_id is any employee_code already found
    u = aliased(UserDetails)
    subordinates = seed.cte(name="subordinates", recursive=True)
    subordinates = subordinates.union_all(
        select(u.employee_code)
        .where(u.senior_profile_id == subordinates.c.employee_code)
        .where(True if include_inactive else (u.is_active.is_(True)))
    )

    # Final select: all employee_codes produced by the CTE
    rows = db.execute(select(subordinates.c.employee_code)).all()
    return [r[0] for r in rows]


def get_subordinate_users(
    db: Session,
    root_employee_code: str,
    include_inactive: bool = False,
) -> List[UserDetails]:
    """
    Same as above but returns full UserDetails rows.
    """
    # Reuse the CTE to build a subquery and join back to the table
    seed = (
        select(UserDetails.employee_code)
        .where(UserDetails.senior_profile_id == root_employee_code)
    )
    if not include_inactive:
        seed = seed.where(UserDetails.is_active.is_(True))

    u = aliased(UserDetails)
    subordinates = seed.cte(name="subordinates", recursive=True)
    subordinates = subordinates.union_all(
        select(u.employee_code)
        .where(u.senior_profile_id == subordinates.c.employee_code)
        .where(True if include_inactive else (u.is_active.is_(True)))
    )

    stmt = (
        select(UserDetails)
        .where(UserDetails.employee_code.in_(select(subordinates.c.employee_code)))
        .order_by(UserDetails.employee_code)
    )
    return list(db.execute(stmt).scalars())
