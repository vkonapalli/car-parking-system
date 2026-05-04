import json
from unittest.mock import patch, MagicMock

import pytest

import lambdas.slack_notifier.handler as handler_module


def _reset_handler_cache():
    handler_module._webhook_url = None
    handler_module._s3 = None
    handler_module._ssm = None


def _make_fake_urlopen(captured: dict):
    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp
    return fake_urlopen


def test_slack_message_format(slack_aws_resources, sample_sns_event):
    _reset_handler_cache()

    captured = {}
    with patch(
        "lambdas.slack_notifier.handler.urllib.request.urlopen",
        side_effect=_make_fake_urlopen(captured),
    ):
        handler_module.lambda_handler(sample_sns_event, {})

    blocks = captured["payload"]["blocks"]
    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"] == "Unknown Vehicle Detected"

    section = blocks[1]
    assert section["type"] == "section"
    field_texts = [f["text"] for f in section["fields"]]
    assert any("ABC123" in t for t in field_texts)
    assert any("92%" in t for t in field_texts)
    assert any("lot-1" in t for t in field_texts)

    image_block = blocks[2]
    assert image_block["type"] == "image"
    assert image_block["alt_text"] == "Captured plate image"


def test_presigned_url_generated(slack_aws_resources, sample_sns_event):
    _reset_handler_cache()

    captured = {}
    with patch(
        "lambdas.slack_notifier.handler.urllib.request.urlopen",
        side_effect=_make_fake_urlopen(captured),
    ):
        handler_module.lambda_handler(sample_sns_event, {})

    image_url = captured["payload"]["blocks"][2]["image_url"]
    assert "captures/lot-1/2026-05-04/09-23-11.jpg" in image_url
    assert any(sig_marker in image_url for sig_marker in ["X-Amz-Expires", "AWSAccessKeyId", "X-Amz-Signature"])


def test_timezone_conversion(slack_aws_resources, sample_sns_event):
    _reset_handler_cache()

    captured = {}
    with patch(
        "lambdas.slack_notifier.handler.urllib.request.urlopen",
        side_effect=_make_fake_urlopen(captured),
    ):
        handler_module.lambda_handler(sample_sns_event, {})

    section_fields = captured["payload"]["blocks"][1]["fields"]
    time_field = next(f for f in section_fields if "*Time:*" in f["text"])

    assert "NZST" in time_field["text"] or "NZDT" in time_field["text"]
    assert "2026-05-04" in time_field["text"]
    assert "09:23:11 UTC" not in time_field["text"]
