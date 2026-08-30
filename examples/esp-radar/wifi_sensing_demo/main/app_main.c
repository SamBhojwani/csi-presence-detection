/*
 * SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdio.h>
#include <inttypes.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nvs_flash.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_wifi.h"
#include "esp_now.h"
#include "esp_netif.h"
#include "esp_event.h"

#include "esp_wifi_sensing.h"

#include "led_control.h"
#include "web_serial_monitor.h"

static const char *TAG = "wifi_sensing_demo";

static esp_wifi_sensing_fsm_handle_t s_hms = NULL;

/*
 * MAC address of the CSI transmitter connected on COM7.
 *
 * The transmitter is sending packets using this MAC:
 *
 * 1a:00:00:00:00:00
 */
static const uint8_t CONFIG_CSI_SEND_MAC[] = {
    0x1a, 0x00, 0x00, 0x00, 0x00, 0x00
};

/*
 * Both ESP32 boards operate on the same Wi-Fi channel.
 */
#define CSI_CHANNEL 11


/* ============================================================
 * Wi-Fi event handler
 * ============================================================ */

static void wifi_event_handler(void *arg,
                               esp_event_base_t event_base,
                               int32_t event_id,
                               void *event_data)
{
    (void)arg;
    (void)event_data;

    if (event_base == WIFI_EVENT) {

        if (event_id == WIFI_EVENT_STA_CONNECTED) {
            led_set_wifi_connected(true);
        }

        else if (event_id == WIFI_EVENT_STA_DISCONNECTED) {
            led_set_wifi_connected(false);
        }
    }
}


/* ============================================================
 * ESP-NOW receive callback
 *
 * This lets us verify that packets from the COM7 transmitter
 * are actually reaching the ESP32-S3.
 * ============================================================ */

static void espnow_recv_cb(const esp_now_recv_info_t *recv_info,
                           const uint8_t *data,
                           int data_len)
{
    if (!recv_info || !data || data_len <= 0) {
        return;
    }

    /*
     * Only display packets originating from our CSI transmitter.
     */
    if (memcmp(recv_info->src_addr,
               CONFIG_CSI_SEND_MAC,
               6) != 0) {
        return;
    }

    if (data_len >= (int)sizeof(uint32_t)) {

        uint32_t count = 0;

        memcpy(&count, data, sizeof(count));

        ESP_LOGI(TAG,
                 "ESP-NOW RX <- " MACSTR
                 " count=%" PRIu32,
                 MAC2STR(recv_info->src_addr),
                 count);
    }

    else {

        ESP_LOGI(TAG,
                 "ESP-NOW RX <- " MACSTR
                 " len=%d",
                 MAC2STR(recv_info->src_addr),
                 data_len);
    }
}


/* ============================================================
 * Wi-Fi initialization
 *
 * IMPORTANT:
 *
 * There is NO router.
 * There is NO hotspot.
 * There is NO example_connect().
 *
 * The ESP32-S3 simply starts its Wi-Fi radio in STA mode and
 * stays on channel 11.
 * ============================================================ */

static void wifi_init_no_router(void)
{
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();

    ESP_ERROR_CHECK(
        esp_wifi_init(&cfg)
    );

    ESP_ERROR_CHECK(
        esp_wifi_set_mode(WIFI_MODE_STA)
    );

    ESP_ERROR_CHECK(
        esp_wifi_set_storage(WIFI_STORAGE_RAM)
    );

    /*
     * Start Wi-Fi without connecting to an AP.
     */
    ESP_ERROR_CHECK(
        esp_wifi_start()
    );

    /*
     * Force channel 11.
     *
     * The COM7 transmitter is also configured for channel 11.
     */
    ESP_ERROR_CHECK(
        esp_wifi_set_channel(
            CSI_CHANNEL,
            WIFI_SECOND_CHAN_NONE
        )
    );

    /*
     * Disable power saving.
     *
     * This gives us a more stable CSI sampling cadence.
     */
    ESP_ERROR_CHECK(
        esp_wifi_set_ps(WIFI_PS_NONE)
    );

    ESP_LOGI(TAG,
             "Wi-Fi started WITHOUT router");

    ESP_LOGI(TAG,
             "Wi-Fi channel: %d",
             CSI_CHANNEL);
}


/* ============================================================
 * ESP-NOW initialization
 * ============================================================ */

static void espnow_rx_init(void)
{
    ESP_ERROR_CHECK(
        esp_now_init()
    );

    /*
     * Register the receive callback.
     */
    ESP_ERROR_CHECK(
        esp_now_register_recv_cb(
            espnow_recv_cb
        )
    );

    /*
     * Add broadcast peer.
     *
     * The transmitter sends broadcast ESP-NOW packets.
     */
    esp_now_peer_info_t peer = {0};

    memset(
        peer.peer_addr,
        0xff,
        ESP_NOW_ETH_ALEN
    );

    peer.channel = CSI_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;

    if (!esp_now_is_peer_exist(peer.peer_addr)) {

        ESP_ERROR_CHECK(
            esp_now_add_peer(&peer)
        );
    }

    ESP_LOGI(TAG,
             "ESP-NOW receiver initialized");
}


/* ============================================================
 * Motion event callback
 * ============================================================ */

