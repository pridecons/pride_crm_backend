from dotenv import load_dotenv
import os
import logging
import json

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

CASHFREE_APP_ID=os.getenv("CASHFREE_APP_ID")
CASHFREE_SECRET_KEY=os.getenv("CASHFREE_SECRET_KEY")
CASHFREE_PRODUCTION=os.getenv("CASHFREE_PRODUCTION")

PAN_API_KEY=os.getenv("PAN_API_KEY")
PAN_API_ID=os.getenv("PAN_API_ID")
PAN_TASK_ID_1=os.getenv("PAN_TASK_ID_1")
PAN_TASK_ID_2=os.getenv("PAN_TASK_ID_2")


