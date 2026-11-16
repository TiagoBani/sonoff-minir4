/* SPDX-License-Identifier: GPL-3.0-or-later
 * Experimental application image; never replaces the partition table or bootloader.
 */
#include "app.h"
#define APP_ID "minir4 homekit 0.2.2"
#define BRIDGE_NAME_FORMAT "minir4-homekit-%02X%02X"
#define STA_WINDOW_MS 45000
#define HOME_RETRY_EVERY_MS 180000
#define HOME_RETRY_FOR_MS 20000
static const char *TAG="minir4_homekit";
static const esp_partition_t *s_running,*s_stock;
static uint8_t s_image_hash[32];
static volatile bool s_committed,s_light,s_seen_on,s_seen_off,s_returning;
static volatile bool s_sta_trying;
static volatile uint32_t s_sta_ip;
static wifi_config_t s_ap_config,s_sta_config;
static TickType_t s_started;
static SemaphoreHandle_t s_light_lock,s_boot_lock;
static hap_char_t *s_on;
static volatile bool s_hap_initialized,s_homekit_ready,s_startup_failed;
static const char *s_stage="storage";
static uint8_t s_previous_stage;
static void stage(const char *name,uint8_t code)
{
    s_stage=name;
    if(!hk_boot_stage_write(code))s_startup_failed=true;
}

static bool stock_valid(void)
{
    static const uint8_t expected[32]={
        0x3f,0xbb,0x2a,0x56,0x07,0xaa,0x18,0xda,0xc0,0xe1,0x79,0xfa,0x3d,0xc1,0xf5,0x27,
        0x72,0xb5,0xa7,0xb1,0x6f,0x9e,0x80,0x9b,0x5e,0x03,0xde,0x74,0x73,0x7a,0xd5,0x4e};
    uint8_t actual[32];
    return s_stock && s_stock->address==0x210000 && s_stock->size==0x1f0000 &&
        esp_partition_get_sha256(s_stock,actual)==ESP_OK && !memcmp(actual,expected,32);
}
static bool choose_stock(void)
{
    return stock_valid() && esp_ota_set_boot_partition(s_stock)==ESP_OK &&
           esp_ota_get_boot_partition() && esp_ota_get_boot_partition()->address==s_stock->address;
}
static void return_stock(bool due_only)
{
    if(s_boot_lock && xSemaphoreTake(s_boot_lock,portMAX_DELAY)!=pdTRUE)return;
    uint32_t elapsed=(uint32_t)(xTaskGetTickCount()-s_started)*portTICK_PERIOD_MS;
    if(due_only && !hk_trial_expired(s_committed,elapsed) && !hk_storage_failed()){
        xSemaphoreGive(s_boot_lock);return;
    }
    s_returning=true;
    /* Failed storage must not block the selection of the intact original. */
    hk_clear_commit();
    if(choose_stock())esp_restart();
    ESP_LOGE(TAG,"Cannot select verified original; refusing another boot target");
    if(s_boot_lock)xSemaphoreGive(s_boot_lock);
}
static void guard_task(void *unused)
{
    (void)unused;
    for(;;){
        vTaskDelay(pdMS_TO_TICKS(1000));
        return_stock(true);
    }
}
static esp_err_t set_light(bool on,bool from_homekit)
{
    if(xSemaphoreTake(s_light_lock,pdMS_TO_TICKS(1000))!=pdTRUE)return ESP_FAIL;
    esp_err_t err=gpio_set_level(GPIO_NUM_26,on);
    if(err==ESP_OK){
        s_light=on;gpio_set_level(GPIO_NUM_19,!on);
        if(from_homekit){if(on)s_seen_on=true;else s_seen_off=true;}
        if(s_on){hap_val_t val={.b=on};hap_char_update_val(s_on,&val);}
    }
    xSemaphoreGive(s_light_lock);return err;
}
static int light_write(hap_write_data_t data[],int count,void *service,void *priv)
{
    (void)service;(void)priv;int result=HAP_SUCCESS;
    for(int i=0;i<count;i++){
        *data[i].status=HAP_STATUS_RES_ABSENT;
        if(!strcmp(hap_char_get_type_uuid(data[i].hc),HAP_CHAR_UUID_ON))
            *data[i].status=set_light(data[i].val.b,true)==ESP_OK ? HAP_STATUS_SUCCESS : HAP_STATUS_RES_BUSY;
        if(*data[i].status!=HAP_STATUS_SUCCESS)result=HAP_FAIL;
    }
    return result;
}
static int identify(hap_acc_t *acc){(void)acc;return HAP_SUCCESS;}
static void buttons_task(void *unused)
{
    (void)unused;
    int stable[2]={gpio_get_level(GPIO_NUM_0),gpio_get_level(GPIO_NUM_27)};
    int last[2]={stable[0],stable[1]},ticks[2]={0,0};
    const gpio_num_t pins[2]={GPIO_NUM_0,GPIO_NUM_27};
    for(;;){
        vTaskDelay(pdMS_TO_TICKS(10));
        for(int i=0;i<2;i++){
            int level=gpio_get_level(pins[i]);
            if(level!=last[i]){last[i]=level;ticks[i]=0;}else if(ticks[i]<5)ticks[i]++;
            if(ticks[i]==5 && level!=stable[i]){
                stable[i]=level;if(i==1 || level==0)set_light(!s_light,false);
            }
        }
    }
}
#include "wifi.inc"

