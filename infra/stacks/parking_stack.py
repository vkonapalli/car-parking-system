import aws_cdk as cdk
from aws_cdk import (
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subscriptions,
    aws_ssm as ssm,
    aws_iam as iam,
    aws_iot as iot,
    aws_lambda as lambda_,
    aws_logs as logs,
)
from constructs import Construct


class ParkingMonitoringStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        captures_bucket = s3.Bucket(
            self,
            "CapturesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(expiration=cdk.Duration.days(30))
            ],
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        vehicles_table = dynamodb.Table(
            self,
            "VehiclesTable",
            table_name="parking-vehicles",
            partition_key=dynamodb.Attribute(
                name="rego", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        events_table = dynamodb.Table(
            self,
            "EventsTable",
            table_name="parking-events",
            partition_key=dynamodb.Attribute(
                name="lot_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        unknown_vehicle_topic = sns.Topic(
            self,
            "UnknownVehicleTopic",
            topic_name="parking-unknown-vehicle",
        )

        ssm.StringParameter(
            self,
            "SlackWebhookUrlParam",
            parameter_name="/parking/slack-webhook-url",
            string_value="PLACEHOLDER",
        )

        iot.CfnThingType(
            self,
            "ParkingCameraThingType",
            thing_type_name="parking-camera",
        )

        iot.CfnPolicy(
            self,
            "ParkingCameraPolicy",
            policy_name="parking-camera-policy",
            policy_document={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "iot:Connect",
                        "Resource": "arn:aws:iot:*:*:client/${iot:Connection.Thing.ThingName}",
                    },
                    {
                        "Effect": "Allow",
                        "Action": "iot:Publish",
                        "Resource": [
                            "arn:aws:iot:*:*:topic/parking/+/capture",
                            "arn:aws:iot:*:*:topic/$aws/things/${iot:Connection.Thing.ThingName}/shadow/update",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["iot:Subscribe"],
                        "Resource": [
                            "arn:aws:iot:*:*:topicfilter/$aws/things/${iot:Connection.Thing.ThingName}/shadow/update/delta",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["iot:Receive"],
                        "Resource": [
                            "arn:aws:iot:*:*:topic/$aws/things/${iot:Connection.Thing.ThingName}/shadow/update/delta",
                        ],
                    },
                ],
            },
        )

        camera_s3_role = iam.Role(
            self,
            "CameraS3Role",
            role_name="parking-camera-s3-role",
            assumed_by=iam.ServicePrincipal("credentials.iot.amazonaws.com"),
        )
        camera_s3_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[captures_bucket.arn_for_objects("captures/*")],
            )
        )

        iot.CfnRoleAlias(
            self,
            "CameraRoleAlias",
            role_alias="parking-camera-role-alias",
            role_arn=camera_s3_role.role_arn,
        )

        anpr_processor = lambda_.DockerImageFunction(
            self,
            "AnprProcessor",
            function_name="anpr-processor",
            code=lambda_.DockerImageCode.from_image_asset("../lambdas/anpr_processor"),
            memory_size=512,
            timeout=cdk.Duration.seconds(60),
            environment={
                "CAPTURES_BUCKET": captures_bucket.bucket_name,
                "VEHICLES_TABLE": vehicles_table.table_name,
                "EVENTS_TABLE": events_table.table_name,
                "SNS_TOPIC_ARN": unknown_vehicle_topic.topic_arn,
                "CONFIDENCE_THRESHOLD": "0.7",
            },
        )

        captures_bucket.grant_read(anpr_processor)
        vehicles_table.grant_read_write_data(anpr_processor)
        events_table.grant_read_write_data(anpr_processor)
        unknown_vehicle_topic.grant_publish(anpr_processor)
        slack_notifier = lambda_.Function(
            self,
            "SlackNotifier",
            function_name="slack-notifier",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("../lambdas/slack_notifier"),
            memory_size=128,
            timeout=cdk.Duration.seconds(10),
            environment={
                "SLACK_WEBHOOK_URL_PARAM": "/parking/slack-webhook-url",
                "CAPTURES_BUCKET": captures_bucket.bucket_name,
            },
        )

        captures_bucket.grant_read(slack_notifier)
        slack_notifier.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    self.format_arn(
                        service="ssm",
                        resource="parameter",
                        resource_name="parking/slack-webhook-url",
                    )
                ],
            )
        )

        unknown_vehicle_topic.add_subscription(
            sns_subscriptions.LambdaSubscription(slack_notifier)
        )

        iot_error_log_group = logs.LogGroup(
            self,
            "IotErrorLogGroup",
            log_group_name="/iot/parking-errors",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        iot_rule_role = iam.Role(
            self,
            "IotRuleRole",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
        )
        anpr_processor.grant_invoke(iot_rule_role)
        iot_error_log_group.grant_write(iot_rule_role)

        iot.CfnTopicRule(
            self,
            "ParkingCaptureRule",
            topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                sql="SELECT * FROM 'parking/+/capture'",
                actions=[
                    iot.CfnTopicRule.ActionProperty(
                        lambda_=iot.CfnTopicRule.LambdaActionProperty(
                            function_arn=anpr_processor.function_arn,
                        )
                    )
                ],
                error_action=iot.CfnTopicRule.ActionProperty(
                    cloudwatch_logs=iot.CfnTopicRule.CloudwatchLogsActionProperty(
                        log_group_name=iot_error_log_group.log_group_name,
                        role_arn=iot_rule_role.role_arn,
                    )
                ),
            ),
            rule_name="parking_capture_rule",
        )

        anpr_processor.add_permission(
            "IotRuleInvoke",
            principal=iam.ServicePrincipal("iot.amazonaws.com"),
            source_arn=self.format_arn(
                service="iot",
                resource="rule",
                resource_name="parking_capture_rule",
            ),
        )

        cdk.CfnOutput(self, "CapturesBucketName", value=captures_bucket.bucket_name)
        cdk.CfnOutput(self, "VehiclesTableName", value=vehicles_table.table_name)
        cdk.CfnOutput(self, "EventsTableName", value=events_table.table_name)
        cdk.CfnOutput(self, "UnknownVehicleTopicArn", value=unknown_vehicle_topic.topic_arn)
