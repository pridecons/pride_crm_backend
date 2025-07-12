from typing import Optional, Dict, Any
from pydantic import BaseModel

# Pydantic Schemas
class PermissionBase(BaseModel):
    add_user: bool = False
    edit_user: bool = False
    delete_user: bool = False
    add_lead: bool = False
    edit_lead: bool = False
    delete_lead: bool = False
    view_users: bool = False
    view_lead: bool = False
    view_branch: bool = False
    view_accounts: bool = False
    view_research: bool = False
    view_client: bool = False
    view_payment: bool = False
    view_invoice: bool = False
    view_kyc: bool = False
    approval: bool = False
    internal_mailing: bool = False
    chatting: bool = False
    targets: bool = False
    reports: bool = False
    fetch_lead: bool = False


class PermissionCreate(PermissionBase):
    user_id: str


class PermissionUpdate(BaseModel):
    add_user: Optional[bool] = None
    edit_user: Optional[bool] = None
    delete_user: Optional[bool] = None
    add_lead: Optional[bool] = None
    edit_lead: Optional[bool] = None
    delete_lead: Optional[bool] = None
    view_users: Optional[bool] = None
    view_lead: Optional[bool] = None
    view_branch: Optional[bool] = None
    view_accounts: Optional[bool] = None
    view_research: Optional[bool] = None
    view_client: Optional[bool] = None
    view_payment: Optional[bool] = None
    view_invoice: Optional[bool] = None
    view_kyc: Optional[bool] = None
    approval: Optional[bool] = None
    internal_mailing: Optional[bool] = None
    chatting: Optional[bool] = None
    targets: Optional[bool] = None
    reports: Optional[bool] = None
    fetch_lead: Optional[bool] = None


class PermissionOut(PermissionBase):
    id: int
    user_id: str
    
    class Config:
        from_attributes = True


class BulkPermissionUpdate(BaseModel):
    permissions: Dict[str, bool]  # permission_name: boolean_value
