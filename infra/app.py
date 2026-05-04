#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.parking_stack import ParkingMonitoringStack

app = cdk.App()
ParkingMonitoringStack(
    app,
    "ParkingMonitoringStack",
    env=cdk.Environment(region="ap-southeast-2"),
)
app.synth()
