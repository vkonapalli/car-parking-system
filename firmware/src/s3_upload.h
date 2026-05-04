#pragma once

#include <Arduino.h>
#include <WiFiClientSecure.h>

struct AwsCredentials {
    String accessKeyId;
    String secretAccessKey;
    String sessionToken;
};

AwsCredentials getIotCredentials(
    const char* credentialProviderEndpoint,
    const char* roleAlias,
    const char* caCert,
    const char* clientCert,
    const char* clientKey
);

bool uploadToS3(
    const AwsCredentials& creds,
    const char* bucket,
    const char* region,
    const char* s3Key,
    const uint8_t* imageData,
    size_t imageLen,
    const char* caCert,
    const char* clientCert,
    const char* clientKey
);

String generateS3Key(const char* lotId, const char* timestamp);
