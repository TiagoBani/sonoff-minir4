/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "hap.h"
#include "hap_apple_servs.h"
#include "hap_apple_chars.h"
#include "store.h"
#include "store_policy.h"
#include "lifecycle.h"
#include "stock_wifi.h"
#include "access.local.h"
#include "pairing.local.h"
#if !CONFIG_IDF_TARGET_ESP32 || CONFIG_ESP_WIFI_NVS_ENABLED || CONFIG_HAP_MFI_ENABLE
#error Unsupported target or enabled stock NVS/MFi writes
#endif

#if CONFIG_LWIP_MAX_SOCKETS < 16 || CONFIG_HAP_HTTP_MAX_OPEN_SOCKETS > 4
#error HomeKit and authenticated maintenance require 16 shared sockets and at most 4 HomeKit clients
#endif
