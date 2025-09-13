# db/Models/models_VBC.py
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
from db.connection import Base

class VBCReport(Base):
    __tablename__ = "crm_vbc_reports"

    id = Column(String(150), primary_key=True)
    in_network = Column(String(100), nullable=True)
    international = Column(String(100), nullable=True)
    extension_id = Column(String(100), nullable=True) #from
    to = Column(String(100), nullable=True)
    direction = Column(String(100), nullable=True)
    length = Column(String(100), nullable=True)
    start = Column(String(100), nullable=True)
    end = Column(String(100), nullable=True)
    charge = Column(String(100), nullable=True)
    rate = Column(String(100), nullable=True)
    destination_device_name = Column(String(100), nullable=True)
    source_device_name = Column(String(100), nullable=True)
    destination_user_full_name = Column(String(100), nullable=True)
    destination_user = Column(String(100), nullable=True)
    destination_sip_id = Column(String(100), nullable=True)
    destination_extension = Column(String(100), nullable=True)
    source_user_full_name = Column(String(100), nullable=True)
    source_user = Column(String(100), nullable=True)
    custom_tag = Column(String(100), nullable=True)
    source_sip_id = Column(String(100), nullable=True)
    source_extension = Column(String(100), nullable=True)
    result = Column(String(100), nullable=True)
    recorded = Column(String(100), nullable=True)
        