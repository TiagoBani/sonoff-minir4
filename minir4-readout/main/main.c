/* SPDX-License-Identifier: GPL-3.0-or-later
 * MINIR4 readout adaptation of adamsthws/firmware-liberator (77702d7).
 * Modified 2026-11-14: ESP32 target, readout only, authenticated endpoints,
 * ESP32 eFuse API, explicit Wi-Fi return to original firmware and idle return.
 * OTA installation overwrites the inactive app slot before any backup.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "esp_err.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_flash.h"
#include "esp_efuse.h"
#include "soc/efuse_reg.h"
#include "soc/soc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "mbedtls/sha256.h"
#include "access.local.h"
#include "stock_wifi.h"
#if !CONFIG_IDF_TARGET_ESP32
#error This application is for the classic ESP32 only
#endif
#define UPLOAD_BUFFER_SIZE 4096
#define BRIDGE_NAME_FORMAT "minir4-readout-%02X%02X"
#define HOME_RETRY_EVERY_MS 180000
#define HOME_RETRY_FOR_MS 20000
#define STA_WINDOW_MS 45000
#define BRIDGE_NAME "minir4 readout 0.1.2"
static const char *TAG = "minir4_readout";
static const esp_partition_t *s_running;
static const esp_partition_t *s_peer;
static volatile bool s_sta_trying;
static volatile uint32_t s_sta_ip;
static wifi_config_t s_ap_config;
static wifi_config_t s_sta_config;
static char s_upload_buffer[UPLOAD_BUFFER_SIZE];
static volatile TickType_t s_last_activity;
static TickType_t s_started;

static bool authorized(httpd_req_t *req)
{
    char token[65];
    if (httpd_req_get_hdr_value_len(req, "X-Access-Token") != 64 ||
        httpd_req_get_hdr_value_str(req, "X-Access-Token", token, sizeof(token)) != ESP_OK ||
        strcmp(token, READOUT_ACCESS_TOKEN) != 0) {
        httpd_resp_set_status(req, "403 Forbidden");
        httpd_resp_sendstr(req, "Access denied.\n");
        return false;
    }
    s_last_activity = xTaskGetTickCount();
    return true;
}

static void delayed_restart(void *unused)
{
    (void)unused;
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_restart();
}

static esp_err_t return_handler(httpd_req_t *req)
{
    if (!authorized(req)) return ESP_OK;
    const esp_partition_t *boot = esp_ota_get_boot_partition();
    if (!boot || boot->address != s_peer->address) {
        httpd_resp_set_status(req, "409 Conflict");
        return httpd_resp_sendstr(req, "Original application is not selected.\n");
    }
    if (xTaskCreate(delayed_restart, "return_stock", 2048, NULL, 5, NULL) != pdPASS) {
        httpd_resp_set_status(req, "500 Internal Server Error");
        return httpd_resp_sendstr(req, "Restart task unavailable.\n");
    }
    return httpd_resp_sendstr(req, "Restarting into the selected original application.\n");
}

static void idle_return(void *unused)
{
    (void)unused;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        TickType_t now = xTaskGetTickCount();
        if (now - s_last_activity > pdMS_TO_TICKS(600000) ||
            now - s_started > pdMS_TO_TICKS(1200000)) esp_restart();
    }
}

static esp_err_t flash_handler(httpd_req_t *req)
{
    if (!authorized(req)) return ESP_OK;
    uint32_t size = 0;
    if (esp_flash_get_size(NULL, &size) != ESP_OK || size == 0) {
        httpd_resp_set_status(req, "500 Internal Server Error");
        return httpd_resp_sendstr(req, "Could not read the flash size.\n");
    }
    char size_text[12];
    snprintf(size_text, sizeof(size_text), "%lu", (unsigned long)size);
    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Flash-Size", size_text);
    for (uint32_t offset = 0; offset < size; offset += sizeof(s_upload_buffer)) {
        s_last_activity = xTaskGetTickCount();
        uint32_t length = size - offset < sizeof(s_upload_buffer)
                              ? size - offset
                              : sizeof(s_upload_buffer);
        if (esp_flash_read(NULL, s_upload_buffer, offset, length) != ESP_OK ||
            httpd_resp_send_chunk(req, s_upload_buffer, length) != ESP_OK) {
            /* End without the final chunk so the host sees a broken transfer. */
            return ESP_FAIL;
        }
    }
    return httpd_resp_send_chunk(req, NULL, 0);
}

