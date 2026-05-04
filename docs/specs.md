# Parking Monitoring System - Detailed Specifications

## Phase 1: Cloud Infrastructure

### Task 1.1: CDK Project Setup

**File:** `infra/app.py`, `infra/requirements.txt`, `infra/stacks/__init__.py`

**Spec:**
- Initialize CDK app with Python
- Target region: `ap-southeast-2`
- Stack name: `ParkingMonitoringStack`
- Dependencies: `aws-cdk-lib`, `constructs`

**Acceptance:**
- `cdk synth` produces valid CloudFormation template
- `cdk ls` lists the stack

---

### Task 1.2: S3 Bucket for Captures

**File:** `infra/stacks/parking_stack.py`

**Spec:**
- Bucket name: auto-generated (CDK physical name)
- Lifecycle rule: expire objects after 30 days
- Block all public access
- Encryption: S3-managed (SSE-S3)
- CORS: none needed (no browser access)

**Acceptance:**
- Bucket created with lifecycle and encryption
- Output: bucket name exported as stack output

---

### Task 1.3: DynamoDB Tables

**File:** `infra/stacks/parking_stack.py`

**Spec:**

Table: `parking-vehicles`
- PK: `rego` (String)
- Attributes: `owner_name`, `vehicle_make`, `vehicle_color`, `is_employee` (bool), `added_date`
- Billing: on-demand (PAY_PER_REQUEST)
- No TTL

Table: `parking-events`
- PK: `lot_id` (String)
- SK: `timestamp` (String) — ISO 8601 format
- Attributes: `rego`, `confidence`, `is_known` (bool), `s3_key`, `device_id`, `plate_recognizer_response`
- Billing: on-demand
- TTL: attribute `expires_at`, set to 90 days from event time

**Acceptance:**
- Both tables created with correct key schemas
- Events table has TTL enabled on `expires_at`
- Output: both table names as stack outputs

---

### Task 1.4: SNS Topic

**File:** `infra/stacks/parking_stack.py`

**Spec:**
- Topic name: `parking-unknown-vehicle`
- No subscription in CDK (added when slack-notifier Lambda is created)

**Acceptance:**
- Topic created
- Output: topic ARN as stack output

---

### Task 1.5: SSM Parameters (Placeholders)

**File:** `infra/stacks/parking_stack.py`

**Spec:**
- `/parking/plate-recognizer-api-key` — StringParameter (placeholder value, manually updated to SecureString via console/CLI after deploy)
- `/parking/slack-webhook-url` — StringParameter (same)

Note: CDK doesn't support creating SecureString parameters. Create as String with
placeholder value. User updates to SecureString manually post-deploy.

**Acceptance:**
- Parameters created with placeholder values
- Documented in README that user must update these post-deploy

---

### Task 1.6: IoT Core Resources

**File:** `infra/stacks/parking_stack.py`

**Spec:**

Thing Type: `parking-camera`

