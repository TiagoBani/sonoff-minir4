idf_component_register(SRCS "main.c" "store.c" "store_policy.c" "lifecycle.c"
    "../../minir4-readout/main/stock_wifi.c"
    INCLUDE_DIRS "." "../../minir4-readout/main"
    REQUIRES esp_hap_core esp_hap_apple_profiles esp_hap_platform esp_http_server
             esp_wifi app_update esp_partition nvs_flash esp_event esp_netif driver)
