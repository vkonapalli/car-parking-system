#include "ir_led.h"
#include <Arduino.h>

void initIR() {
    pinMode(IR_LED_PIN, OUTPUT);
    digitalWrite(IR_LED_PIN, LOW);
}

void enableIR() {
    digitalWrite(IR_LED_PIN, HIGH);
    delay(100);
}

void disableIR() {
    digitalWrite(IR_LED_PIN, LOW);
}