/* The SHA-256 of the whole flash chip, read here, in lower-case hex, so the
 * host can check what /flash sent it byte for byte.  Read-only. */
static esp_err_t flash_sha256_handler(httpd_req_t *req)
{
    if (!authorized(req)) return ESP_OK;
    uint32_t size = 0;
    if (esp_flash_get_size(NULL, &size) != ESP_OK || size == 0) {
        httpd_resp_set_status(req, "500 Internal Server Error");
        return httpd_resp_sendstr(req, "Could not read the flash size.\n");
    }
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts(&sha, 0);
    for (uint32_t offset = 0; offset < size; offset += sizeof(s_upload_buffer)) {
        s_last_activity = xTaskGetTickCount();
        uint32_t length = size - offset < sizeof(s_upload_buffer)
                              ? size - offset
                              : sizeof(s_upload_buffer);
        if (esp_flash_read(NULL, s_upload_buffer, offset, length) != ESP_OK) {
            mbedtls_sha256_free(&sha);
            httpd_resp_set_status(req, "500 Internal Server Error");
            return httpd_resp_sendstr(req, "Could not read the flash.\n");
        }
        mbedtls_sha256_update(&sha, (const unsigned char *)s_upload_buffer, length);
    }
    unsigned char digest[32];
    mbedtls_sha256_finish(&sha, digest);
    mbedtls_sha256_free(&sha);
    char text[2 * sizeof(digest) + 2];
    for (size_t i = 0; i < sizeof(digest); i++) {
        snprintf(text + 2 * i, 3, "%02x", digest[i]);
    }
    text[2 * sizeof(digest)] = '\n';
    text[2 * sizeof(digest) + 1] = 0;
    char size_text[12];
    snprintf(size_text, sizeof(size_text), "%lu", (unsigned long)size);
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "X-Flash-Size", size_text);
    return httpd_resp_sendstr(req, text);
}

/* Read only the ESP32 eFuse bits exposed by the hardware. Protected fields
 * may read as zero; this is not a backup of recoverable encryption keys. */
static esp_err_t efuse_handler(httpd_req_t *req)
{
    if (!authorized(req)) return ESP_OK;
    uint8_t data[124] = {0};
    size_t offset = 0;
    /* esp_efuse_read_block rejects BLK0. Read the target's documented read
     * registers instead, also avoiding assumptions about key coding schemes. */
    const uint32_t bases[] = {EFUSE_BLK0_RDATA0_REG, EFUSE_BLK1_RDATA0_REG,
                              EFUSE_BLK2_RDATA0_REG, EFUSE_BLK3_RDATA0_REG};
    for (size_t block = 0; block < 4; block++) {
        size_t words = block == 0 ? 7 : 8;
        for (size_t word = 0; word < words; word++) {
            uint32_t value = REG_READ(bases[block] + word * 4);
            memcpy(data + offset, &value, sizeof(value));
            offset += sizeof(value);
        }
    }
    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, (const char *)data, offset);
}

static esp_err_t status_handler(httpd_req_t *req)
{
    if (!authorized(req)) return ESP_OK;
    uint8_t mac[6];
    if (esp_read_mac(mac, ESP_MAC_WIFI_STA) != ESP_OK) return ESP_FAIL;
    char body[512];
    snprintf(body, sizeof(body), BRIDGE_NAME "\nmac: %02x:%02x:%02x:%02x:%02x:%02x\n"
        "running: %s offset=0x%lx size=0x%lx\n"
        "next boot: %s offset=0x%lx size=0x%lx\n"
        "partition table: existing device layout\n",
        mac[0], mac[1], mac[2], mac[3], mac[4], mac[5],
        s_running->label, (unsigned long)s_running->address, (unsigned long)s_running->size,
        s_peer->label, (unsigned long)s_peer->address, (unsigned long)s_peer->size);
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, body);
}

