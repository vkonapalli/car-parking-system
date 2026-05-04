#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <LittleFS.h>

struct DeviceConfig {
    String wifi_ssid;
    String wifi_password;
    String lot_id;
    String device_id;
    String iot_endpoint;
    String s3_bucket;
    String s3_region;
    int capture_burst = 3;
    String credential_provider_endpoint;
};

inline bool loadConfig(DeviceConfig &config) {
    File f = LittleFS.open("/config.json", "r");
    if (!f) return false;

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, f);
    f.close();
    if (err) return false;

    config.wifi_ssid = doc["wifi_ssid"].as<String>();
    config.wifi_password = doc["wifi_password"].as<String>();
    config.lot_id = doc["lot_id"].as<String>();
    config.device_id = doc["device_id"].as<String>();
    config.iot_endpoint = doc["iot_endpoint"].as<String>();
    config.s3_bucket = doc["s3_bucket"].as<String>();
    config.s3_region = doc["s3_region"].as<String>();
    config.capture_burst = doc["capture_burst"] | 3;
    config.credential_provider_endpoint = doc["credential_provider_endpoint"].as<String>();

    return true;
}

inline String loadCertFile(const char *path) {
    File f = LittleFS.open(path, "r");
    if (!f) return String();
    String content = f.readString();
    f.close();
    return content;
}
