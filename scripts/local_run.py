#!/usr/bin/env python3
"""Run the ANPR pipeline locally against LocalStack.

Usage:
    uv run scripts/local_run.py --image path/to/plate.jpg
    uv run scripts/local_run.py --image path/to/plate.jpg --lot-id lot-2
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import boto3


ENDPOINT_URL = "http://localhost:4566"
REGION = "ap-southeast-2"

BUCKET_NAME = "parking-captures"
VEHICLES_TABLE = "parking-vehicles"
EVENTS_TABLE = "parking-events"
SNS_TOPIC_NAME = "parking-unknown-vehicle"
SLACK_WEBHOOK_PARAM = "/parking/slack-webhook-url"


def localstack_env():
    """Return env vars that make the Lambda handler talk to LocalStack."""
    sns = boto3.client(
        "sns",
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    topics = sns.list_topics()["Topics"]
    topic_arn = next(t["TopicArn"] for t in topics if SNS_TOPIC_NAME in t["TopicArn"])

    return {
        "CAPTURES_BUCKET": BUCKET_NAME,
        "VEHICLES_TABLE": VEHICLES_TABLE,
        "EVENTS_TABLE": EVENTS_TABLE,
        "SNS_TOPIC_ARN": topic_arn,
        "SLACK_WEBHOOK_URL_PARAM": SLACK_WEBHOOK_PARAM,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": REGION,
        "AWS_ENDPOINT_URL": ENDPOINT_URL,
    }


def upload_image(image_path, lot_id):
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    now = datetime.now(timezone.utc)
    s3_key = f"captures/{lot_id}/{now.strftime('%Y-%m-%d/%H-%M-%S')}.jpg"

    with open(image_path, "rb") as f:
        s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=f, ContentType="image/jpeg")

    print(f"Uploaded to s3://{BUCKET_NAME}/{s3_key}")
    return s3_key, now.isoformat()


def patch_boto3_for_localstack():
    """Monkey-patch boto3 so the handler's _clients() connects to LocalStack."""
    _original_client = boto3.client
    _original_resource = boto3.resource

    def patched_client(service, **kwargs):
        kwargs.setdefault("endpoint_url", ENDPOINT_URL)
        kwargs.setdefault("region_name", REGION)
        kwargs.setdefault("aws_access_key_id", "test")
        kwargs.setdefault("aws_secret_access_key", "test")
        return _original_client(service, **kwargs)

    def patched_resource(service, **kwargs):
        kwargs.setdefault("endpoint_url", ENDPOINT_URL)
        kwargs.setdefault("region_name", REGION)
        kwargs.setdefault("aws_access_key_id", "test")
        kwargs.setdefault("aws_secret_access_key", "test")
        return _original_resource(service, **kwargs)

    boto3.client = patched_client
    boto3.resource = patched_resource


def main():
    parser = argparse.ArgumentParser(description="Run ANPR pipeline locally against LocalStack")
    parser.add_argument("--image", required=True, help="Path to a plate image (JPEG)")
    parser.add_argument("--lot-id", default="lot-1")
    parser.add_argument("--device-id", default="lot-1-cam")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"ERROR: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    env = localstack_env()
    os.environ.update(env)

    print(f"Uploading image: {args.image}")
    s3_key, timestamp = upload_image(args.image, args.lot_id)

    patch_boto3_for_localstack()

    import lambdas.anpr_processor.handler as handler_module
    handler_module._s3 = None
    handler_module._dynamodb = None
    handler_module._sns = None

    event = {
        "s3_key": s3_key,
        "device_id": args.device_id,
        "lot_id": args.lot_id,
        "timestamp": timestamp,
    }

    print(f"\nInvoking ANPR handler with: {json.dumps(event, indent=2)}")
    result = handler_module.lambda_handler(event, None)

    print(f"\n--- Result ---")
    print(json.dumps(result, indent=2, default=str))

    rego = result.get("rego")
    is_known = result.get("is_known")
    if rego:
        status = "KNOWN" if is_known else "UNKNOWN"
        print(f"\nRego: {rego} ({status})")
        if not is_known:
            print("SNS notification published (check LocalStack logs for subscriber delivery)")
    else:
        print("\nNo plate detected in image.")


if __name__ == "__main__":
    main()
