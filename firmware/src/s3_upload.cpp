#include "s3_upload.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>

static void bytesToHex(const uint8_t* bytes, size_t len, char* out) {
    for (size_t i = 0; i < len; i++) {
        sprintf(out + i * 2, "%02x", bytes[i]);
    }
    out[len * 2] = '\0';
}

static void sha256Hex(const uint8_t* data, size_t len, char out[65]) {
    uint8_t hash[32];
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    mbedtls_sha256_starts(&ctx, 0);
    mbedtls_sha256_update(&ctx, data, len);
    mbedtls_sha256_finish(&ctx, hash);
    mbedtls_sha256_free(&ctx);
    bytesToHex(hash, 32, out);
}

static void hmacSha256(
    const uint8_t* key, size_t keyLen,
    const uint8_t* msg, size_t msgLen,
    uint8_t out[32]
) {
    mbedtls_md_context_t ctx;
    const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    mbedtls_md_init(&ctx);
    mbedtls_md_setup(&ctx, info, 1);
    mbedtls_md_hmac_starts(&ctx, key, keyLen);
    mbedtls_md_hmac_update(&ctx, msg, msgLen);
    mbedtls_md_hmac_finish(&ctx, out);
    mbedtls_md_free(&ctx);
}

static void hmacSha256Hex(
    const uint8_t* key, size_t keyLen,
    const String& msg,
    char out[65]
) {
    uint8_t hash[32];
    hmacSha256(key, keyLen, (const uint8_t*)msg.c_str(), msg.length(), hash);
    bytesToHex(hash, 32, out);
}

static String sigV4AuthHeader(
    const AwsCredentials& creds,
    const char* region,
    const char* method,
    const char* host,
    const char* path,
    const String& amzDate,
    const String& amzDateShort,
    const char* payloadHash
) {
    String canonicalHeaders =
        String("content-type:image/jpeg\n") +
        "host:" + host + "\n" +
        "x-amz-content-sha256:" + payloadHash + "\n" +
        "x-amz-date:" + amzDate + "\n" +
        "x-amz-security-token:" + creds.sessionToken + "\n";

    String signedHeaders = "content-type;host;x-amz-content-sha256;x-amz-date;x-amz-security-token";

    String canonicalRequest =
        String(method) + "\n" +
        "/" + path + "\n" +
        "\n" +
        canonicalHeaders + "\n" +
        signedHeaders + "\n" +
        payloadHash;

    char canonicalHash[65];
    sha256Hex(
        (const uint8_t*)canonicalRequest.c_str(),
        canonicalRequest.length(),
        canonicalHash
    );

    String credentialScope = amzDateShort + "/" + region + "/s3/aws4_request";

    String stringToSign =
        String("AWS4-HMAC-SHA256\n") +
        amzDate + "\n" +
        credentialScope + "\n" +
        canonicalHash;

    String awsKey = String("AWS4") + creds.secretAccessKey;
    uint8_t kDate[32], kRegion[32], kService[32], kSigning[32];
    hmacSha256(
        (const uint8_t*)awsKey.c_str(), awsKey.length(),
        (const uint8_t*)amzDateShort.c_str(), amzDateShort.length(),
        kDate
    );
    hmacSha256(kDate, 32, (const uint8_t*)region, strlen(region), kRegion);
    hmacSha256(kRegion, 32, (const uint8_t*)"s3", 2, kService);
    hmacSha256(kService, 32, (const uint8_t*)"aws4_request", 12, kSigning);

    char sigHex[65];
    hmacSha256Hex(kSigning, 32, stringToSign, sigHex);

    return String("AWS4-HMAC-SHA256 Credential=") +
           creds.accessKeyId + "/" + credentialScope +
           ", SignedHeaders=" + signedHeaders +
           ", Signature=" + sigHex;
}

