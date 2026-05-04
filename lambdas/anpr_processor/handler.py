import json
import os
from decimal import Decimal
from datetime import datetime, timezone, timedelta

import boto3
import requests

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
sns = boto3.client("sns")

_api_key = None
_confidence_threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.7"))
_vehicles_table = dynamodb.Table(os.environ.get("VEHICLES_TABLE", "parking-vehicles"))
_events_table = dynamodb.Table(os.environ.get("EVENTS_TABLE", "parking-events"))


def _get_api_key():
    global _api_key
    if _api_key is None:
        param = ssm.get_parameter(
            Name=os.environ["PLATE_RECOGNIZER_API_KEY_PARAM"],
            WithDecryption=True,
        )
        _api_key = param["Parameter"]["Value"]
    return _api_key


def lambda_handler(event, context):
    s3_key = event["s3_key"]
    device_id = event["device_id"]
    lot_id = event["lot_id"]
    timestamp = event["timestamp"]

    bucket = os.environ["CAPTURES_BUCKET"]
    obj = s3.get_object(Bucket=bucket, Key=s3_key)
    image_data = obj["Body"].read()

    api_key = _get_api_key()
    try:
        response = requests.post(
            "https://api.platerecognizer.com/v1/plate-reader/",
            headers={"Authorization": f"Token {api_key}"},
            files={"upload": image_data},
            data={"regions": "nz"},
            timeout=15,
        )
        response.raise_for_status()
        pr_response = response.json()
    except Exception as exc:
        print(f"Plate Recognizer error: {exc}")
        return {"statusCode": 500, "error": str(exc)}

    results = pr_response.get("results", [])
    if not results:
        print("no_plate_detected")
        return {"statusCode": 200, "status": "no_plate_detected"}

    best = max(results, key=lambda r: r.get("score", 0))
    rego = best["plate"].upper()
    confidence = best["score"]

    if confidence < _confidence_threshold:
        print(f"low_confidence: {confidence}")
        return {"statusCode": 200, "status": "low_confidence", "confidence": confidence}

    vehicle_resp = _vehicles_table.get_item(Key={"rego": rego})
    vehicle = vehicle_resp.get("Item")
    is_known = vehicle is not None

    now = datetime.now(timezone.utc)
    expires_at = int((now + timedelta(days=90)).timestamp())

    item = {
        "lot_id": lot_id,
        "timestamp": timestamp,
        "rego": rego,
        "confidence": Decimal(str(confidence)),
        "is_known": is_known,
        "s3_key": s3_key,
        "device_id": device_id,
        "owner_name": vehicle.get("owner_name") if vehicle else None,
        "expires_at": expires_at,
    }
    _events_table.put_item(Item=item)

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
