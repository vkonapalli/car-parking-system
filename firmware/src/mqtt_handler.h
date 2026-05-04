#pragma once

#include <stdint.h>

bool connectMQTT(const char* endpoint, const char* deviceId, const char* caCert,
                 const char* clientCert, const char* clientKey);

bool publishCapture(const char* lotId, const char* deviceId, const char* timestamp,
                    const char* s3Key);

bool updateShadow(const char* deviceId, const char* lastCapture, float batteryVoltage,
                  int32_t wifiRssi, const char* firmwareVersion);

void disconnectMQTT();
