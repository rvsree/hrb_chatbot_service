"""Tests for download_for_reprocessing() (Phase 135) and
generate_admin_doc_download_url() (Phase 170/281) - no real AWS call,
matching this project's existing fake-based convention."""

from src.hrb_chatbot.common.clients.storage_client import s3_upload_client


class _FakeS3Client:
    def __init__(self):
        self.downloaded = []
        self.presigned_params = None

    def download_file(self, bucket, key, local_path):
        self.downloaded.append((bucket, key, local_path))
        with open(local_path, "wb") as f:
            f.write(b"%PDF-1.4 fake content")

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned_params = Params
        return f"https://example-bucket.s3.amazonaws.com/{Params['Key']}?signed=1"


def test_local_path_is_returned_unchanged(monkeypatch):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(s3_upload_client.boto3, "client", lambda service, region_name=None: fake_client)

    result = s3_upload_client.download_for_reprocessing("data/uploads/doc-1/policy.pdf", "doc-1", "policy.pdf")

    assert result == "data/uploads/doc-1/policy.pdf"
    assert fake_client.downloaded == []


def test_s3_uri_is_downloaded_to_the_local_upload_layout(monkeypatch, tmp_path):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(s3_upload_client.boto3, "client", lambda service, region_name=None: fake_client)
    monkeypatch.setattr(s3_upload_client, "UPLOAD_DIRECTORY", tmp_path)

    result = s3_upload_client.download_for_reprocessing(
        "s3://hrb-chatbot-kb-uploads-dev/doc-1/policy.pdf", "doc-1", "policy.pdf"
    )

    assert result == str(tmp_path / "doc-1" / "policy.pdf")
    assert fake_client.downloaded == [("hrb-chatbot-kb-uploads-dev", "doc-1/policy.pdf", str(tmp_path / "doc-1" / "policy.pdf"))]
    assert (tmp_path / "doc-1" / "policy.pdf").exists()


def test_drawio_doc_forces_a_real_download(monkeypatch):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(s3_upload_client.boto3, "client", lambda service, region_name=None: fake_client)

    s3_upload_client.generate_admin_doc_download_url("admin-docs/api-gateway-service/diagram-deployment.drawio")

    assert fake_client.presigned_params["ResponseContentDisposition"] == 'attachment; filename="diagram-deployment.drawio"'


def test_html_doc_is_unaffected(monkeypatch):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(s3_upload_client.boto3, "client", lambda service, region_name=None: fake_client)

    s3_upload_client.generate_admin_doc_download_url("admin-docs/rag-ingestion/overview.html")

    assert "ResponseContentDisposition" not in fake_client.presigned_params