static bool authorized(httpd_req_t *req)
{
    char token[65];
    if(httpd_req_get_hdr_value_len(req,"X-Access-Token")!=64 ||
       httpd_req_get_hdr_value_str(req,"X-Access-Token",token,sizeof(token))!=ESP_OK ||
       strcmp(token,READOUT_ACCESS_TOKEN)){
        httpd_resp_set_status(req,"403 Forbidden");httpd_resp_sendstr(req,"Denied\n");return false;
    }
    return true;
}
static esp_err_t status_handler(httpd_req_t *req)
{
    if(!authorized(req))return ESP_OK;
    uint8_t mac[6];if(esp_read_mac(mac,ESP_MAC_WIFI_STA)!=ESP_OK)return ESP_FAIL;
    char body[896];
    snprintf(body,sizeof(body),"{\"app\":\"" APP_ID "\",\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\","
        "\"mode\":\"%s\",\"relay\":%s,\"paired_controllers\":%d,\"homekit_on_seen\":%s,"
        "\"homekit_off_seen\":%s,\"storage_failed\":%s,\"heap_free\":%lu,\"heap_minimum\":%lu,\"homekit_ready\":%s,\"startup_failed\":%s,\"stage\":\"%s\",\"previous_stage\":%u}",
        mac[0],mac[1],mac[2],mac[3],mac[4],mac[5],s_committed?"committed":"trial",s_light?"true":"false",
        (s_hap_initialized?hap_get_paired_controller_count():0),s_seen_on?"true":"false",s_seen_off?"true":"false",
        hk_storage_failed()?"true":"false",(unsigned long)esp_get_free_heap_size(),
        (unsigned long)esp_get_minimum_free_heap_size(),s_homekit_ready?"true":"false",
        s_startup_failed?"true":"false",s_stage,s_previous_stage);
    httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_sendstr(req,body);
}
static void delayed_return(void *unused)
{(void)unused;vTaskDelay(pdMS_TO_TICKS(1500));return_stock(false);vTaskDelete(NULL);}
static esp_err_t return_handler(httpd_req_t *req)
{
    if(!authorized(req))return ESP_OK;
    if(s_returning || !stock_valid()){
        httpd_resp_set_status(req,"409 Conflict");return httpd_resp_sendstr(req,"Return unavailable\n");
    }
    s_returning=true;
    if(xTaskCreate(delayed_return,"return_stock",4096,NULL,5,NULL)!=pdPASS){
        s_returning=false;httpd_resp_set_status(req,"500 Internal Server Error");
        return httpd_resp_sendstr(req,"Cannot schedule return\n");
    }
    return httpd_resp_sendstr(req,"Return scheduled; confirm original online\n");
}
static esp_err_t commit_handler(httpd_req_t *req)
{
    if(!authorized(req))return ESP_OK;
    if(xSemaphoreTake(s_boot_lock,pdMS_TO_TICKS(3000))!=pdTRUE)return ESP_FAIL;
    uint32_t elapsed=(uint32_t)(xTaskGetTickCount()-s_started)*portTICK_PERIOD_MS;
    if(!s_homekit_ready || s_startup_failed || s_returning || hk_trial_expired(s_committed,elapsed) || !hk_can_commit(hap_get_paired_controller_count()>0,s_seen_on,s_seen_off,hk_storage_failed()) || !stock_valid()){
        xSemaphoreGive(s_boot_lock);
        httpd_resp_set_status(req,"409 Conflict");return httpd_resp_sendstr(req,"Pair and test on/off in Home first\n");
    }
    if(!hk_set_commit(s_image_hash) || esp_ota_set_boot_partition(s_running)!=ESP_OK ||
       !esp_ota_get_boot_partition() || esp_ota_get_boot_partition()->address!=s_running->address){
        hk_clear_commit();choose_stock();xSemaphoreGive(s_boot_lock);httpd_resp_set_status(req,"500 Internal Server Error");
        return httpd_resp_sendstr(req,"Commit not confirmed\n");
    }
    s_committed=true;xSemaphoreGive(s_boot_lock);return httpd_resp_sendstr(req,"HomeKit selected for subsequent boots\n");
}
static esp_err_t maintenance_start(void)
{
    httpd_config_t config=HTTPD_DEFAULT_CONFIG();config.max_open_sockets=2;config.server_port=8080;config.ctrl_port=32769;config.stack_size=8192;
    httpd_handle_t server=NULL;esp_err_t err=httpd_start(&server,&config);if(err!=ESP_OK)return err;
    const httpd_uri_t routes[]={
        {.uri="/status",.method=HTTP_GET,.handler=status_handler},
        {.uri="/return",.method=HTTP_POST,.handler=return_handler},
        {.uri="/commit",.method=HTTP_POST,.handler=commit_handler}};
    for(size_t i=0;i<sizeof(routes)/sizeof(routes[0]);i++){
        err=httpd_register_uri_handler(server,&routes[i]);if(err!=ESP_OK)return err;
    }
    return ESP_OK;
}
static esp_err_t homekit_start(void)
{
    stage("hap_init",4);
    if(hap_init(HAP_TRANSPORT_WIFI)!=HAP_SUCCESS)return ESP_FAIL;
    s_hap_initialized=true;
    stage("setup_info",5);
    if(hap_set_setup_info(&HK_SETUP_INFO)!=HAP_SUCCESS || hap_set_setup_id(HK_SETUP_ID)!=HAP_SUCCESS)return ESP_FAIL;
    stage("accessory",6);
    hap_acc_cfg_t cfg={.name="Luz Escritorio",.manufacturer="Projeto pessoal",.model="MINIR4 HomeKit",
        .serial_num="MINIR4-Office",.fw_rev="0.2.2",.hw_rev="MINIR4",.pv="1.1.0",.identify_routine=identify,.cid=HAP_CID_LIGHTING};
    hap_acc_t *acc=hap_acc_create(&cfg);if(!acc)return ESP_ERR_NO_MEM;
    hap_serv_t *light=hap_serv_lightbulb_create(false);if(!light)return ESP_ERR_NO_MEM;
    s_on=hap_serv_get_char_by_uuid(light,HAP_CHAR_UUID_ON);if(!s_on)return ESP_FAIL;
    hap_serv_set_write_cb(light,light_write);
    if(hap_acc_add_serv(acc,light)!=HAP_SUCCESS)return ESP_FAIL;
    hap_add_accessory(acc);
    stage("hap_start",7);
    return hap_start()==HAP_SUCCESS && !hk_storage_failed() ? ESP_OK : ESP_FAIL;
}
void app_main(void)
{
    s_started=xTaskGetTickCount();s_running=esp_ota_get_running_partition();
    s_stock=esp_partition_find_first(ESP_PARTITION_TYPE_APP,ESP_PARTITION_SUBTYPE_APP_OTA_1,NULL);
    if(!s_running || s_running->address!=0x20000 || s_running->size!=0x1f0000 ||
       esp_partition_get_sha256(s_running,s_image_hash)!=ESP_OK || !choose_stock())return;
    esp_ota_mark_app_valid_cancel_rollback();
    s_boot_lock=xSemaphoreCreateMutex();
    if(!s_boot_lock || xTaskCreate(guard_task,"trial_guard",4096,NULL,5,NULL)!=pdPASS){return_stock(false);return;}
    if(!hk_storage_init()){return_stock(false);return;}
    s_previous_stage=hk_boot_stage_read();
    stage("gpio",1);
    s_light_lock=xSemaphoreCreateMutex();if(!s_light_lock){return_stock(false);return;}
    gpio_config_t output={.pin_bit_mask=(1ULL<<26)|(1ULL<<19),.mode=GPIO_MODE_OUTPUT};
    gpio_config_t input={.pin_bit_mask=(1ULL<<0)|(1ULL<<27),.mode=GPIO_MODE_INPUT,.pull_up_en=GPIO_PULLUP_ENABLE};
    if(gpio_config(&output)!=ESP_OK || gpio_config(&input)!=ESP_OK || set_light(false,false)!=ESP_OK){return_stock(false);return;}
    stage("wifi_init",2);
    if(start_access_point()!=ESP_OK || maintenance_start()!=ESP_OK || esp_wifi_start()!=ESP_OK){return_stock(false);return;}
    stage("wifi_connect",3);
    for(int i=0;i<120 && !s_sta_ip;i++)vTaskDelay(pdMS_TO_TICKS(500));
    if(!s_sta_ip || homekit_start()!=ESP_OK || xTaskCreate(buttons_task,"buttons",3072,NULL,4,NULL)!=pdPASS){
        s_startup_failed=true;
        /* Keep authenticated diagnostics available briefly; original remains next boot. */
        vTaskDelay(pdMS_TO_TICKS(45000));return_stock(false);return;
    }
    stage("ready",8);s_homekit_ready=!s_startup_failed && !hk_storage_failed();
    /* Keep Sonoff selected through all initialization. */
    if(hk_committed(s_image_hash) && s_homekit_ready){
        if(xSemaphoreTake(s_boot_lock,portMAX_DELAY)!=pdTRUE){return_stock(false);return;}
        bool ok=!s_returning && !hk_storage_failed() && esp_ota_set_boot_partition(s_running)==ESP_OK &&
            esp_ota_get_boot_partition() && esp_ota_get_boot_partition()->address==s_running->address;
        if(ok)s_committed=true;
        xSemaphoreGive(s_boot_lock);
        if(!ok){return_stock(false);return;}
    }
}
