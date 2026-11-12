"""يُشغَّل مرة واحدة على جهازك لإنتاج BLOGGER_TOKEN.
الاستخدام:  python scripts/get_blogger_token.py client_secret.json"""
import base64
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/blogger"]

if len(sys.argv) < 2:
    sys.exit("الاستخدام: python scripts/get_blogger_token.py client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.loads(creds.to_json())
print("\n===== انسخ القيمة التالية كاملة وضعها في GitHub Secret باسم BLOGGER_TOKEN =====\n")
print(base64.b64encode(json.dumps(info).encode("utf-8")).decode("utf-8"))
