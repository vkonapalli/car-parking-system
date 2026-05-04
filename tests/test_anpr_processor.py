import json

import pytest
import responses as responses_lib

import lambdas.anpr_processor.handler as handler_module


PLATE_RECOGNIZER_URL = "https://api.platerecognizer.com/v1/plate-reader/"


def _reset_handler_cache():
    handler_module._api_key = None
    handler_module._s3 = None
    handler_module._ssm = None
    handler_module._dynamodb = None
    handler_module._sns = None


def _plate_response(plate: str, score: float) -> dict:
    return {
        "results": [
            {
                "plate": plate,
                "score": score,
                "dscore": score,
                "box": {"xmin": 0, "ymin": 0, "xmax": 100, "ymax": 50},
                "candidates": [{"plate": plate, "score": score}],
            }
        ],
        "usage": {"calls": 1},
    }


@responses_lib.activate
def test_known_vehicle(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    aws_resources["vehicles_table"].put_item(
        Item={"rego": "ABC123", "owner_name": "Jane Smith"}
    )

    responses_lib.add(
        responses_lib.POST,
        PLATE_RECOGNIZER_URL,
        json=_plate_response("abc123", 0.95),
        status=200,
    )

    result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] == "ABC123"
    assert result["is_known"] is True

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 1
    assert events[0]["rego"] == "ABC123"
    assert events[0]["is_known"] is True
    assert events[0]["owner_name"] == "Jane Smith"

    sns_subscriptions = aws_resources["sns"].list_subscriptions()["Subscriptions"]
    assert len(sns_subscriptions) == 0


@responses_lib.activate
def test_unknown_vehicle(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    responses_lib.add(
        responses_lib.POST,
        PLATE_RECOGNIZER_URL,
        json=_plate_response("xyz999", 0.92),
        status=200,
    )

    result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] == "XYZ999"
    assert result["is_known"] is False

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 1
    assert events[0]["rego"] == "XYZ999"
    assert events[0]["is_known"] is False


@responses_lib.activate
def test_no_plate_detected(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    responses_lib.add(
        responses_lib.POST,
        PLATE_RECOGNIZER_URL,
        json={"results": [], "usage": {"calls": 1}},
        status=200,
    )

    result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] is None

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 0


@responses_lib.activate
def test_low_confidence(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    monkeypatch.setattr(handler_module, "CONFIDENCE_THRESHOLD", 0.7)
    _reset_handler_cache()

    responses_lib.add(
        responses_lib.POST,
        PLATE_RECOGNIZER_URL,
        json=_plate_response("low001", 0.5),
        status=200,
    )

    result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 200
    assert result["rego"] == "LOW001"
    assert result["is_known"] is False

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 0


@responses_lib.activate
def test_plate_recognizer_error(aws_resources, sample_anpr_event, monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", aws_resources["topic_arn"])
    _reset_handler_cache()

    responses_lib.add(
        responses_lib.POST,
        PLATE_RECOGNIZER_URL,
        json={"error": "internal server error"},
        status=500,
    )

    result = handler_module.lambda_handler(sample_anpr_event, {})

    assert result["statusCode"] == 500

    events = aws_resources["events_table"].scan()["Items"]
    assert len(events) == 0
