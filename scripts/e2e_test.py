#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


STACK_NAME = "ParkingMonitoringStack"


def get_stack_outputs(cf_client):
    try:
        response = cf_client.describe_stacks(StackName=STACK_NAME)
        outputs = response["Stacks"][0].get("Outputs", [])
        return {o["OutputKey"]: o["OutputValue"] for o in outputs}
    except ClientError as e:
        if e.response["Error"]["Code"] in ("ValidationError", "StackInstanceNotFoundException"):
            return {}
        raise


def resolve_lambda_name(lambda_client, pattern_prefix):
    paginator = lambda_client.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            if fn["FunctionName"].startswith(pattern_prefix):
                return fn["FunctionName"]
    return None


def upload_image(s3_client, bucket, s3_key, image_path):
    with open(image_path, "rb") as f:
        s3_client.put_object(Bucket=bucket, Key=s3_key, Body=f, ContentType="image/jpeg")


def invoke_lambda(lambda_client, function_name, payload):
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    raw = response["Payload"].read()
    return json.loads(raw), response.get("FunctionError")


def main():
    parser = argparse.ArgumentParser(description="End-to-end test for the parking monitoring system")
    parser.add_argument("--image", required=True, help="Path to a test NZ plate image (JPEG)")
    parser.add_argument("--lot-id", default="lot-1", help="Parking lot ID (default: lot-1)")
    parser.add_argument("--device-id", default="lot-1-cam", help="Camera device ID (default: lot-1-cam)")
    parser.add_argument("--bucket", help="S3 bucket name (overrides CloudFormation stack output)")
    parser.add_argument("--lambda-name", help="Lambda function name (overrides CloudFormation stack output)")
    args = parser.parse_args()

    cf_client = boto3.client("cloudformation")
    s3_client = boto3.client("s3")
    lambda_client = boto3.client("lambda")

    print(f"Fetching outputs from CloudFormation stack: {STACK_NAME}")
    stack_outputs = get_stack_outputs(cf_client)
    if stack_outputs:
        print(f"  Found {len(stack_outputs)} stack output(s)")
    else:
        print("  Stack not found or has no outputs — relying on CLI args")

    bucket = args.bucket or stack_outputs.get("CapturesBucketName")
    if not bucket:
        print("ERROR: Could not determine S3 bucket. Use --bucket or deploy the stack.", file=sys.stderr)
        sys.exit(1)

    function_name = args.lambda_name or stack_outputs.get("AnprProcessorFunctionName")
    if not function_name:
        print("  Lambda name not in stack outputs — searching by prefix 'anpr-processor'")
        function_name = resolve_lambda_name(lambda_client, "anpr-processor")
    if not function_name:
        print("ERROR: Could not find Lambda function. Use --lambda-name.", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    s3_key = f"captures/{args.lot_id}/{now.strftime('%Y-%m-%d/%H-%M-%S')}.jpg"
    timestamp = now.isoformat()

    print(f"\nUploading image to s3://{bucket}/{s3_key}")
    try:
        upload_image(s3_client, bucket, s3_key, args.image)
        print("  Upload successful")
    except FileNotFoundError:
        print(f"ERROR: Image file not found: {args.image}", file=sys.stderr)
        sys.exit(1)
    except ClientError as e:
        print(f"ERROR: S3 upload failed: {e}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "device_id": args.device_id,
        "lot_id": args.lot_id,
        "timestamp": timestamp,
        "s3_key": s3_key,
    }

    print(f"\nInvoking Lambda: {function_name}")
    print(f"  Payload: {json.dumps(payload, indent=2)}")

    try:
        result, function_error = invoke_lambda(lambda_client, function_name, payload)
    except ClientError as e:
        print(f"ERROR: Lambda invocation failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nRaw Lambda response: {json.dumps(result, indent=2)}")

    if function_error:
        print(f"\nERROR: Lambda returned a function error ({function_error})", file=sys.stderr)
        sys.exit(1)

    status = result.get("statusCode")
    rego = result.get("rego")
    is_known = result.get("is_known")

    print("\n--- Summary ---")
    print(f"  Status:     {status}")
    print(f"  Rego:       {rego or '(none detected)'}")
    if rego is not None:
        print(f"  Is known:   {'Yes' if is_known else 'No'}")
        if not is_known:
            print("  Slack notification should have been triggered via SNS.")

    if status != 200:
        print(f"\nWARNING: Non-200 status code returned ({status})", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
