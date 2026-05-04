#pragma once

bool connectWiFi(const char* ssid, const char* password, int maxRetries = 3);
void disconnectWiFi();
int32_t getWiFiRSSI();
