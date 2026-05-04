# Parking Monitoring System - Implementation Plan

## Overview

IoT-based parking monitoring system using ESP32-S3-CAM at the edge and AWS cloud
for ANPR processing, vehicle lookup, and alerting.

## System Context

- **Location:** Single lot, NZ
- **Scale:** ~7 employee vehicles
- **Hardware:** ESP32-S3-CAM + PIR + solar/LiPo (ordered separately)
- **Detection:** Motion-triggered capture, real-time ANPR
- **Action:** Log all vehicles, Slack alert on unknown rego
- **No barrier/gate** — passive monitoring only

---

## Architecture

```
ESP32-S3-CAM (IoT Thing)
  │
  ├─ MQTT/TLS (X.509) ──► AWS IoT Core
  │                           │
  │                           ├─ IoT Rule: on 'parking/+/capture'
  │                           │     → invoke Lambda (anpr-processor)
  │                           │
  │                           └─ Device Shadow
  │                                 → health, config, last seen
  │
  └─ HTTPS (IoT Cred Provider) ──► S3 (capture images)
                                      │
                                      └─ (referenced by Lambda, not event-triggered)

Lambda: anpr-processor
  │ → Download image from S3
  │ → Call Plate Recognizer API
  │ → Query DynamoDB vehicles table
  │ → Log event to DynamoDB events table
  │ → If unknown → publish to SNS
  │
  └─► SNS Topic
        └─► Slack webhook (via SNS → Lambda or SNS → HTTPS)
```

### Why IoT Rule triggers Lambda (not S3 event)

The MQTT message contains metadata (device_id, timestamp, s3_key) and arrives
after the image is uploaded. Single trigger point, no race condition between
S3 upload completing and Lambda firing.

---

## Project Structure

```
car-rego/
├── docs/
│   └── implementation-plan.md
├── firmware/                     # ESP32 Arduino/PlatformIO project
│   ├── platformio.ini
│   └── src/
│       └── main.cpp              # Single-file firmware
├── infra/                        # AWS CDK (Python)
│   ├── app.py
│   ├── requirements.txt
│   └── stacks/
│       └── parking_stack.py      # All AWS resources in one stack
├── lambdas/
│   ├── anpr_processor/
│   │   ├── handler.py            # ANPR + lookup + alert logic
│   │   └── requirements.txt
│   └── slack_notifier/
│       ├── handler.py            # SNS → Slack webhook formatter
│       └── requirements.txt
├── scripts/
│   ├── register_vehicle.py       # CLI to add/remove vehicles from whitelist
│   └── provision_device.py       # Create IoT Thing + certs, output for flashing
└── tests/
    ├── test_anpr_processor.py
    └── test_slack_notifier.py
```

---

## Component Details

### 1. AWS Infrastructure (CDK)

Single stack containing:

- **IoT Core**
  - Thing Type: `parking-camera`
  - Thing: `lot-1-cam` (created via provisioning script, not CDK)
  - Policy: allows publish to `parking/+/capture`, connect, subscribe to shadow
  - Topic Rule: `parking/+/capture` → Lambda

- **S3 Bucket**
  - `parking-captures-{account_id}`
  - Lifecycle: delete after 30 days
  - Bucket policy: IoT credential provider role can PutObject

- **DynamoDB Tables**
  - `parking-vehicles` (PK: `rego`) — whitelist
  - `parking-events` (PK: `lot_id`, SK: `timestamp`) — event log, TTL 90 days

- **Lambda Functions**
  - `anpr-processor` — triggered by IoT Rule
  - `slack-notifier` — triggered by SNS

- **SNS Topic**
  - `parking-unknown-vehicle`
  - Subscription: Lambda (slack-notifier)

- **SSM Parameters**
  - `/parking/plate-recognizer-api-key` (SecureString)
  - `/parking/slack-webhook-url` (SecureString)

- **IAM Roles**
  - Lambda execution roles (scoped to specific resources)
  - IoT credential provider role (S3 PutObject only)

### 2. Lambda: anpr-processor

**Trigger:** IoT Rule action (direct Lambda invoke)

**Input payload (from MQTT):**
```json
{
  "device_id": "lot-1-cam",
  "lot_id": "lot-1",
  "timestamp": "2026-05-04T09:23:11Z",
  "s3_key": "captures/lot-1/2026-05-04/09-23-11.jpg",
  "frame_count": 3
}
```

**Logic:**
1. Download image from S3
2. POST to Plate Recognizer API (`https://api.platerecognizer.com/v1/plate-reader/`)
   - Set `regions: ["nz"]` for NZ plate format
