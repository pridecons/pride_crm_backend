import requests
import json
from config import WHATSAPP_ACCESS_TOKEN, PHONE_NUMBER_ID

async def cashfree_payment_link(number, name, payment_amount, payment_url, kyc=False):
    # API endpoint
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Payload
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": f"91{number}",  # Customer's WhatsApp number
        "type": "template",
        "template": {
            "name": "cashfree_payment_req" if kyc else "web_consent_message",  # ✅ corrected ternary
            "language": {"code": "en"},
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "customer_name",  # Template variable name
                            "text": name
                        }
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "payment_amount",
                            "text": payment_amount
                        }
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "payment_link",
                            "text": payment_url if kyc else f"/payment/consent/{payment_url}"  # ✅ corrected ternary
                        }
                    ]
                }
            ]
        }
    }

    # Send request
    response = requests.post(url, headers=headers, json=payload)

    # Print response
    print("Status Code:", response.status_code)
    print("Response:", json.dumps(response.json(), indent=2))
    return json.dumps(response.json(), indent=2)
