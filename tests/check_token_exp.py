"""检查 access_token 的 JWT 过期时间。"""
import time
import json
import base64

# access_token 的 payload 部分（第二段）
token_payload = "eyJ1c2VyX2lkIjoiMWI5YzMzZjItYTdmMS00MjIwLWJjMjctOGI0NDZjZGM2MGNjIiwiZXhwIjoxNzgyNTIzOTkzLCJpc3MiOiJTRUxGX0hPU1RFRCIsInN1YiI6IkNvbnNvbGUgQVBJIFBhc3Nwb3J0In0"
pad = "=" * (-len(token_payload) % 4)
payload = json.loads(base64.urlsafe_b64decode(token_payload + pad))

exp = payload["exp"]
now = int(time.time())
diff_min = (exp - now) // 60

print(f"JWT payload: {payload}")
print(f"exp timestamp: {exp}")
print(f"  exp time: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(exp))}")
print(f"now timestamp: {now}")
print(f"  now time: {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(now))}")
print(f"expired: {now > exp}")
print(f"remaining: {diff_min} minutes ({diff_min // 60} hours {diff_min % 60} min)")
