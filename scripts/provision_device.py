#!/usr/bin/env python3
import argparse
import json
import os
import urllib.request

import boto3
from botocore.exceptions import ClientError


def parse_args():
    parser = argparse.ArgumentParser(description="Provision an ESP32 parking camera device in AWS IoT")
    parser.add_argument("--thing-name", required=True, help="IoT Thing name (e.g. lot-1-cam)")
    parser.add_argument("--lot-id", required=True, help="Parking lot ID (e.g. lot-1)")
    parser.add_argument("--bucket", default=None, help="S3 bucket name (fallback if not in CloudFormation outputs)")
    parser.add_argument("--region", default="ap-southeast-2", help="AWS region (default: ap-southeast-2)")
    return parser.parse_args()


def get_s3_bucket_from_stack(cf_client, bucket_arg):
    if bucket_arg:
        return bucket_arg
    try:
        response = cf_client.describe_stacks(StackName="ParkingMonitoringStack")
        outputs = response["Stacks"][0].get("Outputs", [])
        for output in outputs:
            if output["OutputKey"] == "CapturesBucketName":
                return output["OutputValue"]
    except ClientError:
        pass
    raise ValueError(
        "Could not determine S3 bucket name. Deploy the stack first or pass --bucket."
    )


def ensure_thing(iot_client, thing_name):
    try:
        iot_client.describe_thing(thingName=thing_name)
        print(f"Thing '{thing_name}' already exists, skipping creation.")
        return False
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    iot_client.create_thing(thingName=thing_name, thingTypeName="parking-camera")
    print(f"Created IoT Thing '{thing_name}'.")
    return True


def provision(args):
    iot_client = boto3.client("iot", region_name=args.region)
    cf_client = boto3.client("cloudformation", region_name=args.region)

    s3_bucket = get_s3_bucket_from_stack(cf_client, args.bucket)

    ensure_thing(iot_client, args.thing_name)

    cert_response = iot_client.create_keys_and_certificate(setAsActive=True)
    cert_arn = cert_response["certificateArn"]
    cert_pem = cert_response["certificatePem"]
    private_key_pem = cert_response["keyPair"]["PrivateKey"]
    print(f"Created certificate: {cert_arn}")

    iot_client.attach_policy(policyName="parking-camera-policy", target=cert_arn)
    print("Attached policy 'parking-camera-policy' to certificate.")

    iot_client.attach_thing_principal(thingName=args.thing_name, principal=cert_arn)
    print(f"Attached certificate to thing '{args.thing_name}'.")

    iot_endpoint = iot_client.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
    credential_provider_endpoint = iot_client.describe_endpoint(endpointType="iot:CredentialProvider")["endpointAddress"]

    root_ca_url = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"
    with urllib.request.urlopen(root_ca_url) as resp:
        root_ca_pem = resp.read().decode("utf-8")

    out_dir = os.path.join("output", args.thing_name)
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "device-cert.pem"), "w") as f:
        f.write(cert_pem)

    with open(os.path.join(out_dir, "device-private-key.pem"), "w") as f:
        f.write(private_key_pem)

    with open(os.path.join(out_dir, "amazon-root-ca1.pem"), "w") as f:
        f.write(root_ca_pem)

    config = {
        "wifi_ssid": "",
        "wifi_password": "",
        "lot_id": args.lot_id,
        "device_id": args.thing_name,
        "iot_endpoint": iot_endpoint,
        "s3_bucket": s3_bucket,
        "s3_region": args.region,
        "capture_burst": 3,
        "credential_provider_endpoint": credential_provider_endpoint,
    }
    with open(os.path.join(out_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nOutput files written to: {out_dir}/")
    print("  device-cert.pem")
    print("  device-private-key.pem")
    print("  amazon-root-ca1.pem")
    print("  config.json")
    print("\nNext steps:")
    print(f"  1. Open {out_dir}/config.json and fill in wifi_ssid and wifi_password.")
    print("  2. Flash all files in the output directory to the ESP32 LittleFS partition.")
    print("     e.g. using: esptool.py or the Arduino LittleFS upload plugin.")


if __name__ == "__main__":
    args = parse_args()
    provision(args)