IoT Policy: `parking-camera-policy`
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:*:*:client/${iot:Connection.Thing.ThingName}"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": [
        "arn:aws:iot:*:*:topic/parking/+/capture",
        "arn:aws:iot:*:*:topic/$aws/things/${iot:Connection.Thing.ThingName}/shadow/update"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["iot:Subscribe"],
      "Resource": [
        "arn:aws:iot:*:*:topicfilter/$aws/things/${iot:Connection.Thing.ThingName}/shadow/update/delta"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["iot:Receive"],
      "Resource": [
        "arn:aws:iot:*:*:topic/$aws/things/${iot:Connection.Thing.ThingName}/shadow/update/delta"
      ]
    }
  ]
}
```

IoT Credential Provider:
- IAM Role: `parking-camera-s3-role`
  - Trust policy: `credentials.iot.amazonaws.com`
  - Permissions: `s3:PutObject` on captures bucket `captures/*` prefix only
- Role Alias: `parking-camera-role-alias`

Topic Rule: `parking_capture_rule`
- SQL: `SELECT * FROM 'parking/+/capture'`
- Action: invoke anpr-processor Lambda
- Error action: CloudWatch Logs (log group: `/iot/parking-errors`)

**Acceptance:**
- Thing type created
- IoT policy created
- Role alias created, linked to S3 role
- Topic rule invokes Lambda on matching messages
- Error action logs to CloudWatch

---

### Task 1.7: ANPR Processor Lambda

**Files:** `lambdas/anpr_processor/handler.py`, `lambdas/anpr_processor/requirements.txt`

**Spec:**

Runtime: Python 3.12
Memory: 256 MB
Timeout: 30 seconds
Handler: `handler.lambda_handler`

Dependencies: `requests` (for Plate Recognizer API call)

Environment variables (set by CDK):
- `CAPTURES_BUCKET`
- `VEHICLES_TABLE`
- `EVENTS_TABLE`
- `SNS_TOPIC_ARN`
- `PLATE_RECOGNIZER_API_KEY_PARAM` (SSM param name)
- `CONFIDENCE_THRESHOLD` (default: "0.7")

Logic:
```
def lambda_handler(event, context):
    1. Extract s3_key, device_id, lot_id, timestamp from event
    2. Download image from S3 (CAPTURES_BUCKET / s3_key)
    3. Fetch Plate Recognizer API key from SSM (cache in global scope)
    4. POST image to https://api.platerecognizer.com/v1/plate-reader/
       - Headers: Authorization: Token {api_key}
       - Body: multipart form with image file
       - Data: regions=nz
    5. Parse response:
       - If no plates found → log event as "no_plate_detected", return
       - Extract best result (highest score)
       - rego = result["plate"].upper()
       - confidence = result["score"]
    6. If confidence < CONFIDENCE_THRESHOLD → log as "low_confidence", return
    7. Query DynamoDB vehicles table: get_item(Key={"rego": rego})
       - is_known = True if item exists, False otherwise
    8. Put event to DynamoDB events table:
       {
         "lot_id": lot_id,
         "timestamp": timestamp,
         "rego": rego,
         "confidence": Decimal(str(confidence)),
         "is_known": is_known,
         "s3_key": s3_key,
         "device_id": device_id,
         "owner_name": vehicle.get("owner_name") if known else None,
         "expires_at": int(now + 90 days)
       }
    9. If not is_known:
       - Publish to SNS topic:
         {
           "rego": rego,
           "confidence": confidence,
           "s3_key": s3_key,
           "timestamp": timestamp,
           "lot_id": lot_id,
           "device_id": device_id
         }
    10. Return {"statusCode": 200, "rego": rego, "is_known": is_known}
```

SSM caching: fetch API key once per Lambda cold start, store in module-level variable.

**Acceptance:**
- Handles happy path (plate found, known vehicle)
- Handles happy path (plate found, unknown vehicle → SNS)
- Handles no plate detected
- Handles low confidence
- Handles Plate Recognizer API errors gracefully (log, don't crash)
- All AWS interactions use boto3 with resource names from env vars

---

### Task 1.8: Slack Notifier Lambda

**Files:** `lambdas/slack_notifier/handler.py`, `lambdas/slack_notifier/requirements.txt`

**Spec:**

Runtime: Python 3.12
Memory: 128 MB
Timeout: 10 seconds
Handler: `handler.lambda_handler`

Dependencies: none (use urllib3 bundled in Lambda runtime)

Environment variables:
- `SLACK_WEBHOOK_URL_PARAM` (SSM param name)
- `CAPTURES_BUCKET`

Logic:
```
def lambda_handler(event, context):
    1. Parse SNS message from event["Records"][0]["Sns"]["Message"] (JSON string)
    2. Extract rego, confidence, s3_key, timestamp, lot_id
    3. Generate presigned S3 URL for s3_key (1 hour expiry)
    4. Fetch Slack webhook URL from SSM (cached in module scope)
    5. Build Slack Block Kit payload:
       {
         "blocks": [
           {"type": "header", "text": {"type": "plain_text", "text": "Unknown Vehicle Detected"}},
           {"type": "section", "fields": [
             {"type": "mrkdwn", "text": "*Rego:*\n{rego}"},
             {"type": "mrkdwn", "text": "*Confidence:*\n{confidence:.0%}"},
             {"type": "mrkdwn", "text": "*Time:*\n{timestamp formatted to NZ timezone}"},
             {"type": "mrkdwn", "text": "*Lot:*\n{lot_id}"}
           ]},
           {"type": "image", "image_url": presigned_url, "alt_text": "Captured plate image"}
         ]
       }
    6. POST to Slack webhook URL
    7. Log response status
```

Timezone: convert UTC timestamp to `Pacific/Auckland` for display.

**Acceptance:**
- Parses SNS event correctly
- Generates valid presigned URL
- Posts well-formatted Block Kit message to Slack
- Handles Slack API errors (log, don't crash)

---

### Task 1.9: Wire Lambdas into CDK Stack

**File:** `infra/stacks/parking_stack.py`

**Spec:**
- Create both Lambda functions with bundled code from `lambdas/` directory
- Grant anpr-processor: S3 read, DynamoDB read/write, SSM read, SNS publish
- Grant slack-notifier: S3 read (for presigned URLs), SSM read
- Subscribe slack-notifier to SNS topic
- Grant IoT Rule permission to invoke anpr-processor
- Set environment variables on both Lambdas

**Acceptance:**
- Both Lambdas deployed with correct permissions
- SNS subscription wired
- IoT Rule action invokes anpr-processor

---

### Task 1.10: Unit Tests for Lambdas

**Files:** `tests/test_anpr_processor.py`, `tests/test_slack_notifier.py`, `tests/conftest.py`

**Spec:**

Framework: pytest
Mocking: moto (for AWS), responses or unittest.mock (for HTTP)

Test cases for anpr-processor:
1. `test_known_vehicle` — plate found, rego in whitelist → event logged, no SNS
2. `test_unknown_vehicle` — plate found, rego NOT in whitelist → event logged + SNS published
3. `test_no_plate_detected` — Plate Recognizer returns empty results → event logged as no_plate
4. `test_low_confidence` — confidence below threshold → event logged as low_confidence, no SNS
5. `test_plate_recognizer_error` — API returns 500 → handled gracefully

Test cases for slack-notifier:
1. `test_slack_message_format` — verify Block Kit payload structure
2. `test_presigned_url_generated` — verify S3 presigned URL is created
3. `test_timezone_conversion` — UTC timestamp displayed as NZ time

**Acceptance:**
- All tests pass
- No real AWS or HTTP calls made

---

## Phase 2: Scripts & Integration Testing

### Task 2.1: Device Provisioning Script

**File:** `scripts/provision_device.py`

**Spec:**

CLI: `python scripts/provision_device.py --thing-name lot-1-cam --lot-id lot-1`

Logic:
1. Create IoT Thing (type: `parking-camera`)
2. Create keys and certificate
3. Attach policy `parking-camera-policy` to certificate
4. Attach certificate to thing
5. Write output files to `output/{thing_name}/`:
   - `device-cert.pem`
   - `device-private-key.pem`
   - `amazon-root-ca1.pem` (downloaded from Amazon)
   - `config.json` with:
     ```json
     {
       "wifi_ssid": "",
       "wifi_password": "",
       "lot_id": "lot-1",
       "device_id": "lot-1-cam",
       "iot_endpoint": "<fetched from describe-endpoint>",
       "s3_bucket": "<from stack output or param>",
       "s3_region": "ap-southeast-2",
       "capture_burst": 3,
       "credential_provider_endpoint": "<fetched>"
     }
     ```
6. Print instructions for user to fill WiFi credentials and flash to ESP32

**Acceptance:**
- Creates thing + certs in AWS
- Outputs all files needed for ESP32 LittleFS
- Idempotent: skips creation if thing already exists

---

### Task 2.2: Vehicle Management Script

**File:** `scripts/register_vehicle.py`

**Spec:**

CLI using argparse with subcommands:
```
python scripts/register_vehicle.py add --rego ABC123 --owner "John Smith" --make "Toyota Corolla" --color "White"
python scripts/register_vehicle.py remove --rego ABC123
python scripts/register_vehicle.py list
```

Logic:
- `add`: put_item to parking-vehicles table. Rego normalized to uppercase, stripped.
  Added `added_date` as ISO 8601 timestamp.
- `remove`: delete_item from parking-vehicles table.
- `list`: scan table, print as formatted table (tabulate or simple print).

Table name: read from env var `VEHICLES_TABLE` or default `parking-vehicles`.

**Acceptance:**
- Can add, remove, list vehicles
- Rego is normalized (uppercase, stripped)
- Duplicate add overwrites (upsert)

---

### Task 2.3: End-to-End Test Script

**File:** `scripts/e2e_test.py`

**Spec:**

Simulates the full flow without hardware:
1. Upload a test NZ plate image to S3 bucket (provide a sample image path as arg)
2. Construct the MQTT payload that the ESP32 would send
3. Invoke anpr-processor Lambda directly (using boto3 Lambda.invoke)
4. Print the result: detected rego, is_known, confidence
5. Check if Slack notification was sent (by querying SNS publish metrics or just checking Slack)

CLI: `python scripts/e2e_test.py --image path/to/plate.jpg`

**Acceptance:**
- Uploads image to correct S3 path
- Invokes Lambda and prints result
- Confirms end-to-end flow works

---

## Phase 3: Firmware

### Task 3.1: PlatformIO Project Setup

**Files:** `firmware/platformio.ini`, `firmware/src/main.cpp`

**Spec:**
```ini
[env:esp32s3cam]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
monitor_speed = 115200
lib_deps =
    bblanchon/ArduinoJson@^7
    256dpi/MQTT@^2.5
board_build.partitions = huge_app.csv
board_build.filesystem = littlefs
```

Scaffold `main.cpp` with empty `setup()` and `loop()` functions.

**Acceptance:**
- Project compiles with PlatformIO
- Board and dependencies configured

---

### Task 3.2: WiFi + Camera Initialization

**File:** `firmware/src/main.cpp`

**Spec:**
- Read config from LittleFS (`/config.json`)
- Connect to WiFi with SSID/password from config
- Initialize camera: OV5640, JPEG mode, QSXGA (2560x1920) resolution
- LED flash control on a GPIO for debugging

**Acceptance:**
- ESP32 boots, connects WiFi, initializes camera
- Serial output confirms connection

---

### Task 3.3: Image Capture + Frame Selection

**File:** `firmware/src/main.cpp`

**Spec:**
- On wake, capture `capture_burst` frames (default 3)
- For each frame, compute a sharpness score (variance of Laplacian approximation)
- Select sharpest frame
- Free other frame buffers

**Acceptance:**
- Captures multiple frames
- Selects sharpest one
- Memory is properly freed

---

### Task 3.4: S3 Upload via IoT Credential Provider

**File:** `firmware/src/main.cpp`

**Spec:**
- Call IoT credential provider endpoint to get temporary AWS credentials
  - HTTPS GET to `https://{cred_endpoint}/role-aliases/{role_alias}/credentials`
  - Uses device X.509 cert for auth
  - Returns AccessKeyId, SecretAccessKey, SessionToken
- Upload JPEG to S3 using AWS SigV4 signed PUT request
  - Path: `captures/{lot_id}/{date}/{time}.jpg`
- Use WiFiClientSecure for TLS

**Acceptance:**
- Gets temp credentials successfully
- Uploads image to correct S3 path
- Handles credential refresh

---

### Task 3.5: MQTT Publish + Device Shadow

**File:** `firmware/src/main.cpp`

**Spec:**
- Connect to IoT Core MQTT endpoint (port 8883, TLS, X.509 client cert)
- Publish to `parking/{lot_id}/capture`:
  ```json
  {
    "device_id": "lot-1-cam",
    "lot_id": "lot-1",
    "timestamp": "2026-05-04T09:23:11Z",
    "s3_key": "captures/lot-1/2026-05-04/09-23-11.jpg"
  }
  ```
- Update device shadow reported state:
  ```json
  {
    "state": {
      "reported": {
        "last_capture": "2026-05-04T09:23:11Z",
        "battery_voltage": 3.85,
        "wifi_rssi": -42,
        "firmware_version": "1.0.0"
      }
    }
  }
  ```
- Disconnect cleanly

**Acceptance:**
- MQTT message published
- Device shadow updated
- Clean disconnect

---

### Task 3.6: Deep Sleep + PIR Wake

**File:** `firmware/src/main.cpp`

**Spec:**
- After MQTT publish + disconnect, enter deep sleep
- Configure ext0 wake source on PIR GPIO pin (e.g. GPIO1), HIGH level trigger
- On wake, check wake cause (PIR vs reset)
- Debounce: if last wake was < 30 seconds ago (stored in RTC memory), go back to sleep
  (prevents repeated triggers from same vehicle)

**Acceptance:**
- Enters deep sleep after processing
- Wakes on PIR motion
- Debounce prevents rapid re-triggers
- Current draw in deep sleep < 20μA (verify with multimeter if possible)

---

### Task 3.7: IR LED Control

**File:** `firmware/src/main.cpp`

**Spec:**
- Control IR LED board via MOSFET on a GPIO pin
- On wake: turn on IR LEDs → wait 100ms for illumination → capture frames → turn off
- Only activate at night (can use a simple LDR on ADC, or always-on since IR is invisible)

For simplicity in v1: always activate IR LEDs during capture regardless of ambient light.

**Acceptance:**
- IR LEDs turn on before capture, off after
- MOSFET switching works
- No visible flash to human eye (850nm has faint red glow, acceptable)

---

### Task 3.8: Assemble Full Firmware Flow

**File:** `firmware/src/main.cpp`

**Spec:**

Bring all components together into the main flow:
```
setup():
  1. Check wake cause (PIR or cold boot)
  2. If debounce period active → deep sleep immediately
  3. Store wake timestamp in RTC memory
  4. Init serial (for debug logging)
  5. Read config from LittleFS
  6. Turn on IR LEDs
  7. Init camera
  8. Capture burst, select sharpest
  9. Turn off IR LEDs
  10. Connect WiFi
  11. Get IoT temp credentials
  12. Upload image to S3
  13. Connect MQTT
  14. Publish capture message
  15. Update device shadow
  16. Disconnect MQTT + WiFi
  17. Enter deep sleep

loop():
  // never reached (deep sleep resets to setup)
```

**Acceptance:**
- Full cycle completes in < 15 seconds
- Handles WiFi connection failure (retry 3x, then sleep and retry on next trigger)
- Handles S3/MQTT failure (log error, sleep, retry next trigger)
- No memory leaks across cycles
