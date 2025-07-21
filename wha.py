import requests
import json

class WhatsAppBusinessAPI:
    def __init__(self, access_token, phone_number_id):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = "https://graph.facebook.com/v17.0"

    def send_payment_template(self, to_phone, customer_name, amount, payment_link):
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": "cashfree_pay",
                "language": {"code": "en"},
                "components": [
                    # 1) Header (named placeholder: customer_name)
                    {
                        "type": "header",
                        "parameters": [
                            {
                                "type": "text",
                                "text": customer_name,
                                "name": "customer_name"
                            }
                        ]
                    },
                    # 2) Body (named placeholder: payment_amount)
                    {
                        "type": "body",
                        "parameters": [
                            {
                                "type": "text",
                                "text": str(amount),
                                "name": "payment_amount"
                            }
                        ]
                    },
                    # 3) URL button (named placeholder: payment_link)
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": 0,
                        "parameters": [
                            {
                                "type": "text",
                                "text": payment_link,
                                "name": "payment_link"
                            }
                        ]
                    }
                ]
            }
        }

        print("Sending template:", json.dumps(payload, indent=2))
        resp = requests.post(url, headers=headers, json=payload)
        print(resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()

# Usage
if __name__ == "__main__":
    api = WhatsAppBusinessAPI(
        access_token="EAAIU4R08QAEBPEpfaczkfSFx2RPFZBZCj7JozJ2s7KzZAxaeO33gbA0G4fh2XkVWZBmPuwZBivjHzF4ZBOT3gMc8yjQro5AS5puRH1wNepRriqZAy2ZAZCIHZBN4RtUB7U97IBGaBh64ClPghzNI3tJkMjpZAZA2wIXeikKJKOhCFlUH8t5mN0ZAeLnGs93dUZCwmZCrE65INZCxpI9cWdugaJePE3zd36dn7vbZB9d7hGb0aWhkG60EWxuZBKA5fxE4tXQm8ZD",
        phone_number_id="712120695307063"
    )

    result = api.send_payment_template(
        to_phone="917869615290",
        customer_name="Raj Malviya",
        amount=25000,
        payment_link="https://api.cashfree.com/pg/view/sessions/checkout/web/pk8yEVukbhtWG2Numjvx"
    )
    print("Template result:", result)
