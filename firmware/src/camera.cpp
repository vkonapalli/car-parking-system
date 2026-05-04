#include "camera.h"
#include <Arduino.h>

#define CAM_PIN_PWDN    -1
#define CAM_PIN_RESET   -1
#define CAM_PIN_XCLK    15
#define CAM_PIN_SIOD    4
#define CAM_PIN_SIOC    5
#define CAM_PIN_D7      16
#define CAM_PIN_D6      17
#define CAM_PIN_D5      18
#define CAM_PIN_D4      12
#define CAM_PIN_D3      10
#define CAM_PIN_D2      8
#define CAM_PIN_D1      9
#define CAM_PIN_D0      11
#define CAM_PIN_VSYNC   6
#define CAM_PIN_HREF    7
#define CAM_PIN_PCLK    13

bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = CAM_PIN_D0;
    config.pin_d1       = CAM_PIN_D1;
    config.pin_d2       = CAM_PIN_D2;
    config.pin_d3       = CAM_PIN_D3;
    config.pin_d4       = CAM_PIN_D4;
    config.pin_d5       = CAM_PIN_D5;
    config.pin_d6       = CAM_PIN_D6;
    config.pin_d7       = CAM_PIN_D7;
    config.pin_xclk     = CAM_PIN_XCLK;
    config.pin_pclk     = CAM_PIN_PCLK;
    config.pin_vsync    = CAM_PIN_VSYNC;
    config.pin_href     = CAM_PIN_HREF;
    config.pin_sccb_sda = CAM_PIN_SIOD;
    config.pin_sccb_scl = CAM_PIN_SIOC;
    config.pin_pwdn     = CAM_PIN_PWDN;
    config.pin_reset    = CAM_PIN_RESET;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size   = FRAMESIZE_QSXGA;
    config.jpeg_quality = 10;
    config.fb_count     = 2;
    config.fb_location  = CAMERA_FB_IN_PSRAM;
    config.grab_mode    = CAMERA_GRAB_LATEST;

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed: 0x%x\n", err);
        return false;
    }

    sensor_t* s = esp_camera_sensor_get();
    if (s && s->id.PID == OV5640_PID) {
        s->set_vflip(s, 1);
    }

    return true;
}

// Variance of adjacent-byte differences in the JPEG bitstream is a valid
// sharpness proxy: more image detail → higher entropy → higher variance.
// Striding avoids iterating multi-megabyte QSXGA buffers exhaustively while
// preserving statistical accuracy.
static float sharpnessScore(const uint8_t* buf, size_t len) {
    if (len < 2) return 0.0f;

    constexpr size_t kStride = 64;
    float sum = 0.0f;
    float sumSq = 0.0f;
    size_t n = 0;

    for (size_t i = 0; i + 1 < len; i += kStride) {
        float diff = static_cast<float>(buf[i + 1]) - static_cast<float>(buf[i]);
        sum   += diff;
        sumSq += diff * diff;
        n++;
    }

    if (n == 0) return 0.0f;
    float mean = sum / static_cast<float>(n);
    return (sumSq / static_cast<float>(n)) - (mean * mean);
}

camera_fb_t* captureBestFrame(int burstCount) {
    camera_fb_t* frames[burstCount];
    float scores[burstCount];

    for (int i = 0; i < burstCount; i++) {
        frames[i] = esp_camera_fb_get();
        if (!frames[i]) {
            for (int j = 0; j < i; j++) {
                esp_camera_fb_return(frames[j]);
            }
            return nullptr;
        }
        scores[i] = sharpnessScore(frames[i]->buf, frames[i]->len);
    }

    int bestIdx = 0;
    for (int i = 1; i < burstCount; i++) {
        if (scores[i] > scores[bestIdx]) {
            bestIdx = i;
        }
    }

    for (int i = 0; i < burstCount; i++) {
        if (i != bestIdx) {
            esp_camera_fb_return(frames[i]);
        }
    }

    return frames[bestIdx];
}

void deinitCamera() {
    esp_camera_deinit();
}