static bool read_stock_wifi(wifi_config_t *sta)
{
    esp_err_t err = nvs_flash_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "stock NVS not readable (%s)", esp_err_to_name(err));
        return false;
    }
    bool found = false;
    nvs_handle_t handle;
    if (nvs_open("pair", NVS_READONLY, &handle) == ESP_OK) {
        uint8_t blob[MINIR4_PAIR_INFO_SIZE] = {0};
        size_t length = sizeof(blob);
        if (nvs_get_blob(handle, "info", blob, &length) == ESP_OK) {
            found = minir4_decode_pair_wifi(blob, length, sta->sta.ssid, sta->sta.password);
        }
        memset(blob, 0, sizeof(blob));
        nvs_close(handle);
    }
    if (!found && nvs_open("nvs.net80211", NVS_READONLY, &handle) == ESP_OK) {
        struct {
            uint32_t len;
            uint8_t ssid[32];
        } ssid;
        char password[65];
        size_t ssid_size = sizeof(ssid), password_size = sizeof(password);
        if (nvs_get_blob(handle, "sta.ssid", &ssid, &ssid_size) == ESP_OK &&
            ssid_size == sizeof(ssid) && ssid.len > 0 && ssid.len <= 32 &&
            nvs_get_blob(handle, "sta.pswd", password, &password_size) == ESP_OK &&
            password_size <= sizeof(password)) {
            memcpy(sta->sta.ssid, ssid.ssid, ssid.len);
            password[sizeof(password) - 1] = 0;
            strlcpy((char *)sta->sta.password, password, sizeof(sta->sta.password));
            found = true;
        }
        memset(password, 0, sizeof(password));
        nvs_close(handle);
    }
    nvs_flash_deinit();
    return found;
}

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START && s_sta_trying) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_sta_ip = 0;
        if (s_sta_trying) {
            esp_wifi_connect();
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_sta_ip = ((ip_event_got_ip_t *)data)->ip_info.ip.addr;
        ESP_LOGI(TAG, "joined the home network: " IPSTR,
                 IP2STR(&((ip_event_got_ip_t *)data)->ip_info.ip));
    }
}

/* Raise the bridge's own network once the home network has given the bridge
 * no address for STA_WINDOW_MS - at start-up, or after losing it - so there
 * is always a way in.  On its own network, it tries the home network again
 * every HOME_RETRY_EVERY_MS while nobody is joined to it - a router back
 * after a restart is found again, and the run goes on there - and goes back
 * to its own if that fails.  Never both at once: on one radio, the joined
 * network dropped out while the bridge's own was up (v5). */
/* Each change of network is a restart of Wi-Fi, as at start-up: stopped, set,
 * started again, rather than the mode changed while it runs. */
static void own_network(void)
{
    s_sta_trying = false;
    esp_wifi_disconnect();
    esp_wifi_stop();
    esp_wifi_set_mode(WIFI_MODE_AP);
    esp_wifi_set_config(WIFI_IF_AP, &s_ap_config);
    esp_wifi_start();
    ESP_LOGI(TAG, "AP ready: %s", s_ap_config.ap.ssid);
}

static void home_network(void)
{
    esp_wifi_stop();
    s_sta_trying = true;  /* STA_START, as Wi-Fi starts, connects (on_wifi_event) */
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &s_sta_config);
    esp_wifi_start();
}

static void station_watch(void *unused)
{
    (void)unused;
    for (;;) {
        TickType_t without = 0;
        while (without < pdMS_TO_TICKS(STA_WINDOW_MS)) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            without = s_sta_ip != 0 ? 0 : without + pdMS_TO_TICKS(1000);
        }
        ESP_LOGW(TAG, "no address on the home network; raising the bridge's own");
        own_network();
        for (;;) {
            vTaskDelay(pdMS_TO_TICKS(HOME_RETRY_EVERY_MS));
            wifi_sta_list_t joined = {0};
            if (esp_wifi_ap_get_sta_list(&joined) == ESP_OK && joined.num > 0) {
                continue;  /* someone is using the bridge's own network */
            }
            ESP_LOGI(TAG, "nobody on the bridge's own network; trying the home network again");
            home_network();
            TickType_t waited = 0;
            while (s_sta_ip == 0 && waited < pdMS_TO_TICKS(HOME_RETRY_FOR_MS)) {
                vTaskDelay(pdMS_TO_TICKS(500));
                waited += pdMS_TO_TICKS(500);
            }
            if (s_sta_ip != 0) {
                ESP_LOGI(TAG, "back on the home network; the bridge's own is down");
                break;  /* watch it again, as at start-up */
            }
            ESP_LOGW(TAG, "still no home network; the bridge's own again");
            own_network();
        }
    }
}

