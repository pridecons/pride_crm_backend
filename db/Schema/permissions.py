from typing import Optional, Dict, Any, List
from pydantic import BaseModel
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

    manage_add_lead      : Optional[bool] = None
    manage_source_lead      : Optional[bool] = None
    manage_response_lead      : Optional[bool] = None
    manage_fetch_limit      : Optional[bool] = None
    manage_bulk_upload      : Optional[bool] = None


    # Lead[id] :- 
    lead_recording_view      : Optional[bool] = None
    lead_recording_upload      : Optional[bool] = None
    lead_transfer      : Optional[bool] = None

    # Users :-
    user_add      : Optional[bool] = None
    user_branch_filter      : Optional[bool] = None


    # Rational :-
    rational_export_pdf      : Optional[bool] = None
    rational_export_xls      : Optional[bool] = None
    rational_add_rational      : Optional[bool] = None


    # Services :-
    service_create      : Optional[bool] = None
    service_edit      : Optional[bool] = None
    service_delete      : Optional[bool] = None

    # Email :-
    email_add_temp  : Optional[bool] = None
    email_view_temp : Optional[bool] = None
    email_edit_temp : Optional[bool] = None
    email_delete_temp : Optional[bool] = None
