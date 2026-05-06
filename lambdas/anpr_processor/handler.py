import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

from .plate_detector import detect_plate
from .ocr import read_plate
from .plate_validator import process_plate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_s3 = None
_dynamodb = None
_sns = None

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))


def _clients():
    global _s3, _dynamodb, _sns
    if _s3 is None:
        _s3 = boto3.client("s3")
        _dynamodb = boto3.resource("dynamodb")
        _sns = boto3.client("sns")
    return _s3, _dynamodb, _sns


def lambda_handler(event, context):
    s3_key = event["s3_key"]
    device_id = event["device_id"]
    lot_id = event["lot_id"]
    timestamp = event["timestamp"]

    s3, dynamodb, sns = _clients()

    s3_response = s3.get_object(Bucket=os.environ["CAPTURES_BUCKET"], Key=s3_key)
    image_data = s3_response["Body"].read()

    plate_image = detect_plate(image_data)
    if plate_image is None:
        logger.info("no_plate_region s3_key=%s", s3_key)
        return {"statusCode": 200, "rego": None, "is_known": False}

    raw_text, ocr_confidence = read_plate(plate_image)
    if not raw_text:
        logger.info("no_text_detected s3_key=%s", s3_key)
        return {"statusCode": 200, "rego": None, "is_known": False}

    rego, confidence = process_plate(raw_text, ocr_confidence)
    if rego is None:
        logger.info("no_valid_plate s3_key=%s", s3_key)
        return {"statusCode": 200, "rego": None, "is_known": False}

    logger.info("plate_read rego=%s confidence=%.2f raw=%s", rego, confidence, raw_text)

    if confidence < CONFIDENCE_THRESHOLD:
        logger.info("low_confidence rego=%s confidence=%s", rego, confidence)
        return {"statusCode": 200, "rego": rego, "is_known": False}

    vehicles_table = dynamodb.Table(os.environ["VEHICLES_TABLE"])
    vehicle_response = vehicles_table.get_item(Key={"rego": rego})
    vehicle = vehicle_response.get("Item")
    is_known = vehicle is not None

    expires_at = int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp())

    item = {
        "lot_id": lot_id,
        "timestamp": timestamp,
        "rego": rego,
        "confidence": Decimal(str(confidence)),
        "is_known": is_known,
        "s3_key": s3_key,
        "device_id": device_id,
        "expires_at": expires_at,
    }
    if is_known and vehicle.get("owner_name"):
        item["owner_name"] = vehicle["owner_name"]

    events_table = dynamodb.Table(os.environ["EVENTS_TABLE"])
    events_table.put_item(Item=item)

    if not is_known:
        sns.publish(
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
