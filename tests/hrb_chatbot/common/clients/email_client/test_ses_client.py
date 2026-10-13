"""Tests for ses_client.py (Phase 136; attachments added Phase 152) - no real AWS call."""

from botocore.exceptions import ClientError

from src.hrb_chatbot.common.clients.email_client import ses_client


class _FakeSesClient:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.calls: list[dict] = []
        self.raw_calls: list[dict] = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        if self.should_fail:
            raise ClientError({"Error": {"Code": "MessageRejected", "Message": "Email address not verified"}}, "SendEmail")
        return {"MessageId": "fake-message-id"}

    def send_raw_email(self, **kwargs):
        self.raw_calls.append(kwargs)
        if self.should_fail:
            raise ClientError({"Error": {"Code": "MessageRejected", "Message": "Email address not verified"}}, "SendRawEmail")
        return {"MessageId": "fake-raw-message-id"}


def test_send_email_succeeds_and_calls_ses_with_the_right_shape(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    result = ses_client.send_email("someone@example.com", "Subject", "Body text")

    assert result == {"sent": True, "message": "Email sent to someone@example.com."}
    assert fake.calls[0]["Source"] == "sender@example.com"
    assert fake.calls[0]["Destination"] == {"ToAddresses": ["someone@example.com"]}
    assert fake.calls[0]["Message"]["Subject"]["Data"] == "Subject"
    assert fake.calls[0]["Message"]["Body"]["Text"]["Data"] == "Body text"


def test_send_email_reports_a_real_ses_failure_as_data_not_an_exception(monkeypatch):
    fake = _FakeSesClient(should_fail=True)
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    result = ses_client.send_email("someone@example.com", "Subject", "Body")

    assert result["sent"] is False
    assert "not verified" in result["message"]


def test_send_email_without_a_configured_sender_fails_gracefully(monkeypatch):
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: default)

    result = ses_client.send_email("someone@example.com", "Subject", "Body")

    assert result == {"sent": False, "message": "SES_SENDER_EMAIL is not configured."}


# Phase 152 - attachments go through send_raw_email (a real MIME message),
# not the plain send_email call above, which has no attachment support at all.


def test_send_email_with_attachments_calls_send_raw_email_not_send_email(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    result = ses_client.send_email(
        "someone@example.com", "Subject", "Body text", attachments=[("report.pdf", b"%PDF-1.4 fake pdf bytes")]
    )

    assert result == {"sent": True, "message": "Email sent to someone@example.com."}
    assert fake.calls == []  # the plain API was never called
    assert len(fake.raw_calls) == 1
    assert fake.raw_calls[0]["Source"] == "sender@example.com"
    assert fake.raw_calls[0]["Destinations"] == ["someone@example.com"]


def test_send_email_with_attachments_builds_a_real_mime_message_with_the_right_filename(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email(
        "someone@example.com", "Subject", "Body text", attachments=[("report.pdf", b"%PDF-1.4 fake pdf bytes")]
    )

    raw_bytes = fake.raw_calls[0]["RawMessage"]["Data"]
    assert b"report.pdf" in raw_bytes
    assert b"Body text" in raw_bytes


def test_send_email_with_multiple_attachments_includes_every_filename(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email(
        "someone@example.com",
        "Subject",
        "Body text",
        attachments=[("a.pdf", b"pdf bytes"), ("b.csv", b"a,b\n1,2")],
    )

    raw_bytes = fake.raw_calls[0]["RawMessage"]["Data"]
    assert b"a.pdf" in raw_bytes
    assert b"b.csv" in raw_bytes


def test_send_email_with_an_oversized_attachment_fails_gracefully_without_calling_ses(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    oversized = b"x" * (ses_client.MAX_TOTAL_ATTACHMENT_BYTES + 1)

    result = ses_client.send_email("someone@example.com", "Subject", "Body", attachments=[("big.pdf", oversized)])

    assert result["sent"] is False
    assert "limit" in result["message"]
    assert fake.calls == []
    assert fake.raw_calls == []


def test_send_email_with_attachments_reports_a_real_ses_failure_as_data(monkeypatch):
    fake = _FakeSesClient(should_fail=True)
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    result = ses_client.send_email("someone@example.com", "Subject", "Body", attachments=[("a.pdf", b"bytes")])

    assert result["sent"] is False
    assert "not verified" in result["message"]


# Phase 157 - html_body: SES's simple API gets both Text and Html keys; the
# raw/attachment API's body part becomes "html", not "plain".


def test_send_email_with_html_body_includes_both_text_and_html_in_the_simple_api_call(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    result = ses_client.send_email(
        "someone@example.com", "Subject", "Plain fallback", html_body="<p>Hello</p><table><tr><th>A</th></tr></table>"
    )

    assert result == {"sent": True, "message": "Email sent to someone@example.com."}
    body = fake.calls[0]["Message"]["Body"]
    assert body["Text"]["Data"] == "Plain fallback"
    assert body["Html"]["Data"] == "<p>Hello</p><table><tr><th>A</th></tr></table>"


def test_send_email_without_html_body_omits_the_html_key(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email("someone@example.com", "Subject", "Plain only")

    assert "Html" not in fake.calls[0]["Message"]["Body"]


def test_send_email_with_attachments_and_html_body_sends_an_html_mime_part(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email(
        "someone@example.com",
        "Subject",
        "Plain fallback",
        attachments=[("report.pdf", b"bytes")],
        html_body="<table><tr><th>A</th></tr></table>",
    )

    raw_bytes = fake.raw_calls[0]["RawMessage"]["Data"]
    assert b"Content-Type: text/html" in raw_bytes
    assert b"<table>" in raw_bytes


def test_send_email_with_attachments_and_no_html_body_sends_a_plain_mime_part(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email(
        "someone@example.com", "Subject", "Plain body text", attachments=[("report.pdf", b"bytes")]
    )

    raw_bytes = fake.raw_calls[0]["RawMessage"]["Data"]
    assert b"Content-Type: text/plain" in raw_bytes


# Phase 163 - cc_addresses, on both the simple and raw/attachment paths.


def test_send_email_with_cc_addresses_includes_them_in_the_simple_api_call(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    result = ses_client.send_email(
        "someone@example.com", "Subject", "Body text", cc_addresses=["cc1@example.com", "cc2@example.com"]
    )

    assert result == {"sent": True, "message": "Email sent to someone@example.com."}
    assert fake.calls[0]["Destination"] == {
        "ToAddresses": ["someone@example.com"],
        "CcAddresses": ["cc1@example.com", "cc2@example.com"],
    }


def test_send_email_without_cc_addresses_omits_the_cc_key(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email("someone@example.com", "Subject", "Body text")

    assert "CcAddresses" not in fake.calls[0]["Destination"]


def test_send_email_with_attachments_and_cc_addresses_includes_them_in_destinations(monkeypatch):
    fake = _FakeSesClient()
    monkeypatch.setattr(ses_client.boto3, "client", lambda service, region_name=None: fake)
    monkeypatch.setattr(ses_client, "read_setting", lambda value, name, default=None: "sender@example.com" if name == "SES_SENDER_EMAIL" else default)

    ses_client.send_email(
        "someone@example.com",
        "Subject",
        "Body text",
        attachments=[("report.pdf", b"bytes")],
        cc_addresses=["cc1@example.com"],
    )

    assert fake.raw_calls[0]["Destinations"] == ["someone@example.com", "cc1@example.com"]
    raw_bytes = fake.raw_calls[0]["RawMessage"]["Data"]
    assert b"cc1@example.com" in raw_bytes
