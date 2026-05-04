#!/usr/bin/env python3
import argparse
import os
from datetime import datetime, timezone

import boto3


TABLE_NAME = os.environ.get("VEHICLES_TABLE", "parking-vehicles")
REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")


def get_table():
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return dynamodb.Table(TABLE_NAME)


def cmd_add(args):
    rego = args.rego.strip().upper()
    table = get_table()
    table.put_item(Item={
        "rego": rego,
        "owner": args.owner,
        "make": args.make,
        "color": args.color,
        "is_employee": True,
        "added_date": datetime.now(timezone.utc).isoformat(),
    })
    print(f"Added {rego}")


def cmd_remove(args):
    rego = args.rego.strip().upper()
    get_table().delete_item(Key={"rego": rego})
    print(f"Removed {rego}")


def cmd_list(_args):
    table = get_table()
    response = table.scan()
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    if not items:
        print("No vehicles registered.")
        return

    col_widths = {
        "rego": max(len("Rego"), max(len(i.get("rego", "")) for i in items)),
        "owner": max(len("Owner"), max(len(i.get("owner", "")) for i in items)),
        "make": max(len("Make"), max(len(i.get("make", "")) for i in items)),
        "color": max(len("Color"), max(len(i.get("color", "")) for i in items)),
        "is_employee": len("Employee"),
        "added_date": max(len("Added"), max(len(i.get("added_date", "")) for i in items)),
    }

    def row(rego, owner, make, color, employee, added):
        return (
            f"{rego:<{col_widths['rego']}}  "
            f"{owner:<{col_widths['owner']}}  "
            f"{make:<{col_widths['make']}}  "
            f"{color:<{col_widths['color']}}  "
            f"{employee:<{col_widths['is_employee']}}  "
            f"{added:<{col_widths['added_date']}}"
        )

    header = row("Rego", "Owner", "Make", "Color", "Employee", "Added")
    separator = "-" * len(header)
    print(header)
    print(separator)

    for item in sorted(items, key=lambda i: i.get("rego", "")):
        print(row(
            item.get("rego", ""),
            item.get("owner", ""),
            item.get("make", ""),
            item.get("color", ""),
            str(item.get("is_employee", "")),
            item.get("added_date", ""),
        ))


def main():
    parser = argparse.ArgumentParser(description="Manage registered vehicles in the parking system.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Register a vehicle")
    add_parser.add_argument("--rego", required=True, help="Vehicle registration plate")
    add_parser.add_argument("--owner", required=True, help="Owner full name")
    add_parser.add_argument("--make", required=True, help="Vehicle make and model")
    add_parser.add_argument("--color", required=True, help="Vehicle color")
    add_parser.set_defaults(func=cmd_add)

    remove_parser = subparsers.add_parser("remove", help="Remove a registered vehicle")
    remove_parser.add_argument("--rego", required=True, help="Vehicle registration plate")
    remove_parser.set_defaults(func=cmd_remove)

    subparsers.add_parser("list", help="List all registered vehicles").set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
