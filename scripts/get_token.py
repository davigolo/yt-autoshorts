from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nGuarda estos valores como secrets en GitHub:\n")
print(f"YT_CLIENT_ID={credentials.client_id}")
print(f"YT_CLIENT_SECRET={credentials.client_secret}")
print(f"YT_REFRESH_TOKEN={credentials.refresh_token}")
