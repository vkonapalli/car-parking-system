#include "mqtt_handler.h"

#include <WiFiClientSecure.h>
#include <MQTT.h>
#include <ArduinoJson.h>

static constexpr int kPayloadSize = 384;

static WiFiClientSecure _tlsClient;
// Receive buffer sized for shadow delta messages only; we never subscribe to large topics.
static MQTTClient _mqttClient(256);

bool connectMQTT(const char* endpoint, const char* deviceId, const char* caCert,
                 const char* clientCert, const char* clientKey) {
    _tlsClient.setCACert(caCert);
    _tlsClient.setCertificate(clientCert);
    _tlsClient.setPrivateKey(clientKey);

    _mqttClient.begin(endpoint, 8883, _tlsClient);

    return _mqttClient.connect(deviceId);
}

bool publishCapture(const char* lotId, const char* deviceId, const char* timestamp,
                    const char* s3Key) {
    JsonDocument doc;
    doc["device_id"] = deviceId;
    doc["lot_id"] = lotId;
    doc["timestamp"] = timestamp;
    doc["s3_key"] = s3Key;

    char payload[kPayloadSize];
    serializeJson(doc, payload, sizeof(payload));

    char topic[64];
    snprintf(topic, sizeof(topic), "parking/%s/capture", lotId);

    return _mqttClient.publish(topic, payload);
}

bool updateShadow(const char* deviceId, const char* lastCapture, float batteryVoltage,
                  int32_t wifiRssi, const char* firmwareVersion) {
    JsonDocument doc;
    JsonObject reported = doc["state"]["reported"].to<JsonObject>();
    reported["last_capture"] = lastCapture;
    reported["battery_voltage"] = batteryVoltage;
    reported["wifi_rssi"] = wifiRssi;
    reported["firmware_version"] = firmwareVersion;

    char payload[kPayloadSize];
    serializeJson(doc, payload, sizeof(payload));

    char topic[80];
    snprintf(topic, sizeof(topic), "$aws/things/%s/shadow/update", deviceId);

    return _mqttClient.publish(topic, payload);
}

void disconnectMQTT() {
    _mqttClient.disconnect();
}
