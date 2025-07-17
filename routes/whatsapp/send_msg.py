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
        
        print(f"URL: {url}")
        print(f"Headers: {headers}")
        print(f"Data: {json.dumps(data, indent=2)}")
        
        response = requests.post(url, headers=headers, json=data)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        return response.json()

# Usage with proper phone number format
api = WhatsAppBusinessAPI("EAAIU4R08QAEBPEpfaczkfSFx2RPFZBZCj7JozJ2s7KzZAxaeO33gbA0G4fh2XkVWZBmPuwZBivjHzF4ZBOT3gMc8yjQro5AS5puRH1wNepRriqZAy2ZAZCIHZBN4RtUB7U97IBGaBh64ClPghzNI3tJkMjpZAZA2wIXeikKJKOhCFlUH8t5mN0ZAeLnGs93dUZCwmZCrE65INZCxpI9cWdugaJePE3zd36dn7vbZB9d7hGb0aWhkG60EWxuZBKA5fxE4tXQm8ZD", "712120695307063")
result = api.send_message("917869615290", "Hello from Python!")  # +91 prefix added
print(result)