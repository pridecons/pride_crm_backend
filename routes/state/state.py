import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/state", tags=["State"])

state_code = {
    "JAMMU AND KASHMIR": 1,
    "HIMACHAL PRADESH": 2,
    "PUNJAB": 3,
    "CHANDIGARH": 4,
    "UTTARAKHAND": 5,
    "HARYANA": 6,
    "DELHI": 7,
    "RAJASTHAN": 8,
    "UTTAR PRADESH": 9,
    "BIHAR": 10,
    "SIKKIM": 11,
    "ARUNACHAL PRADESH": 12,
    "NAGALAND": 13,
    "MANIPUR": 14,
    "MIZORAM": 15,
    "TRIPURA": 16,
    "MEGHALAYA": 17,
    "ASSAM": 18,
    "WEST BENGAL": 19,
    "JHARKHAND": 20,
    "ODISHA": 21,
    "CHATTISGARH": 22,
    "MADHYA PRADESH": 23,
    "GUJARAT": 24,
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": 26,
    "MAHARASHTRA": 27,
    "ANDHRA PRADESH(BEFORE DIVISION)": 28,
    "KARNATAKA": 29,
    "GOA": 30,
    "LAKSHADWEEP": 31,
    "KERALA": 32,
    "TAMIL NADU": 33,
    "PUDUCHERRY": 34,
    "ANDAMAN AND NICOBAR ISLANDS": 35,
    "TELANGANA": 36,
    "ANDHRA PRADESH": 37,
    "LADAKH (NEWLY ADDED)": 38,
    "OTHER TERRITORY": 97,
    "CENTRE JURISDICTION": 99
}


@router.get("/")
def get_states():
    # Convert dictionary into a list of dicts
    states = [
        {"state_name": name, "code": code}
        for name, code in state_code.items()
    ]
    return {"states": states}
