import requests
import json

class WhatsAppBusinessAPI:
    def __init__(self, access_token, phone_number_id):
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.base_url = "https://graph.facebook.com/v17.0"
    
    def send_message(self, to_phone, message_text):
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message_text}
        }
        response = requests.post(url, headers=headers, json=data)
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print(f"Error: {response.text}")
        return response.json()

    def get_templates(self):
        """Get list of approved templates"""
        url = f"{self.base_url}/{self.phone_number_id}/message_templates"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }
        response = requests.get(url, headers=headers)
        print(f"Templates Status: {response.status_code}")
        if response.status_code == 200:
            templates = response.json()
            print("Available templates:")
            for template in templates.get('data', []):
                print(f"  - {template['name']} ({template['language']}) - Status: {template['status']}")
        else:
            print(f"Error fetching templates: {response.text}")
        return response.json()

    def send_payment_template(self, to_phone, customer_name, amount, payment_link, template_name="cashfree_pay"):
        """
        Sends the cashfree_pay template message
        Based on your template: Header + Body with variables + Pay Now button
        """
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Your template uses "English" language, try common English language codes
        language_codes = ["en", "en_US", "en_GB"]
        
        for lang_code in language_codes:
            # Template structure with header component
            payload = {
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": lang_code},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {"type": "text", "text": customer_name}
                            ]
                        },
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": customer_name},
                                {"type": "text", "text": str(amount)}
                            ]
                        },
                        {
                            "type": "button",
                            "sub_type": "url",
                            "index": 0,
                            "parameters": [
                                {"type": "text", "text": payment_link}
                            ]
                        }
                    ]
                }
            }
            
            print(f"Trying template with language: {lang_code}")
            print(f"Payload: {json.dumps(payload, indent=2)}")
            
            resp = requests.post(url, headers=headers, json=payload)
            print(f"Status: {resp.status_code}")
            
            if resp.status_code == 200:
                print("✅ Template sent successfully!")
                return resp.json()
            else:
                error_response = resp.json()
                print(f"❌ Error with {lang_code}: {resp.text}")
                
                # If it's a language issue, try next language
                if "does not exist in" in str(error_response):
                    continue
                else:
                    # If it's a different error, stop trying other languages
                    break
                
        print("❌ Failed to send template with all language codes")
        return None

    def send_payment_template_flexible(self, to_phone, customer_name, amount, payment_link, template_name="cashfree_pay"):
        """
        Tries different parameter combinations for the template
        """
        url = f"{self.base_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Different component combinations to try
        template_variations = [
            # Variation 1: Header + Body + Button
            {
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {"type": "text", "text": customer_name}
                        ]
                    },
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": customer_name},
                            {"type": "text", "text": str(amount)}
                        ]
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": 0,
                        "parameters": [
                            {"type": "text", "text": payment_link}
                        ]
                    }
                ]
            },
            # Variation 2: Only Body + Button (no header)
            {
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": customer_name},
                            {"type": "text", "text": str(amount)}
                        ]
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": 0,
                        "parameters": [
                            {"type": "text", "text": payment_link}
                        ]
                    }
                ]
            },
            # Variation 3: Header with different param + Body + Button
            {
                "components": [
                    {
                        "type": "header",
                        "parameters": [
                            {"type": "text", "text": str(amount)}
                        ]
                    },
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": customer_name},
                            {"type": "text", "text": str(amount)}
                        ]
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": 0,
                        "parameters": [
                            {"type": "text", "text": payment_link}
                        ]
                    }
                ]
            }
        ]
        
        language_codes = ["en", "en_US", "en_GB"]
        
        for i, template_structure in enumerate(template_variations):
            print(f"\n--- Trying variation {i+1} ---")
            
            for lang_code in language_codes:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to_phone,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": lang_code},
                        **template_structure
                    }
                }
                
                print(f"Language: {lang_code}")
                resp = requests.post(url, headers=headers, json=payload)
                print(f"Status: {resp.status_code}")
                
                if resp.status_code == 200:
                    print("✅ Template sent successfully!")
                    print(f"Successful payload: {json.dumps(payload, indent=2)}")
                    return resp.json()
                else:
                    error_response = resp.json()
                    print(f"❌ Error: {resp.text}")
                    
                    # If it's a language issue, try next language
                    if "does not exist in" in str(error_response):
                        continue
                    else:
                        # If it's a parameter issue, try next variation
                        break
                        
        print("❌ Failed to send template with all variations")
        return None


# Usage example:
if __name__ == "__main__":
    api = WhatsAppBusinessAPI(
        access_token="EAAIU4R08QAEBPEpfaczkfSFx2RPFZBZCj7JozJ2s7KzZAxaeO33gbA0G4fh2XkVWZBmPuwZBivjHzF4ZBOT3gMc8yjQro5AS5puRH1wNepRriqZAy2ZAZCIHZBN4RtUB7U97IBGaBh64ClPghzNI3tJkMjpZAZA2wIXeikKJKOhCFlUH8t5mN0ZAeLnGs93dUZCwmZCrE65INZCxpI9cWdugaJePE3zd36dn7vbZB9d7hGb0aWhkG60EWxuZBKA5fxE4tXQm8ZD",
        phone_number_id="712120695307063"
    )

    # First, check what templates are available
    print("=== Checking available templates ===")
    api.get_templates()
    
    print("\n=== Sending payment message ===")
    
    # Try to send template first
    result = api.send_payment_template(
        to_phone="917869615290",
        customer_name="Raj Malviya",
        amount=25000,
        payment_link="https://api.cashfree.com/pg/view/sessions/checkout/web/pk8yEVukbhtWG2Numjvx"
    )
    