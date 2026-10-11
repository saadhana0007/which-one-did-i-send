"""Shared Google OAuth for gmail_import.py (read) and the app's real Gmail sending.

Run `python google_auth.py` once to (re)authorise. It requests gmail.readonly, gmail.send and drive.file.
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
CREDS, TOKEN = BASE / "credentials.json", BASE / "token.json"
READ_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SEND_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]  # only files this app creates
ALL_SCOPES = READ_SCOPES + SEND_SCOPES + DRIVE_SCOPES


def granted_scopes() -> set:
    try:
        return set(json.loads(TOKEN.read_text()).get("scopes") or [])
    except Exception:
        return set()


def has_scopes(scopes) -> bool:
    return set(scopes) <= granted_scopes()


def get_credentials(scopes=ALL_SCOPES, interactive=True):
    """Valid credentials covering `scopes`; opens the browser consent flow if needed (interactive only)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN.exists() and has_scopes(scopes):
        creds = Credentials.from_authorized_user_file(str(TOKEN), sorted(granted_scopes()))
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
    if creds and creds.valid:
        return creds
    if not interactive:
        raise RuntimeError("not authorised for these scopes; run: python google_auth.py")
    if not CREDS.exists():
        raise RuntimeError("credentials.json missing")
    creds = InstalledAppFlow.from_client_secrets_file(str(CREDS), ALL_SCOPES).run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    return creds


if __name__ == "__main__":
    get_credentials(ALL_SCOPES, interactive=True)
    print("Authorised. Granted:", ", ".join(sorted(granted_scopes())))
