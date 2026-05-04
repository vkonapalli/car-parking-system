import json
import logging
import os
import urllib.request
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CAPTURES_BUCKET = os.environ["CAPTURES_BUCKET"]
SLACK_WEBHOOK_URL_PARAM = os.environ["SLACK_WEBHOOK_URL_PARAM"]
NZ_TZ = ZoneInfo("Pacific/Auckland")

_slack_webhook_url: str | None = None


@lru_cache(maxsize=1)
def _ssm_client():
    return boto3.client("ssm")


@lru_cache(maxsize=1)
def _s3_client():
    return boto3.client("s3")


def _get_slack_webhook_url() -> str:
    global _slack_webhook_url
    if _slack_webhook_url is None:
        response = _ssm_client().get_parameter(Name=SLACK_WEBHOOK_URL_PARAM, WithDecryption=True)
        _slack_webhook_url = response["Parameter"]["Value"]
    return _slack_webhook_url


def _presigned_url(s3_key: str) -> str:
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": CAPTURES_BUCKET, "Key": s3_key},
        ExpiresIn=3600,
    )


def _format_timestamp(ts: str) -> str:
    dt = datetime.fromisoformat(ts)
    return dt.astimezone(NZ_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def _build_payload(rego: str, confidence: float, timestamp: str, lot_id: str, presigned_url: str) -> dict:
    return {
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
                    {"type": "mrkdwn", "text": f"*Time:*\n{_format_timestamp(timestamp)}"},
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


def lambda_handler(event, context):
    message = json.loads(event["Records"][0]["Sns"]["Message"])
    rego = message["rego"]
    confidence = message["confidence"]
    s3_key = message["s3_key"]
    timestamp = message["timestamp"]
    lot_id = message["lot_id"]

    url = _presigned_url(s3_key)
    webhook_url = _get_slack_webhook_url()
    payload = _build_payload(rego, confidence, timestamp, lot_id, url)

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            logger.info("Slack response status: %s", resp.status)
    except urllib.error.HTTPError as exc:
        logger.error("Slack webhook error: %s %s", exc.code, exc.reason)
