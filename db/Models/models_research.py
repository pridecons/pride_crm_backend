# db/models_research.py
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

# ✅ Share the SAME Base/MetaData as your core models
from db.models import UserDetails  # make sure UserDetails.__tablename__ is 'crm_user_details'
from db.connection import Base

class ResearchReport(Base):
    __tablename__ = "research_reports"

    id = Column(Integer, primary_key=True)
    # store who created the report
    created_by = Column(
        String(50),
        ForeignKey("crm_user_details.employee_code", ondelete="SET NULL"),
        nullable=True,
    )

    # optional relationship to show creator details
    created_by_user = relationship(
        "UserDetails",
        primaryjoin="UserDetails.employee_code==ResearchReport.created_by",
        lazy="joined",
        viewonly=True,
    )

    # … your other optional research fields …
    # Example fields:
    report_date = Column(Date, nullable=True)
    section_ipo = Column(Text, nullable=True)
    section_board_meeting = Column(Text, nullable=True)
    section_corporate_action = Column(Text, nullable=True)
    section_result_calendar = Column(Text, nullable=True)
    section_support_registration = Column(Text, nullable=True)
    section_disclaimer = Column(Text, nullable=True)
    section_top_gainer_loser = Column(Text, nullable=True)
    section_fii_dii = Column(Text, nullable=True)
    section_calls_json = Column(Text, nullable=True)   # store JSON string

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
