from unittest.mock import patch

import lambdas.anpr_processor.handler as handler_module


def _reset_handler_cache():
    handler_module._s3 = None
    handler_module._dynamodb = None
    handler_module._sns = None


def _mock_pipeline(rego: str | None, confidence: float):
    """Return mock functions for detect_plate, read_plate, and process_plate."""
    if rego is None:
        return (
            patch("lambdas.anpr_processor.handler.detect_plate", return_value=None),
            patch("lambdas.anpr_processor.handler.read_plate", return_value=("", 0.0)),
            patch("lambdas.anpr_processor.handler.process_plate", return_value=(None, 0.0)),
        )
    return (
        patch("lambdas.anpr_processor.handler.detect_plate", return_value=b"fake-crop"),
        patch("lambdas.anpr_processor.handler.read_plate", return_value=(rego, confidence)),
        patch("lambdas.anpr_processor.handler.process_plate", return_value=(rego.upper(), confidence)),
    )


def test_known_vehicle(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    aws_resources["vehicles_table"].put_item(
        Item={"rego": "ABC123", "owner_name": "Jane Smith"}
    )

    p_detect, p_read, p_process = _mock_pipeline("abc123", 0.95)
    with p_detect, p_read, p_process:
        result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] == "ABC123"
    assert result["is_known"] is True

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 1
    assert events[0]["rego"] == "ABC123"
    assert events[0]["is_known"] is True
    assert events[0]["owner_name"] == "Jane Smith"


def test_unknown_vehicle(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    p_detect, p_read, p_process = _mock_pipeline("xyz999", 0.92)
    with p_detect, p_read, p_process:
        result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] == "XYZ999"
    assert result["is_known"] is False

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 1
    assert events[0]["rego"] == "XYZ999"
    assert events[0]["is_known"] is False


def test_no_plate_detected(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    p_detect, p_read, p_process = _mock_pipeline(None, 0.0)
    with p_detect, p_read, p_process:
        result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] is None

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 0


def test_low_confidence(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    monkeypatch.setattr(handler_module, "CONFIDENCE_THRESHOLD", 0.7)
    _reset_handler_cache()

    p_detect, p_read, p_process = _mock_pipeline("low001", 0.5)
    with p_detect, p_read, p_process:
        result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] == "LOW001"
    assert result["is_known"] is False

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 0
