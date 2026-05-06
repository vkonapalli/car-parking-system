#!/usr/bin/env python3
"""Bootstrap LocalStack with the resources needed for local development."""

import argparse
import json
import sys

import boto3


ENDPOINT_URL = "http://localhost:4566"
REGION = "ap-southeast-2"

BUCKET_NAME = "parking-captures"
VEHICLES_TABLE = "parking-vehicles"
EVENTS_TABLE = "parking-events"
SNS_TOPIC_NAME = "parking-unknown-vehicle"
SLACK_WEBHOOK_PARAM = "/parking/slack-webhook-url"


def client(service):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def resource(service):
    return boto3.resource(
        service,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def create_bucket(s3):
    try:
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        print(f"  Created S3 bucket: {BUCKET_NAME}")
    except s3.exceptions.BucketAlreadyExists:
        print(f"  S3 bucket already exists: {BUCKET_NAME}")


def create_tables(dynamodb):
    existing = dynamodb.meta.client.list_tables()["TableNames"]

    if VEHICLES_TABLE not in existing:
        dynamodb.create_table(
            TableName=VEHICLES_TABLE,
            KeySchema=[{"AttributeName": "rego", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "rego", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created DynamoDB table: {VEHICLES_TABLE}")
    else:
        print(f"  DynamoDB table already exists: {VEHICLES_TABLE}")

    if EVENTS_TABLE not in existing:
        dynamodb.create_table(
            TableName=EVENTS_TABLE,
            KeySchema=[
                {"AttributeName": "lot_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "lot_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created DynamoDB table: {EVENTS_TABLE}")
    else:
        print(f"  DynamoDB table already exists: {EVENTS_TABLE}")


def create_sns_topic(sns):
    response = sns.create_topic(Name=SNS_TOPIC_NAME)
    arn = response["TopicArn"]
    print(f"  Created SNS topic: {arn}")
    return arn


def create_ssm_params(ssm, slack_webhook_url):
    if not slack_webhook_url:
        return
    ssm.put_parameter(
        Name=SLACK_WEBHOOK_PARAM,
        Value=slack_webhook_url,
        Type="SecureString",
        Overwrite=True,
    )
    print(f"  Set SSM parameter: {SLACK_WEBHOOK_PARAM}")


def seed_vehicles(dynamodb, vehicles):
    table = dynamodb.Table(VEHICLES_TABLE)
    for v in vehicles:
        table.put_item(Item=v)
        print(f"  Seeded vehicle: {v['rego']}")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap LocalStack for parking system")
    parser.add_argument("--slack-webhook-url", default="", help="Slack webhook URL (optional)")
    args = parser.parse_args()

    print("Bootstrapping LocalStack resources...")

    s3 = client("s3")
    dynamodb = resource("dynamodb")
    sns = client("sns")
    ssm = client("ssm")

    create_bucket(s3)
    create_tables(dynamodb)
    topic_arn = create_sns_topic(sns)
    create_ssm_params(ssm, args.slack_webhook_url)

    seed_vehicles(dynamodb, [
        {"rego": "ABC123", "owner_name": "Test User", "vehicle_make": "Toyota", "vehicle_color": "White", "is_employee": True},
        {"rego": "XYZ789", "owner_name": "Jane Doe", "vehicle_make": "Honda", "vehicle_color": "Black", "is_employee": True},
    ])

    print(f"\nDone. SNS Topic ARN: {topic_arn}")
    print("\nExport for local_run.py:")
    print(f"  SNS_TOPIC_ARN={topic_arn}")


if __name__ == "__main__":
    main()
