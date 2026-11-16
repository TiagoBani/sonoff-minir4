/* GPL-3.0-or-later: Wi-Fi flow shared with minir4-readout 0.1.2. */
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
    /* Wi-Fi starts only after HAP has registered its services. */
    if (sta_netif != NULL) {
        ESP_LOGI(TAG, "joining the home network; own network only if that fails");
        if (xTaskCreate(station_watch, "sta_watch", 2048, NULL, 5, NULL) != pdPASS) return ESP_FAIL;
    } else {
        ESP_LOGI(TAG, "AP ready: %s", config->ap.ssid);
    }
    return ESP_OK;
}