3. Extract best plate result (highest confidence)
4. If confidence < threshold (from env var, default 0.7) → log as `unreadable`, skip alert
5. Query DynamoDB `parking-vehicles` table by rego
6. Write event to `parking-events` table
7. If vehicle unknown → publish to SNS topic with rego, confidence, S3 image URL, timestamp

**Environment variables:**
- `PLATE_RECOGNIZER_API_KEY_PARAM` → SSM parameter name
- `VEHICLES_TABLE` → DynamoDB table name
- `EVENTS_TABLE` → DynamoDB table name
- `SNS_TOPIC_ARN` → unknown vehicle topic
- `CAPTURES_BUCKET` → S3 bucket name
- `CONFIDENCE_THRESHOLD` → minimum confidence (default 0.7)

### 3. Lambda: slack-notifier

**Trigger:** SNS subscription

**Input (from SNS message body):**
```json
{
  "rego": "ABC123",
  "confidence": 0.92,
  "s3_key": "captures/lot-1/2026-05-04/09-23-11.jpg",
  "timestamp": "2026-05-04T09:23:11Z",
  "lot_id": "lot-1",
  "device_id": "lot-1-cam"
}
```

**Logic:**
1. Generate a presigned S3 URL for the capture image (1 hour expiry)
2. Format Slack message (Block Kit):
   - Header: "Unknown Vehicle Detected"
   - Fields: rego, time, lot, confidence
   - Image: presigned URL
3. POST to Slack webhook URL (from SSM parameter)

### 4. ESP32-S3-CAM Firmware

**Framework:** Arduino via PlatformIO

**Libraries:**
- `arduino-esp32` (ESP32 board support)
- `aws-iot-device-sdk-embedded-c` or `arduino-mqtt` + `WiFiClientSecure`
- `esp32-camera` (built into board support)

**Boot sequence:**
1. Wake from deep sleep (PIR trigger on GPIO)
2. Initialize camera with configured resolution + lens settings
3. Connect WiFi
4. Connect to IoT Core via MQTT (TLS, X.509 cert from SPIFFS/LittleFS)
5. Capture burst of 3 frames, pick sharpest (Laplacian variance)
6. Upload image to S3 via HTTPS (using IoT credential provider for temp creds)
7. Publish MQTT message to `parking/{lot_id}/capture` with metadata
8. Update device shadow (reported state: last_capture, battery_voltage, wifi_rssi)
9. Disconnect WiFi
10. Enter deep sleep, wake on PIR

**Configuration (stored in LittleFS):**
```json
{
  "wifi_ssid": "...",
  "wifi_password": "...",
  "lot_id": "lot-1",
  "device_id": "lot-1-cam",
  "iot_endpoint": "xxxxx.iot.ap-southeast-2.amazonaws.com",
  "s3_bucket": "parking-captures-xxxx",
  "s3_region": "ap-southeast-2",
  "capture_burst": 3
}
```

**Certificates (stored in LittleFS):**
- `device-cert.pem`
- `device-private-key.pem`
- `amazon-root-ca1.pem`

### 5. Device Provisioning Script

`scripts/provision_device.py`

**What it does:**
1. Creates IoT Thing in AWS
2. Creates and attaches X.509 certificate
3. Attaches IoT policy
4. Outputs certificate files + config JSON ready to flash to ESP32 LittleFS
5. Registers IoT credential provider role alias (for S3 access)

### 6. Vehicle Management Script

`scripts/register_vehicle.py`

**CLI interface:**
```bash
# Add a vehicle
python scripts/register_vehicle.py add --rego "ABC123" --owner "John Smith" --make "Toyota Corolla"

# Remove a vehicle
python scripts/register_vehicle.py remove --rego "ABC123"

# List all vehicles
python scripts/register_vehicle.py list
```

---

## Build Order

### Phase 1: Cloud Infrastructure
1. CDK stack with all AWS resources
2. anpr-processor Lambda
3. slack-notifier Lambda
4. Unit tests for both Lambdas

### Phase 2: Scripts & Manual Testing
5. Device provisioning script
6. Vehicle management script
7. Manual end-to-end test (upload test image to S3, trigger Lambda manually)

### Phase 3: Firmware
8. ESP32 firmware (camera + WiFi + MQTT + S3 upload + deep sleep)
9. Integration test with real hardware

### Phase 4: Polish
10. Dashboard (future — not in initial scope)
11. Push notifications (future — extend SNS with mobile push)

---

## AWS Region

`ap-southeast-2` (Sydney) — closest to NZ

## Testing Strategy

- **Unit tests:** Mock AWS services (moto) + mock Plate Recognizer API responses
- **Integration test:** Upload a real NZ plate image, verify end-to-end flow
- **Hardware test:** ESP32 captures a plate at 5m, verify ANPR accuracy before full deployment