static void on_motion_event(
    esp_wifi_sensing_fsm_handle_t handle,
    const uint8_t peer_mac[6],
    esp_wifi_sensing_fsm_event_t event,
    uint32_t data,
    void *usr_data)
{
    (void)handle;
    (void)usr_data;

    /*
     * Only process our dedicated CSI transmitter.
     */
    if (memcmp(peer_mac,
               CONFIG_CSI_SEND_MAC,
               6) != 0) {
        return;
    }

    if (event == ESP_WIFI_SENSING_FSM_EVENT_ACTIVE) {

        ESP_LOGI(
            TAG,
            "[CSI] ACTIVE peer=" MACSTR
            " data=%" PRIu32,
            MAC2STR(peer_mac),
            data
        );
    }

    else if (event == ESP_WIFI_SENSING_FSM_EVENT_INACTIVE) {

        ESP_LOGI(
            TAG,
            "[CSI] INACTIVE peer=" MACSTR,
            MAC2STR(peer_mac)
        );
    }
}


/* ============================================================
 * ESP Wi-Fi sensing / radar initialization
 * ============================================================ */

static void sensing_init(void)
{
    esp_wifi_sensing_fsm_config_t cfg =
        DEFAULT_ESP_WIFI_SENSING_FSM_CONFIG();

    /*
     * We have ONE sensing source:
     *
     * COM7 transmitter
     *
     * MAC:
     * 1a:00:00:00:00:00
     */
    cfg.max_channel_num = 1;

    ESP_ERROR_CHECK(
        esp_wifi_sensing_fsm_create(
            &cfg,
            &s_hms
        )
    );

    /*
     * Add our CSI transmitter as the sensing channel.
     */
    ESP_ERROR_CHECK(
        esp_wifi_sensing_fsm_add_channel(
            s_hms,
            CONFIG_CSI_SEND_MAC
        )
    );

    /*
     * ACTIVE callback.
     */
    ESP_ERROR_CHECK(
        esp_wifi_sensing_fsm_register_event_cb(
            s_hms,
            ESP_WIFI_SENSING_FSM_EVENT_ACTIVE,
            on_motion_event,
            NULL
        )
    );

    /*
     * INACTIVE callback.
     */
    ESP_ERROR_CHECK(
        esp_wifi_sensing_fsm_register_event_cb(
            s_hms,
            ESP_WIFI_SENSING_FSM_EVENT_INACTIVE,
            on_motion_event,
            NULL
        )
    );

    /*
     * Start sensing FSM.
     */
    ESP_ERROR_CHECK(
        esp_wifi_sensing_fsm_control(
            s_hms,
            ESP_WIFI_SENSING_FSM_CTRL_START,
            NULL
        )
    );

    ESP_LOGI(
        TAG,
        "========================================"
    );

    ESP_LOGI(
        TAG,
        "CSI WIFI SENSING STARTED"
    );

    ESP_LOGI(
        TAG,
        "Channel: %d",
        CSI_CHANNEL
    );

    ESP_LOGI(
        TAG,
        "CSI sender: " MACSTR,
        MAC2STR(CONFIG_CSI_SEND_MAC)
    );

    ESP_LOGI(
        TAG,
        "Router: NONE"
    );

    ESP_LOGI(
        TAG,
        "========================================"
    );
}


/* ============================================================
 * Application entry point
 * ============================================================ */

void app_main(void)
{
    /*
     * ---------------------------------------------------------
     * NVS initialization
     * ---------------------------------------------------------
     */

    esp_err_t ret = nvs_flash_init();

    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {

        ESP_ERROR_CHECK(
            nvs_flash_erase()
        );

        ret = nvs_flash_init();
    }

    ESP_ERROR_CHECK(ret);


    /*
     * ---------------------------------------------------------
     * Network stack
     * ---------------------------------------------------------
     */

    ESP_ERROR_CHECK(
        esp_netif_init()
    );

    ESP_ERROR_CHECK(
        esp_event_loop_create_default()
    );


    /*
     * ---------------------------------------------------------
     * LED
     * ---------------------------------------------------------
     */

    ESP_ERROR_CHECK(
        led_init()
    );

    ESP_ERROR_CHECK(
        esp_event_handler_register(
            WIFI_EVENT,
            WIFI_EVENT_STA_CONNECTED,
            wifi_event_handler,
            NULL
        )
    );

    ESP_ERROR_CHECK(
        esp_event_handler_register(
            WIFI_EVENT,
            WIFI_EVENT_STA_DISCONNECTED,
            wifi_event_handler,
            NULL
        )
    );

    led_set_wifi_connected(false);


    /*
     * ---------------------------------------------------------
     * Wi-Fi
     *
     * NO ROUTER / NO HOTSPOT
     * ---------------------------------------------------------
     */

    wifi_init_no_router();


    /*
     * ---------------------------------------------------------
     * ESP-NOW
     * ---------------------------------------------------------
     */

    espnow_rx_init();


    /*
     * ---------------------------------------------------------
     * CSI / RADAR
     * ---------------------------------------------------------
     */

    sensing_init();


    /*
     * ---------------------------------------------------------
     * Web Serial Monitor
     * ---------------------------------------------------------
     */

#if CONFIG_ESP_WIFI_SENSING_WEB_SERIAL_ENABLE

    web_serial_monitor_peer_t serial_peers[] = {
        { .name = "CSI_TX" },
    };

    memcpy(
        serial_peers[0].mac,
        CONFIG_CSI_SEND_MAC,
        sizeof(CONFIG_CSI_SEND_MAC)
    );

    web_serial_monitor_config_t serial_cfg = {
        .fsm = s_hms,
        .peers = serial_peers,
        .peer_num = 1,
        .stream_period_ms =
            CONFIG_ESP_WIFI_SENSING_WEB_SERIAL_STREAM_PERIOD_MS,
    };

    ESP_ERROR_CHECK(
        web_serial_monitor_init(
            &serial_cfg
        )
    );

#endif


    /*
     * ---------------------------------------------------------
     * Main task
     * ---------------------------------------------------------
     */

    while (1) {

        vTaskDelay(
            pdMS_TO_TICKS(1000)
        );
    }
}