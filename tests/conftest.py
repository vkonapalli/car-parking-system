import json

import boto3
import pytest
from moto import mock_aws


REGION = "ap-southeast-2"
CAPTURES_BUCKET = "test-captures-bucket"
VEHICLES_TABLE = "test-parking-vehicles"
EVENTS_TABLE = "test-parking-events"
SLACK_WEBHOOK_PARAM = "/parking/slack-webhook-url"
FAKE_WEBHOOK_URL = "https://hooks.slack.com/services/TEST/WEBHOOK"


@pytest.fixture(scope="function")
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture(scope="function")
def anpr_env(monkeypatch, aws_credentials):
    monkeypatch.setenv("CAPTURES_BUCKET", CAPTURES_BUCKET)
    monkeypatch.setenv("VEHICLES_TABLE", VEHICLES_TABLE)
    monkeypatch.setenv("EVENTS_TABLE", EVENTS_TABLE)
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.7")


@pytest.fixture(scope="function")
def slack_env(monkeypatch, aws_credentials):
    monkeypatch.setenv("CAPTURES_BUCKET", CAPTURES_BUCKET)
    monkeypatch.setenv("SLACK_WEBHOOK_URL_PARAM", SLACK_WEBHOOK_PARAM)


@pytest.fixture(scope="function")
def aws_resources(anpr_env):
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=CAPTURES_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_object(
            Bucket=CAPTURES_BUCKET,
            Key="captures/lot-1/2026-05-04/09-23-11.jpg",
            Body=b"fake-image-data",
        )

        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        dynamodb.create_table(
            TableName=VEHICLES_TABLE,
            KeySchema=[{"AttributeName": "rego", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "rego", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
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

        sns_client = boto3.client("sns", region_name=REGION)
        topic = sns_client.create_topic(Name="parking-unknown-vehicle")
        topic_arn = topic["TopicArn"]

        yield {
            "s3": s3,
            "dynamodb": dynamodb,
            "sns": sns_client,
            "topic_arn": topic_arn,
            "vehicles_table": dynamodb.Table(VEHICLES_TABLE),
            "events_table": dynamodb.Table(EVENTS_TABLE),
        }


@pytest.fixture(scope="function")
def slack_aws_resources(slack_env):
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=CAPTURES_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_object(
            Bucket=CAPTURES_BUCKET,
            Key="captures/lot-1/2026-05-04/09-23-11.jpg",
            Body=b"fake-image-data",
        )

        ssm_client = boto3.client("ssm", region_name=REGION)
        ssm_client.put_parameter(
            Name=SLACK_WEBHOOK_PARAM,
            Value=FAKE_WEBHOOK_URL,
            Type="SecureString",
            Overwrite=True,
        )

        yield {"s3": s3, "ssm": ssm_client}


@pytest.fixture
def sample_anpr_event():
    return {
        "s3_key": "captures/lot-1/2026-05-04/09-23-11.jpg",
        "device_id": "lot-1-cam",
        "lot_id": "lot-1",
        "timestamp": "2026-05-04T09:23:11Z",
    }


@pytest.fixture
def sample_sns_event():
    return {
        "Records": [
            {
                "Sns": {
                    "Message": json.dumps({
                        "rego": "ABC123",
                        "confidence": 0.92,
                        "s3_key": "captures/lot-1/2026-05-04/09-23-11.jpg",
                        "timestamp": "2026-05-04T09:23:11Z",
                        "lot_id": "lot-1",
                        "device_id": "lot-1-cam",
                    })
                }
            }
        ]
    }