static esp_err_t start_access_point(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    if (esp_netif_create_default_wifi_ap() == NULL) {
        return ESP_FAIL;
    }

    /* The fallback AP uses the private password created for this build. */
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    char name[32];
    snprintf(name, sizeof(name), BRIDGE_NAME_FORMAT, mac[4], mac[5]);

    wifi_config_t station = {0};
    bool have_station = read_stock_wifi(&station);
    esp_netif_t *sta_netif = have_station ? esp_netif_create_default_wifi_sta() : NULL;
    if (sta_netif != NULL) {
        esp_netif_set_hostname(sta_netif, name);
    }

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, NULL));

    wifi_config_t *config = &s_ap_config;
    snprintf((char *)config->ap.ssid, sizeof(config->ap.ssid), "%s", name);
    config->ap.ssid_len = strlen((char *)config->ap.ssid);
    config->ap.channel = 1;
    config->ap.max_connection = 2;
    config->ap.authmode = WIFI_AUTH_WPA2_PSK;
    strlcpy((char *)config->ap.password, READOUT_AP_PASSWORD, sizeof(config->ap.password));

    if (sta_netif != NULL) {
        station.sta.pmf_cfg.capable = true;
        station.sta.pmf_cfg.required = false;
        s_sta_trying = true;
        s_sta_config = station;
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &station));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, config));
    }
    memset(&station, 0, sizeof(station));
    ESP_ERROR_CHECK(esp_wifi_start());
    if (sta_netif != NULL) {
        ESP_LOGI(TAG, "joining the home network; own network only if that fails");
        if (xTaskCreate(station_watch, "sta_watch", 2048, NULL, 5, NULL) != pdPASS) return ESP_FAIL;
    } else {
        ESP_LOGI(TAG, "AP ready: %s", config->ap.ssid);
    }
    return ESP_OK;
}

static esp_err_t start_web_server(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 8192;
    config.recv_wait_timeout = 20;
    config.send_wait_timeout = 20;
    httpd_handle_t server = NULL;
    esp_err_t err = httpd_start(&server, &config);
    if (err != ESP_OK) return err;
    const httpd_uri_t routes[] = {
        {.uri="/status", .method=HTTP_GET, .handler=status_handler},
        {.uri="/flash", .method=HTTP_GET, .handler=flash_handler},
        {.uri="/flash-sha256", .method=HTTP_GET, .handler=flash_sha256_handler},
        {.uri="/efuse", .method=HTTP_GET, .handler=efuse_handler},
        {.uri="/return", .method=HTTP_POST, .handler=return_handler},
    };
    for (size_t i=0; i < sizeof(routes)/sizeof(routes[0]); i++) {
        err = httpd_register_uri_handler(server, &routes[i]);
        if (err != ESP_OK) return err;
    }
    return ESP_OK;
}

void app_main(void)
{
    s_last_activity = xTaskGetTickCount();
    s_started = s_last_activity;
    s_running = esp_ota_get_running_partition();
    s_peer = esp_ota_get_next_update_partition(NULL);
    if (!s_running || !s_peer || s_running == s_peer) {
        ESP_LOGE(TAG, "No distinct OTA peer; cannot establish return path");
        return;
    }
    /* This build is specific to the stock image already verified in the dump.
     * Do not mistake another auxiliary/alternative app for a return to Sonoff. */
    static const uint8_t expected_stock_hash[32] = {
        0x3f,0xbb,0x2a,0x56,0x07,0xaa,0x18,0xda,0xc0,0xe1,0x79,0xfa,0x3d,0xc1,0xf5,0x27,
        0x72,0xb5,0xa7,0xb1,0x6f,0x9e,0x80,0x9b,0x5e,0x03,0xde,0x74,0x73,0x7a,0xd5,0x4e};
    uint8_t peer_hash[32];
    if (esp_partition_get_sha256(s_peer, peer_hash) != ESP_OK ||
        memcmp(peer_hash, expected_stock_hash, sizeof(peer_hash)) != 0) {
        ESP_LOGE(TAG, "Peer does not match the verified original Sonoff image");
        return;
    }
    esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
    if (err != ESP_OK) ESP_LOGW(TAG, "Confirmation: %s", esp_err_to_name(err));
    err = esp_ota_set_boot_partition(s_peer);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Cannot select original application: %s", esp_err_to_name(err));
        return;
    }
    if (xTaskCreate(idle_return, "idle_return", 2048, NULL, 5, NULL) != pdPASS) {
        esp_restart();
        return;
    }
    if (start_access_point() != ESP_OK || start_web_server() != ESP_OK) esp_restart();
}
