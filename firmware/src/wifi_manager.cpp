#include "wifi_manager.h"
#include <WiFi.h>

static const unsigned long CONNECT_TIMEOUT_MS = 10000;

bool connectWiFi(const char* ssid, const char* password, int maxRetries) {
    WiFi.mode(WIFI_STA);

    for (int attempt = 1; attempt <= maxRetries; attempt++) {
        Serial.printf("[WiFi] Connecting to %s (attempt %d/%d)\n", ssid, attempt, maxRetries);
        WiFi.begin(ssid, password);

        wl_status_t status = static_cast<wl_status_t>(WiFi.waitForConnectResult(CONNECT_TIMEOUT_MS));

        if (status == WL_CONNECTED) {
            Serial.printf("[WiFi] Connected. IP: %s RSSI: %d dBm\n",
                          WiFi.localIP().toString().c_str(),
                          WiFi.RSSI());
            return true;
        }

        Serial.printf("[WiFi] Attempt %d failed (status %d)\n", attempt, status);
        WiFi.disconnect(true);
    }

    Serial.println("[WiFi] All retries exhausted");
    return false;
}

void disconnectWiFi() {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
}

int32_t getWiFiRSSI() {
    return WiFi.RSSI();
}
