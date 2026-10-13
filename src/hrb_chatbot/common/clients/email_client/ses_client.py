"""Sends email via AWS SES (Phase 136) - a plain function, not a Base*Client/
Gateway pair, same reasoning as s3_upload_client.py: one provider, nothing
to swap at runtime. boto3 is already a dependency (S3/Lambda use it) - no
new library for this.

Real one-time setup this code can't do by itself: a new AWS account's SES
starts in sandbox mode, which can only send to pre-verified addresses -
the SENDER identity (SES_SENDER_EMAIL) needs verifying in the SES console
before any send succeeds, sandbox or not. See docs/dev-reference/
genai_chat_workflow.md for the full note.

Phase 152: attachments go through SES's send_raw_email (a real MIME
message we build ourselves), not send_email (Subject/Body-Text only, no
attachment support at all) - the two are genuinely different SES APIs.

Phase 157: an optional html_body - SES's simple send_email already
supports a Html body key alongside Text (same call, no new API); the raw/
attachment path's body part becomes an "html" MIMEText instead of
"plain". Lets the caller send a real formatted email (an HTML <table>,
not markdown pipe syntax) instead of plain text."""

import mimetypes
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import boto3
from botocore.exceptions import ClientError

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("ses_client")

DEFAULT_REGION = "us-east-1"

# SES's send_raw_email hard caps the whole raw message at 10MB. Our own
# base64-encoding of each attachment (email.mime.application does this
# automatically) inflates raw bytes by ~37% - checking the RAW attachment
# total against a conservative 7MB leaves headroom for that inflation plus
# headers/body, instead of discovering the real cap via a raw ClientError.
MAX_TOTAL_ATTACHMENT_BYTES = 7 * 1024 * 1024


def _build_raw_message(
    sender: str,
    recipient_email: str,
    subject: str,
    body_text: str,
    attachments: list[tuple[str, bytes]],
    html_body: str | None = None,
    cc_addresses: list[str] | None = None,
) -> bytes:
    message = MIMEMultipart("mixed")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient_email
    if cc_addresses:
        message["Cc"] = ", ".join(cc_addresses)
    message.attach(MIMEText(html_body, "html") if html_body else MIMEText(body_text, "plain"))

    for filename, content in attachments:
        content_type, _ = mimetypes.guess_type(filename)
        maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
        part = MIMEApplication(content, _subtype=subtype or "octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(part)

    return message.as_bytes()


def send_email(
    recipient_email: str,
    subject: str,
    body_text: str,
    attachments: list[tuple[str, bytes]] | None = None,
    html_body: str | None = None,
    cc_addresses: list[str] | None = None,
) -> dict:
    """Returns {"sent": bool, "message": str} - never raises; a send
    failure (unverified sender, sandbox restriction, bad address, an
    oversized attachment) is reported as data, same error-handling-by-layer
    convention every other client in this project follows.

    attachments: optional list of (filename, raw_bytes) - when given, sends
    via SES's send_raw_email instead of its plain send_email, since only
    the raw/MIME API supports attachments at all.

    html_body: optional HTML version of the email - sent alongside
    body_text via SES's simple API (which accepts both in one call), or as
    the sole body format on the raw/attachment path (one MIMEText part, not
    a multipart/alternative with both - simpler, and nothing here needs an
    HTML-unaware email client's plain-text fallback).

    cc_addresses: optional list of CC recipients (Phase 163) - works on
    both the simple and raw/attachment paths."""
    sender = read_setting(None, "SES_SENDER_EMAIL")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)

    if not sender:
        return {"sent": False, "message": "SES_SENDER_EMAIL is not configured."}

    if attachments:
        total_bytes = sum(len(content) for _, content in attachments)
        if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
            return {
                "sent": False,
                "message": (
                    f"Attachments are {total_bytes} bytes total, over the "
                    f"{MAX_TOTAL_ATTACHMENT_BYTES}-byte limit for one email."
                ),
            }

    ses_client = boto3.client("ses", region_name=region)

    try:
        with log_backend_call(logger, "ses", "send_email", recipient=recipient_email):
            if attachments:
                raw_message = _build_raw_message(
                    sender, recipient_email, subject, body_text, attachments, html_body, cc_addresses
                )
                ses_client.send_raw_email(
                    Source=sender,
                    Destinations=[recipient_email, *(cc_addresses or [])],
                    RawMessage={"Data": raw_message},
                )
            else:
                body = {"Text": {"Data": body_text}}
                if html_body:
                    body["Html"] = {"Data": html_body}
                destination = {"ToAddresses": [recipient_email]}
                if cc_addresses:
                    destination["CcAddresses"] = cc_addresses
                ses_client.send_email(
                    Source=sender,
                    Destination=destination,
                    Message={
                        "Subject": {"Data": subject},
                        "Body": body,
                    },
                )
    except ClientError as error:
        logger.warning("SES send to %s failed: %s", recipient_email, error)
        return {"sent": False, "message": str(error)}

    return {"sent": True, "message": f"Email sent to {recipient_email}."}
