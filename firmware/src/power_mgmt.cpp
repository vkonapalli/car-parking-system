#include "power_mgmt.h"
#include <esp_sleep.h>
#include <esp_timer.h>
#include <driver/adc.h>

static const uint64_t DEBOUNCE_US = 30ULL * 1000 * 1000;
static const gpio_num_t PIR_PIN = GPIO_NUM_1;
static const adc1_channel_t BATTERY_ADC_CHANNEL = ADC1_CHANNEL_1;

static const float ADC_MAX = 4095.0f;
static const float ADC_REF_V = 3.3f;
static const float VOLTAGE_DIVIDER_RATIO = 2.0f;

RTC_DATA_ATTR static int64_t rtcLastWakeUs = 0;

bool shouldDebounce() {
    if (rtcLastWakeUs == 0) {
        return false;
    }
    int64_t now = esp_timer_get_time();
    return (now - rtcLastWakeUs) < (int64_t)DEBOUNCE_US;
}

void recordWakeTime() {
    rtcLastWakeUs = esp_timer_get_time();
}

WakeCause getWakeCause() {
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    switch (cause) {
        case ESP_SLEEP_WAKEUP_EXT0:
            return WAKE_PIR;
        case ESP_SLEEP_WAKEUP_UNDEFINED:
            return WAKE_RESET;
        default:
            return WAKE_OTHER;
    }
}

void enterDeepSleep() {
    esp_sleep_enable_ext0_wakeup(PIR_PIN, 1);
    esp_deep_sleep_start();
}

float readBatteryVoltage() {
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(BATTERY_ADC_CHANNEL, ADC_ATTEN_DB_11);
    int raw = adc1_get_raw(BATTERY_ADC_CHANNEL);
    if (raw < 0) {
        return 0.0f;
    }
    return (raw / ADC_MAX) * ADC_REF_V * VOLTAGE_DIVIDER_RATIO;
}
