import json
import logging
import os
import time
from decimal import Decimal

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))

_api_key = None
_s3 = None
_dynamodb = None
_sns = None
_ssm = None


def _clients():
    global _s3, _dynamodb, _sns, _ssm
    if _s3 is None:
        _s3 = boto3.client("s3")
        _dynamodb = boto3.resource("dynamodb")
        _sns = boto3.client("sns")
        _ssm = boto3.client("ssm")
    return _s3, _dynamodb, _sns, _ssm


def _get_api_key():
    global _api_key
    if _api_key is None:
        _, _, _, ssm = _clients()
        param_name = os.environ["PLATE_RECOGNIZER_API_KEY_PARAM"]
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        _api_key = response["Parameter"]["Value"]
    return _api_key


def lambda_handler(event, context):
    s3_key = event["s3_key"]
    device_id = event["device_id"]
    lot_id = event["lot_id"]
    timestamp = event["timestamp"]

    s3, dynamodb, sns_client, _ = _clients()

    s3_response = s3.get_object(Bucket=os.environ["CAPTURES_BUCKET"], Key=s3_key)
    image_data = s3_response["Body"].read()

    api_key = _get_api_key()

    try:
        pr_response = requests.post(
            "https://api.platerecognizer.com/v1/plate-reader/",
            headers={"Authorization": f"Token {api_key}"},
            files={"upload": image_data},
            data={"regions": "nz"},
            timeout=20,
        )
        pr_response.raise_for_status()
        pr_data = pr_response.json()
    except Exception as exc:
        logger.error("Plate Recognizer API error: %s", exc)
        return {"statusCode": 500, "error": str(exc)}

    results = pr_data.get("results", [])
    if not results:
        logger.info("no_plate_detected s3_key=%s", s3_key)
        return {"statusCode": 200, "event": "no_plate_detected"}

    best = max(results, key=lambda r: r["score"])
    rego = best["plate"].upper()
    confidence = best["score"]

    if confidence < CONFIDENCE_THRESHOLD:
        logger.info("low_confidence rego=%s confidence=%s", rego, confidence)
        return {"statusCode": 200, "event": "low_confidence"}

    vehicles_table = dynamodb.Table(os.environ["VEHICLES_TABLE"])
    vehicle_response = vehicles_table.get_item(Key={"rego": rego})
    vehicle = vehicle_response.get("Item")
    is_known = vehicle is not None

    expires_at = int(time.time()) + 90 * 24 * 60 * 60

    events_table = dynamodb.Table(os.environ["EVENTS_TABLE"])
    events_table.put_item(Item={
        "lot_id": lot_id,
        "timestamp": timestamp,
        "rego": rego,
        "confidence": Decimal(str(confidence)),
        "is_known": is_known,
        "s3_key": s3_key,
        "device_id": device_id,
        "owner_name": vehicle.get("owner_name") if is_known else None,
        "expires_at": expires_at,
    })

    if not is_known:
        sns_client.publish(
            TopicArn=os.environ["SNS_TOPIC_ARN"],
            Message=json.dumps({
                "rego": rego,
                "confidence": confidence,
                "s3_key": s3_key,
                "timestamp": timestamp,
                "lot_id": lot_id,
                "device_id": device_id,
            }),
        )

    return {"statusCode": 200, "rego": rego, "is_known": is_known}
