#pragma once

enum WakeCause {
    WAKE_PIR,
    WAKE_RESET,
    WAKE_OTHER,
};

bool shouldDebounce();
void recordWakeTime();
WakeCause getWakeCause();
void enterDeepSleep();
float readBatteryVoltage();
