"""Outbound senders. Gmail is a real send; WhatsApp is a UI handoff (see static/index.html)."""
import base64
import io
import mimetypes
from email.message import EmailMessage

import google_auth


def send_gmail(to: str, subject: str, body: str, filename: str, data: bytes) -> dict:
    from googleapiclient.discovery import build

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject  # EmailMessage rejects newlines (header injection) with ValueError
    msg.set_content(body or f"Attached: {filename}")
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    main, sub = ctype.split("/", 1)
    msg.add_attachment(data, maintype=main, subtype=sub, filename=filename)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc = build("gmail", "v1", credentials=google_auth.get_credentials(google_auth.SEND_SCOPES, interactive=False),
                cache_discovery=False)
    return svc.users().messages().send(userId="me", body={"raw": raw}).execute()


def upload_drive_link(filename: str, data: bytes) -> dict:
    """Upload to the user's Drive and make it viewable by anyone with the link. Returns {id, webViewLink}."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    svc = build("drive", "v3", credentials=google_auth.get_credentials(google_auth.DRIVE_SCOPES, interactive=False),
                cache_discovery=False)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    f = svc.files().create(body={"name": filename}, media_body=MediaIoBaseUpload(io.BytesIO(data), mimetype=mime),
                           fields="id,webViewLink").execute()
    svc.permissions().create(fileId=f["id"], body={"type": "anyone", "role": "reader"}).execute()
    return f
