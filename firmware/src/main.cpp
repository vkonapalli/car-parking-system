#include <Arduino.h>
#include <time.h>

#include "config.h"
#include "power_mgmt.h"
#include "ir_led.h"
#include "camera.h"
#include "wifi_manager.h"
#include "s3_upload.h"
#include "mqtt_handler.h"

#define FIRMWARE_VERSION "1.0.0"
#define NTP_SERVER       "pool.ntp.org"

static void syncNtp() {
    configTime(0, 0, NTP_SERVER);
    struct tm t;
    for (int i = 0; i < 50 && !getLocalTime(&t); i++) {
        delay(100);
    }
}

static void formatTimestamp(char *buf, size_t len) {
    struct tm t;
    if (getLocalTime(&t)) {
        strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &t);
    } else {
        snprintf(buf, len, "%lums", (unsigned long)millis());
    }
}

void setup() {
    Serial.begin(115200);

    WakeCause cause = getWakeCause();
    Serial.printf("Wake cause: %d\n", (int)cause);

    if (shouldDebounce()) {
        Serial.println("Debounce active, returning to sleep");
        enterDeepSleep();
        return;
    }

    recordWakeTime();

    DeviceConfig config;
    if (!loadConfig(config)) {
        Serial.println("Config load failed");
        enterDeepSleep();
        return;
    }

    String cert     = loadCertFile("/device-cert.pem");
    String key      = loadCertFile("/device-private-key.pem");
    String rootCa   = loadCertFile("/amazon-root-ca1.pem");
    if (cert.isEmpty() || key.isEmpty() || rootCa.isEmpty()) {
        Serial.println("Cert load failed");
        enterDeepSleep();
        return;
    }

    initIR();
    enableIR();

    initCamera();
    uint8_t *frame = nullptr;
    size_t frameLen = 0;
    captureBestFrame(config.capture_burst, &frame, &frameLen);

    disableIR();
    deinitCamera();

    if (!frame || frameLen == 0) {
        Serial.println("Capture failed");
        enterDeepSleep();
        return;
    }

    if (!connectWiFi(config.wifi_ssid, config.wifi_password)) {
        Serial.println("WiFi failed after retries");
        enterDeepSleep();
        return;
    }

    syncNtp();

    AwsCredentials creds;
    if (!getAwsCredentials(config, cert, key, rootCa, creds)) {
        Serial.println("IoT credentials failed");
        disconnectWiFi();
        enterDeepSleep();
        return;
    }

    char timestamp[32];
    formatTimestamp(timestamp, sizeof(timestamp));

    String s3Key = generateS3Key(config.lot_id, timestamp);

    if (!uploadToS3(creds, s3Key, frame, frameLen)) {
        Serial.println("S3 upload failed, continuing");
    }

    if (connectMQTT(config, cert, key, rootCa)) {
        publishCapture(config.lot_id, s3Key, timestamp);
        updateShadow(readBatteryVoltage(), getWiFiRSSI(), FIRMWARE_VERSION);
        disconnectMQTT();
    } else {
        Serial.println("MQTT connect failed, continuing");
    }

    disconnectWiFi();
    enterDeepSleep();
}

void loop() {}
