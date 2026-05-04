#pragma once

#include "esp_camera.h"

bool initCamera();
camera_fb_t* captureBestFrame(int burstCount = 3);
void deinitCamera();
