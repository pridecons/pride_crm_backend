# routes/invoices.py

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Payment, Lead
from pydantic import BaseModel
import io
import os
import zipfile
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/invoices", tags=["invoices"])


class PaymentInvoiceOut(BaseModel):
    id: int
    lead_id: Optional[int]
    invoice_path: Optional[str]   # stored in Payment.invoice
    invoice_no: Optional[str]
    paid_amount: float
    status: Optional[str]
    order_id: Optional[str]
    transaction_id: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


@router.get(
    "/lead/{lead_id}",
    response_model=List[PaymentInvoiceOut],
    summary="Get all invoice‐PDF paths for a specific lead"
)
def get_payment_invoices_by_lead(
    lead_id: int,
    db: Session = Depends(get_db),
):
    payments = (
        db.query(Payment)
          .filter(Payment.lead_id == lead_id, Payment.invoice.isnot(None))
          .order_by(Payment.created_at.desc())
          .all()
    )
    if not payments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No payment invoices found for lead {lead_id}"
        )
    return [
        PaymentInvoiceOut(
            id=p.id,
            lead_id=p.lead_id,
            invoice_path=p.invoice,
            invoice_no=p.invoice_no,
            paid_amount=p.paid_amount,
            status=p.status,
            order_id=p.order_id,
            transaction_id=p.transaction_id,
            created_at=p.created_at,
        )
        for p in payments
    ]


@router.get(
    "/",
    response_model=List[PaymentInvoiceOut],
    summary="Get all payment-based invoices (PDF paths) with filters + pagination"
)
def get_payment_invoices(
    # pagination
    skip: int = Query(0, ge=0, description="Records to skip"),
    limit: int = Query(100, gt=0, description="Max records to return"),

    # filters
    lead_id:        Optional[int]  = Query(None, description="Filter by lead ID"),
    from_date:      Optional[date] = Query(None, description="created_at ≥ this date (YYYY-MM-DD)"),
    to_date:        Optional[date] = Query(None, description="created_at ≤ this date (YYYY-MM-DD)"),
    status:         Optional[str]  = Query(None, description="Filter by payment status (e.g. 'PAID')"),
    min_amount:     Optional[float]= Query(None, description="paid_amount ≥ this value"),
    max_amount:     Optional[float]= Query(None, description="paid_amount ≤ this value"),
    branch_id:      Optional[int]  = Query(None, description="Filter by branch_id of the lead"),

    db: Session = Depends(get_db),
):
    """
    Returns all payments that have an invoice PDF (invoice column non-null),
    with optional filters and pagination.
    """
    query = db.query(Payment).filter(Payment.invoice.isnot(None))

    if lead_id is not None:
        query = query.filter(Payment.lead_id == lead_id)

    if from_date:
        query = query.filter(Payment.created_at.cast(date) >= from_date)
    if to_date:
        query = query.filter(Payment.created_at.cast(date) <= to_date)

    if status:
        query = query.filter(Payment.status == status)

    if min_amount is not None:
        query = query.filter(Payment.paid_amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Payment.paid_amount <= max_amount)

    if branch_id is not None:
        query = query.join(Lead, Payment.lead_id == Lead.id).filter(Lead.branch_id == branch_id)

    payments = (
        query
        .order_by(Payment.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return [
        PaymentInvoiceOut(
            id=p.id,
            lead_id=p.lead_id,
            invoice_path=p.invoice,
            invoice_no=p.invoice_no,
            paid_amount=p.paid_amount,
            status=p.status,
            order_id=p.order_id,
            transaction_id=p.transaction_id,
            created_at=p.created_at,
        )
        for p in payments
    ]


@router.get(
    "/export-zip",
    summary="Export filtered invoice PDFs as a ZIP archive"
)
def export_invoices_zip(
    # same filters as get_payment_invoices
    lead_id:        Optional[int]  = Query(None, description="Filter by lead ID"),
    from_date:      Optional[date] = Query(None, description="created_at ≥ this date (YYYY-MM-DD)"),
    to_date:        Optional[date] = Query(None, description="created_at ≤ this date (YYYY-MM-DD)"),
    status:         Optional[str]  = Query(None, description="Filter by payment status"),
    min_amount:     Optional[float]= Query(None, description="paid_amount ≥ this value"),
    max_amount:     Optional[float]= Query(None, description="paid_amount ≤ this value"),
    branch_id:      Optional[int]  = Query(None, description="Filter by branch_id of the lead"),

    db: Session = Depends(get_db),
):
    """
    Fetches all payments matching the filters that have a non-null `invoice` path,
    bundles the PDF files into a ZIP, and streams it back.
    """
    query = db.query(Payment).filter(Payment.invoice.isnot(None))

    if lead_id is not None:
        query = query.filter(Payment.lead_id == lead_id)
    if from_date:
        query = query.filter(Payment.created_at.cast(date) >= from_date)
    if to_date:
        query = query.filter(Payment.created_at.cast(date) <= to_date)
    if status:
        query = query.filter(Payment.status == status)
    if min_amount is not None:
        query = query.filter(Payment.paid_amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Payment.paid_amount <= max_amount)
    if branch_id is not None:
        query = query.join(Lead, Payment.lead_id == Lead.id).filter(Lead.branch_id == branch_id)

    payments = query.all()
    if not payments:
        raise HTTPException(status_code=404, detail="No invoices found for given filters")

    # Create in-memory ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for p in payments:
            # p.invoice holds the file path, e.g. "/static/lead_docs/lead_123_invoice_abc.pdf"
            file_path = p.invoice.lstrip("/")  # remove leading slash if present
            if os.path.isfile(file_path):
                zipf.write(file_path, arcname=os.path.basename(file_path))

    zip_buffer.seek(0)
    filename = f"invoices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
