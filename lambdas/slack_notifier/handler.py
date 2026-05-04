import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_webhook_url = None
_s3 = None
_ssm = None

NZ_TZ = ZoneInfo("Pacific/Auckland")


def _clients():
    global _s3, _ssm
    if _s3 is None:
        _s3 = boto3.client("s3")
        _ssm = boto3.client("ssm")
    return _s3, _ssm


def _get_webhook_url():
    global _webhook_url
    if _webhook_url is None:
        _, ssm = _clients()
        param_name = os.environ["SLACK_WEBHOOK_URL_PARAM"]
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        _webhook_url = response["Parameter"]["Value"]
    return _webhook_url


def _format_nz_time(timestamp: str) -> str:
    dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    dt_nz = dt_utc.astimezone(NZ_TZ)
    return dt_nz.strftime("%Y-%m-%d %H:%M:%S %Z")


def lambda_handler(event, context):
    message = json.loads(event["Records"][0]["Sns"]["Message"])

    rego = message["rego"]
    confidence = message["confidence"]
    s3_key = message["s3_key"]
    timestamp = message["timestamp"]
    lot_id = message["lot_id"]

    s3, _ = _clients()

    presigned_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["CAPTURES_BUCKET"], "Key": s3_key},
        ExpiresIn=3600,
    )

    webhook_url = _get_webhook_url()

    nz_time = _format_nz_time(timestamp)

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Unknown Vehicle Detected"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Rego:*\n{rego}"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                    {"type": "mrkdwn", "text": f"*Time:*\n{nz_time}"},
                    {"type": "mrkdwn", "text": f"*Lot:*\n{lot_id}"},
                ],
            },
            {
                "type": "image",
                "image_url": presigned_url,
                "alt_text": "Captured plate image",
            },
        ]
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("slack_response status=%s", resp.status)
    except Exception as e:
        logger.error("slack_error error=%s", str(e))
