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


SMTP_SERVER=os.getenv("smtp_server")
SMTP_PORT=os.getenv("smtp_port")
SMTP_USER=os.getenv("smtp_user")
SMTP_PASSWORD=os.getenv("smtp_pass")

COM_SMTP_SERVER=os.getenv("com_smtp_server")
COM_SMTP_PORT=os.getenv("com_smtp_port")
COM_SMTP_USER=os.getenv("com_smtp_user")
COM_SMTP_PASSWORD=os.getenv("com_smtp_pass")


WHATSAPP_ACCESS_TOKEN=os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID=os.getenv("PHONE_NUMBER_ID")


SMS_API_URL = os.getenv("SMS_API_URL")
SMS_AUTHKEY = os.getenv("SMS_AUTHKEY")
DLT_TE_ID = os.getenv("DLT_TE_ID")
SENDER_ID = os.getenv("SENDER_ID")
ROUTE = os.getenv("ROUTE")
COUNTRY = os.getenv("COUNTRY")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "crm_db")
DB_USERNAME = os.getenv("DB_USERNAME", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")