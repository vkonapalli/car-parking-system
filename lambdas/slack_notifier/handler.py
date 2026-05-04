import json
import os
import urllib.request
import boto3
from datetime import datetime
from zoneinfo import ZoneInfo

s3 = boto3.client("s3")
ssm = boto3.client("ssm")

_webhook_url = None


def _get_webhook_url():
    global _webhook_url
    if _webhook_url is None:
        param = ssm.get_parameter(
            Name=os.environ["SLACK_WEBHOOK_URL_PARAM"],
            WithDecryption=True,
        )
        _webhook_url = param["Parameter"]["Value"]
    return _webhook_url


def lambda_handler(event, context):
    message = json.loads(event["Records"][0]["Sns"]["Message"])
    rego = message["rego"]
    confidence = message["confidence"]
    s3_key = message["s3_key"]
    timestamp = message["timestamp"]
    lot_id = message["lot_id"]

    presigned_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["CAPTURES_BUCKET"], "Key": s3_key},
        ExpiresIn=3600,
    )

    utc_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    nz_dt = utc_dt.astimezone(ZoneInfo("Pacific/Auckland"))
    display_time = nz_dt.strftime("%Y-%m-%d %H:%M:%S %Z")

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
                    {"type": "mrkdwn", "text": f"*Time:*\n{display_time}"},
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

    webhook_url = _get_webhook_url()
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"Slack response: {resp.status}")
    except Exception as exc:
        print(f"Slack error: {exc}")