static void isoToAmzDates(const char* ts, String& dateShort, String& amzDate) {
    char buf[9];
    buf[0] = ts[0]; buf[1] = ts[1]; buf[2] = ts[2]; buf[3] = ts[3];
    buf[4] = ts[5]; buf[5] = ts[6];
    buf[6] = ts[8]; buf[7] = ts[9];
    buf[8] = '\0';
    dateShort = String(buf);

    amzDate = dateShort + "T";
    amzDate += ts[11]; amzDate += ts[12];
    amzDate += ts[14]; amzDate += ts[15];
    amzDate += ts[17]; amzDate += ts[18];
    amzDate += "Z";
}

AwsCredentials getIotCredentials(
    const char* credentialProviderEndpoint,
    const char* roleAlias,
    const char* caCert,
    const char* clientCert,
    const char* clientKey
) {
    AwsCredentials creds;

    WiFiClientSecure tlsClient;
    tlsClient.setCACert(caCert);
    tlsClient.setCertificate(clientCert);
    tlsClient.setPrivateKey(clientKey);

    HTTPClient http;
    String url = String("https://") + credentialProviderEndpoint +
                 "/role-aliases/" + roleAlias + "/credentials";
    http.begin(tlsClient, url);

    int status = http.GET();
    if (status != 200) {
        Serial.printf("[s3_upload] credential provider HTTP %d\n", status);
        http.end();
        return creds;
    }

    String body = http.getString();
    http.end();

    JsonDocument doc;
    if (deserializeJson(doc, body) != DeserializationError::Ok) {
        Serial.println("[s3_upload] failed to parse credentials JSON");
        return creds;
    }

    creds.accessKeyId     = doc["credentials"]["accessKeyId"].as<String>();
    creds.secretAccessKey = doc["credentials"]["secretAccessKey"].as<String>();
    creds.sessionToken    = doc["credentials"]["sessionToken"].as<String>();

    return creds;
}

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
) {
    time_t now = time(nullptr);
    struct tm t;
    gmtime_r(&now, &t);
    char isoTs[21];
    strftime(isoTs, sizeof(isoTs), "%Y-%m-%dT%H:%M:%SZ", &t);

    String amzDateShort, amzDate;
    isoToAmzDates(isoTs, amzDateShort, amzDate);

    char payloadHash[65];
    sha256Hex(imageData, imageLen, payloadHash);

    String host = String(bucket) + ".s3." + region + ".amazonaws.com";

    String authHeader = sigV4AuthHeader(
        creds, region,
        "PUT", host.c_str(), s3Key,
        amzDate, amzDateShort,
        payloadHash
    );

    WiFiClientSecure tlsClient;
    tlsClient.setCACert(caCert);
    tlsClient.setCertificate(clientCert);
    tlsClient.setPrivateKey(clientKey);

    HTTPClient http;
    String url = String("https://") + host + "/" + s3Key;
    http.begin(tlsClient, url);

    http.addHeader("Content-Type", "image/jpeg");
    http.addHeader("x-amz-date", amzDate);
    http.addHeader("x-amz-content-sha256", payloadHash);
    http.addHeader("x-amz-security-token", creds.sessionToken);
    http.addHeader("Authorization", authHeader);

    int status = http.PUT(const_cast<uint8_t*>(imageData), imageLen);
    http.end();

    if (status != 200) {
        Serial.printf("[s3_upload] S3 PUT HTTP %d\n", status);
        return false;
    }
    return true;
}

String generateS3Key(const char* lotId, const char* timestamp) {
    if (strlen(timestamp) < 19) {
        return String("captures/") + lotId + "/unknown/unknown.jpg";
    }

    char date[11];
    strncpy(date, timestamp, 10);
    date[10] = '\0';

    char timePart[9];
    timePart[0] = timestamp[11]; timePart[1] = timestamp[12];
    timePart[2] = '-';
    timePart[3] = timestamp[14]; timePart[4] = timestamp[15];
    timePart[5] = '-';
    timePart[6] = timestamp[17]; timePart[7] = timestamp[18];
    timePart[8] = '\0';

    return String("captures/") + lotId + "/" + date + "/" + timePart + ".jpg";
}
