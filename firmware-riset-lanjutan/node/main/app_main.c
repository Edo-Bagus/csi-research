/**
 * RISET_CSI_2 — Receiver CSI ESP32-C6, mode STREAM TCP (multi-STA).
 *
 * Perbedaan dari varian sebelumnya:
 *   - Sink data = socket TCP ke laptop kolektor, BUKAN UART/USB.
 *     Laptop berdiri sendiri di router yang sama; tidak ada kabel USB sama sekali.
 *   - node_id diturunkan dari MAC factory saat runtime (bukan CONFIG_TX_ID
 *     compile-time), jadi SATU binary dipakai untuk semua board. Tidak ada lagi
 *     risiko salah label dataset karena salah flash.
 *   - Field msg_id lama DIHAPUS. Isinya dulu dibaca dari payload+15 — peninggalan
 *     era ESP-NOW yang sudah tidak valid untuk ICMP reply (terbukti konstan
 *     1157629952 di seluruh 302 baris test_ap.csv). Penggantinya seq: counter
 *     lokal per node, monotonic, berguna untuk deteksi gap.
 *
 * Alignment antar-node memakai skema (a) time-binned: setiap board independen,
 * penyelarasan dilakukan di host memakai timestamp kedatangan. Karena itu
 * firmware ini TIDAK berusaha sinkron dengan board lain.
 *
 * Varian mode log RSSI disimpan di main/app_main_rssi_log.c.bak (tidak ikut
 * dikompilasi karena bukan berekstensi .c).
 *
 * Target: ESP32-C6, ESP-IDF 5.5.2. Router ASUS RT-AX53U, channel 11, HE20.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <assert.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/message_buffer.h"
#include "freertos/event_groups.h"
#include "freertos/timers.h"
#include "nvs_flash.h"

#include "sdkconfig.h"
#include "esp_mac.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_timer.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "ping/ping_sock.h"
#include "esp_csi_gain_ctrl.h"

#define CONFIG_LESS_INTERFERENCE_CHANNEL   11
#define CONFIG_WIFI_BAND_MODE               WIFI_BAND_MODE_2G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS           WIFI_BW_HT20  // 20 MHz = 256 subcarrier @ 802.11ax
#define CONFIG_WIFI_2G_PROTOCOL             WIFI_PROTOCOL_11AX

#define CONFIG_FORCE_GAIN                   0

#define WIFI_STA_SSID                       CONFIG_CSI_WIFI_SSID
#define WIFI_STA_PASSWORD                   CONFIG_CSI_WIFI_PASSWORD

/**
 * Alamat laptop kolektor.
 *
 * Pada riset ini alamat laptop dikunci lewat DHCP reservation di router
 * ASUS RT-AX53U, jadi nilainya tetap selama reservation tidak dihapus.
 * Isi lewat `idf.py menuconfig`, lihat main/Kconfig.projbuild.
 *
 * Catatan: alamat itu berada DI DALAM DHCP pool. Reservation tetap mengunci
 * alamatnya, tapi kalau reservation dihapus, alamat bisa berpindah dan board
 * harus di-flash ulang. Kalau ini jadi sering, pertimbangkan UDP discovery.
 */
#define COLLECTOR_IP                        CONFIG_CSI_COLLECTOR_IP
#define COLLECTOR_PORT                      5566

// Rate ping = rate CSI. 100 ms -> ~10 paket/detik per node.
#define PING_INTERVAL_MS                    100
#define PING_TIMEOUT_MS                     (PING_INTERVAL_MS / 2)
#define PING_DATA_SIZE                      32

#define WIFI_RECONNECT_DELAY_MS             2000
#define WIFI_CONNECT_TIMEOUT_MS             15000

// Batas buffer CSI dalam jumlah int16. 1024 int16 = 512 subcarrier kompleks.
// Nilai normal HE20 yang teramati: len = 512 (256 subcarrier).
#define CONFIG_CSI_MAX_LEN                  1024

/**
 * Filter jenis frame berdasarkan sig_len (v2).
 *
 * Router mengirim >1 jenis frame ke BSSID yang sama. Terukur pada capture
 * 2026-09-09: sig_len=114 (ICMP echo reply, yang memang kita picu lewat ping)
 * dan sig_len=94 (frame lain) datang ~50/50, tapi punya distribusi amplitudo
 * dan varians berbeda -- amp 19.2 / CV 0.125 vs amp 23.5 / CV 0.296.
 *
 * Mencampur keduanya menyuntikkan bimodalitas ke dataset yang penyebabnya
 * jenis frame, BUKAN keberadaan orang. Jadi hanya satu jenis yang diambil.
 *
 * Set CSI_FILTER_SIG_LEN ke 0 untuk merekam semua jenis (mode diagnostik,
 * berguna kalau perlu melihat lagi komposisi frame dari router).
 */
#define CSI_FILTER_SIG_LEN                  1
#define CSI_ACCEPT_SIG_LEN                  114

#define MSG_BUF_SIZE                        (128 * 1024)
/**
 * Batching dimatikan (v2).
 *
 * v1 menumpuk sampai 8 KB sebelum kirim. Akibatnya ~8 paket tiba di laptop
 * nyaris bersamaan dan mendapat host_time yang hampir identik, padahal
 * ditangkap belasan sampai puluhan ms terpisah. Terukur pada capture
 * 2026-09-09: 70-77% paket datang <5 ms terpisah, error timestamp std 84 ms
 * (node38) sampai 3200 ms (node4b) -- lebih besar dari lebar bin 150 ms,
 * sehingga penyelarasan skema (a) jadi tidak valid.
 *
 * Sekarang setiap paket dikirim langsung. Overhead-nya sepele: ~1 KB per paket
 * pada ~13 pkt/s = ~13 KB/s, jauh di bawah kapasitas link.
 */
#define TCP_WRITE_BUF_SIZE                  (2 * 1024)
#define TCP_RECONNECT_DELAY_MS              1000
#define TCP_SEND_TIMEOUT_MS                 2000
// Magic dikirim ulang berkala supaya kolektor bisa resync kalau stream terpotong.
#define STREAM_MAGIC_INTERVAL_MS            1000
#define STREAM_MAGIC                        0xDEADBEEFu

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
#define ESP_IF_WIFI_STA ESP_MAC_WIFI_STA
#endif

static const char *TAG = "csi_tcp";

/**
 * Frame biner per paket CSI.
 *
 * Berubah dari versi UART lama:
 *   - msg_id (uint32, garbage) -> seq (uint32, counter lokal node)
 *   - tx_id (uint8, compile-time) -> node_id (uint8, dari MAC)
 *   - + node_mac[6]: identitas penuh node, supaya kolektor tidak perlu tabel
 *     lookup node_id -> board.
 *
 * TIDAK ada version field di frame (warisan desain lama). Kalau struct ini
 * diubah, csi_collector.py HARUS diubah di commit yang sama — ketidakcocokan
 * menghasilkan CSV yang terparsing tapi isinya sampah, bukan error.
 */
typedef struct {
    uint32_t seq;                 // counter lokal node, monotonic, untuk deteksi gap
    uint8_t  node_id;             // 2 byte terakhir MAC di-fold; lihat node_id_from_mac()
    uint8_t  node_mac[6];
    int16_t  rssi;
    uint8_t  rate;
    int8_t   noise_floor;
    int8_t   fft_gain;
    uint8_t  agc_gain;
    uint8_t  channel;
    uint8_t  first_word_invalid;
    uint8_t  ap_mac[6];           // BSSID router (sumber paket)
    uint32_t timestamp;           // rx_ctrl->timestamp, jam LOKAL board (bukan wall clock)
    // uptime_us diambil DI DALAM callback CSI, sedekat mungkin dengan saat paket
    // benar-benar diterima radio. Inilah sumber waktu intra-node yang akurat:
    // host_time masih kena jitter jaringan, tapi selisih uptime_us antar paket
    // di node yang sama bebas dari jitter itu. Lihat csi_merge.py.
    uint64_t uptime_us;           // esp_timer saat capture, sejak boot
    uint64_t sent_us;             // esp_timer saat frame dikirim ke socket
    uint16_t sig_len;
    uint8_t  rx_state;
    uint16_t len;                 // jumlah int16 CSI yang menyusul
    int16_t  csi_buf[CONFIG_CSI_MAX_LEN];
} __attribute__((packed)) csi_binary_msg_t;

// Ukuran header = seluruh struct dikurangi payload CSI.
#define CSI_HEADER_SIZE (offsetof(csi_binary_msg_t, csi_buf))

static MessageBufferHandle_t s_msg_buf = NULL;
static volatile uint32_t s_drop_count = 0;
static volatile uint32_t s_sent_count = 0;
static volatile uint32_t s_recv_count = 0;
static volatile uint32_t s_max_seen_len = 0;
static volatile uint32_t s_oversize_count = 0;
static volatile uint32_t s_filtered_count = 0;   // paket dibuang oleh filter sig_len
static volatile bool s_stream_connected = false;

static volatile bool s_sta_connected = false;
static uint8_t s_ap_bssid[6] = {0};
static uint8_t s_node_mac[6] = {0};
static uint8_t s_node_id = 0;
static esp_ip4_addr_t s_gateway_ip = {0};
static EventGroupHandle_t s_wifi_event_group = NULL;
#define WIFI_CONNECTED_BIT BIT0
static esp_netif_t *s_sta_netif = NULL;
static TimerHandle_t s_reconnect_timer = NULL;

/**
 * node_id 1 byte dari MAC.
 *
 * XOR dua byte terakhir MAC. Cukup untuk membedakan 2-3 board di satu ruangan,
 * dan tetap stabil lintas reboot/reflash. Tabrakan mungkin secara teori — kalau
 * itu terjadi, node_mac[6] di frame tetap unik, jadi kolektor bisa memakai MAC
 * sebagai identitas otoritatif dan node_id hanya sebagai label pendek.
 */
static uint8_t node_id_from_mac(const uint8_t mac[6])
{
    return (uint8_t)(mac[4] ^ mac[5]);
}

static void reconnect_timer_cb(TimerHandle_t xTimer)
{
    (void)xTimer;
    esp_wifi_connect();
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data)
{
    (void)arg;

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_CONNECTED) {
        const wifi_event_sta_connected_t *ev = (const wifi_event_sta_connected_t *)event_data;
        memcpy(s_ap_bssid, ev->bssid, sizeof(s_ap_bssid));
        ESP_LOGI(TAG, "STA connected, BSSID " MACSTR ", channel %d",
                 MAC2STR(ev->bssid), ev->channel);
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_sta_connected = false;
        if (s_wifi_event_group) {
            xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        }
        ESP_LOGW(TAG, "STA disconnected (reason %d), retry in %d ms",
                 ((const wifi_event_sta_disconnected_t *)event_data)->reason,
                 WIFI_RECONNECT_DELAY_MS);
        // Retry lewat timer, bukan vTaskDelay(): handler ini jalan di task event
        // loop, blocking di sini menahan semua event WiFi/IP lain.
        if (s_reconnect_timer) {
            xTimerStart(s_reconnect_timer, 0);
        }
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *ev = (const ip_event_got_ip_t *)event_data;
        esp_netif_ip_info_t ip_info;
        if (esp_netif_get_ip_info(ev->esp_netif, &ip_info) == ESP_OK) {
            s_gateway_ip = ip_info.gw;
        } else {
            s_gateway_ip = ev->ip_info.gw;
        }
        s_sta_connected = true;
        ESP_LOGI(TAG, "Got IP " IPSTR ", gateway " IPSTR,
                 IP2STR(&ev->ip_info.ip), IP2STR(&s_gateway_ip));
        if (s_wifi_event_group) {
            xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        }
        return;
    }
}

static void wifi_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    s_sta_netif = esp_netif_create_default_wifi_sta();
    assert(s_sta_netif != NULL);

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
    wifi_protocols_t protocols = {
        .ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
    };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
    wifi_bandwidths_t bandwidth = {
        .ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
    };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));

    // PS harus OFF: power save membuat board tidur dan melewatkan paket CSI.
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    if (CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_2G_ONLY && CONFIG_WIFI_2G_BANDWIDTHS == WIFI_BW_HT20) {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_NONE));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_BELOW));
    }
    // MAC factory sengaja TIDAK di-override: itu identitas node (lihat node_id_from_mac).

    wifi_config_t sta_config = {
        .sta = {
            .ssid = WIFI_STA_SSID,
            .password = WIFI_STA_PASSWORD,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
            .scan_method = WIFI_FAST_SCAN,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_config));
    // Tanpa ESP_ERROR_CHECK: connect pertama bisa gagal sementara; ditangani
    // handler DISCONNECTED + loop timeout di app_main(), bukan dengan abort.
    esp_err_t conn_ret = esp_wifi_connect();
    if (conn_ret != ESP_OK) {
        ESP_LOGW(TAG, "initial esp_wifi_connect() failed: %s, will retry",
                 esp_err_to_name(conn_ret));
    }
}

/**
 * Traffic generator.
 *
 * Router tidak mengirim unicast ke STA tanpa dipicu, jadi tanpa ini CSI callback
 * tidak pernah jalan. Setiap echo reply adalah unicast HE frame yang memicu
 * wifi_csi_rx_cb.
 *
 * Catatan multi-STA: tiap board nge-ping sendiri-sendiri, jadi paket yang
 * diamati board A dan board B BUKAN paket yang sama. Ini konsekuensi skema (a);
 * penyelarasan dilakukan di host lewat binning waktu.
 */
static void icmp_ping_task(void *arg)
{
    (void)arg;
    esp_ping_handle_t ping_handle = NULL;

    while (1) {
        if (!s_sta_connected || s_gateway_ip.addr == 0) {
            if (ping_handle) {
                esp_ping_stop(ping_handle);
                esp_ping_delete_session(ping_handle);
                ping_handle = NULL;
            }
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }

        if (ping_handle == NULL) {
            ip_addr_t target = {0};
            target.type = IPADDR_TYPE_V4;
            target.u_addr.ip4.addr = s_gateway_ip.addr;

            esp_ping_config_t ping_config = ESP_PING_DEFAULT_CONFIG();
            ping_config.target_addr = target;
            ping_config.count = ESP_PING_COUNT_INFINITE;
            ping_config.interval_ms = PING_INTERVAL_MS;
            ping_config.timeout_ms = PING_TIMEOUT_MS;
            ping_config.data_size = PING_DATA_SIZE;
            ping_config.task_stack_size = 4096;
            ping_config.task_prio = 2;

            esp_ping_callbacks_t cbs = {0};

            if (esp_ping_new_session(&ping_config, &cbs, &ping_handle) == ESP_OK) {
                if (esp_ping_start(ping_handle) != ESP_OK) {
                    esp_ping_delete_session(ping_handle);
                    ping_handle = NULL;
                }
            } else {
                ping_handle = NULL;
            }

            if (ping_handle == NULL) {
                vTaskDelay(pdMS_TO_TICKS(1000));
                continue;
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

/**
 * Buka socket TCP ke kolektor. Mengembalikan fd, atau -1 kalau gagal.
 *
 * TCP (bukan UDP) dipilih supaya kehilangan paket tidak diam-diam merusak
 * dataset: kalau link putus, kita tahu dari error write, bukan dari baris yang
 * hilang tanpa jejak.
 */
static int collector_connect(void)
{
    struct sockaddr_in dest = {0};
    dest.sin_family = AF_INET;
    dest.sin_port = htons(COLLECTOR_PORT);
    if (inet_pton(AF_INET, COLLECTOR_IP, &dest.sin_addr) != 1) {
        ESP_LOGE(TAG, "COLLECTOR_IP '%s' tidak valid", COLLECTOR_IP);
        return -1;
    }

    int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock < 0) {
        ESP_LOGW(TAG, "socket() gagal: errno %d", errno);
        return -1;
    }

    if (connect(sock, (struct sockaddr *)&dest, sizeof(dest)) != 0) {
        ESP_LOGW(TAG, "connect() ke %s:%d gagal: errno %d",
                 COLLECTOR_IP, COLLECTOR_PORT, errno);
        close(sock);
        return -1;
    }

    // Timeout kirim: tanpa ini, kolektor yang berhenti membaca akan memblokir
    // task ini selamanya dan message buffer meluap diam-diam.
    struct timeval tv = {
        .tv_sec = TCP_SEND_TIMEOUT_MS / 1000,
        .tv_usec = (TCP_SEND_TIMEOUT_MS % 1000) * 1000,
    };
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    // Nagle OFF: tiap paket dikirim sendiri-sendiri dan harus berangkat SEKARANG.
    // Kalau Nagle aktif, kernel menahan paket kecil untuk digabung -- persis
    // efek batching yang justru sedang kita hilangkan di v2.
    int flag = 1;
    setsockopt(sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

    ESP_LOGI(TAG, "Tersambung ke kolektor %s:%d", COLLECTOR_IP, COLLECTOR_PORT);
    return sock;
}

// Kirim seluruh buffer; TCP boleh mengirim sebagian, jadi harus di-loop.
static bool send_all(int sock, const uint8_t *data, size_t len)
{
    size_t off = 0;
    while (off < len) {
        int w = send(sock, data + off, len - off, 0);
        if (w <= 0) {
            return false;
        }
        off += (size_t)w;
    }
    return true;
}

/**
 * Task pengirim: ambil paket dari message buffer, batch, kirim lewat TCP.
 *
 * Alasan ada task terpisah (bukan kirim langsung dari CSI callback): callback
 * jalan di konteks driver WiFi. I/O yang blocking di sana akan menahan driver
 * dan membuat paket ter-drop diam-diam. Message buffer memindahkan I/O ke sini.
 */
static void tcp_send_task(void *arg)
{
    (void)arg;
    static uint8_t pkt_buf[sizeof(csi_binary_msg_t)];

    int sock = -1;
    TickType_t last_magic_tick = xTaskGetTickCount();
    const TickType_t magic_interval = pdMS_TO_TICKS(STREAM_MAGIC_INTERVAL_MS);

    while (1) {
        if (sock < 0) {
            s_stream_connected = false;
            if (!s_sta_connected) {
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }
            sock = collector_connect();
            if (sock < 0) {
                vTaskDelay(pdMS_TO_TICKS(TCP_RECONNECT_DELAY_MS));
                continue;
            }
            /**
             * [v2] Buang isi message buffer sebelum menandai link siap.
             *
             * Setelah reconnect, buffer bisa berisi paket dari beberapa detik
             * lalu. Kalau dikirim, kolektor menstempelnya dengan host_time
             * SEKARANG -- CSI lama tampak baru, dan penyelarasan berbasis waktu
             * jadi salah tanpa gejala yang kelihatan.
             */
            {
                size_t flushed = 0;
                while (xMessageBufferReceive(s_msg_buf, pkt_buf, sizeof(pkt_buf), 0) > 0) {
                    flushed++;
                }
                if (flushed) {
                    ESP_LOGI(TAG, "buang %u paket basi dari buffer", (unsigned)flushed);
                }
            }

            s_stream_connected = true;
            // Magic langsung setelah connect: penanda awal stream bagi kolektor.
            uint32_t magic = STREAM_MAGIC;
            if (!send_all(sock, (const uint8_t *)&magic, sizeof(magic))) {
                close(sock);
                sock = -1;
                continue;
            }
            last_magic_tick = xTaskGetTickCount();
        }

        size_t recv = xMessageBufferReceive(s_msg_buf, pkt_buf, sizeof(pkt_buf),
                                            pdMS_TO_TICKS(200));

        if (recv > 0) {
            // Stempel waktu kirim tepat sebelum masuk socket. Selisih
            // sent_us - uptime_us = lama paket mengantre di dalam board;
            // kolektor memakainya untuk memisahkan penundaan internal dari
            // jitter jaringan.
            if (recv >= CSI_HEADER_SIZE) {
                uint64_t now_us = (uint64_t)esp_timer_get_time();
                memcpy(pkt_buf + offsetof(csi_binary_msg_t, sent_us),
                       &now_us, sizeof(now_us));
            }

            // [v2] Kirim SATU paket per send, tanpa menumpuk. Batching di v1
            // membuat host_time beberapa paket jadi hampir identik dan merusak
            // penyelarasan berbasis waktu. Lihat catatan di TCP_WRITE_BUF_SIZE.
            if (!send_all(sock, pkt_buf, recv)) {
                ESP_LOGW(TAG, "send gagal (errno %d), reconnect", errno);
                close(sock);
                sock = -1;
                continue;
            }
            s_sent_count++;
        }

        TickType_t now = xTaskGetTickCount();
        if ((now - last_magic_tick) >= magic_interval) {
            // Tiap paket sudah dikirim utuh, jadi posisi ini selalu batas frame.
            uint32_t magic = STREAM_MAGIC;
            if (!send_all(sock, (const uint8_t *)&magic, sizeof(magic))) {
                close(sock);
                sock = -1;
                continue;
            }
            last_magic_tick = now;
        }
    }
}

static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;

    if (!info || !info->buf) {
        return;
    }
    // Sebelum STA terkoneksi, s_ap_bssid belum valid -> filter tidak bisa dipercaya.
    if (!s_sta_connected) {
        return;
    }
    // Hanya paket dari router yang terasosiasi.
    if (memcmp(info->mac, s_ap_bssid, 6) != 0) {
        return;
    }

    /**
     * Gate pada link kolektor (v2).
     *
     * Sebelum TCP tersambung, paket tidak bisa dikirim ke mana pun. v1 tetap
     * menaikkan seq untuk paket-paket ini, sehingga "gap" yang dilaporkan
     * kolektor tercampur antara "board menunggu kolektor" dan "data benar-benar
     * hilang". Terukur: jam ESP merentang 140.9 s sementara host hanya 59.3 s.
     *
     * Sekarang paket sebelum link siap dibuang tanpa menaikkan seq, jadi seq
     * menghitung paket yang BENAR-BENAR terkirim dan gap hanya berarti
     * kehilangan sungguhan.
     */
    if (!s_stream_connected) {
        return;
    }

#if CSI_FILTER_SIG_LEN
    // Buang jenis frame lain; lihat catatan di CSI_ACCEPT_SIG_LEN.
    if (info->rx_ctrl.sig_len != CSI_ACCEPT_SIG_LEN) {
        s_filtered_count++;
        return;
    }
#endif

    // Catat len terbesar SEBELUM guard, supaya terlihat kalau hardware
    // sebenarnya mengirim lebih dari CONFIG_CSI_MAX_LEN.
    if ((uint32_t)info->len > s_max_seen_len) {
        s_max_seen_len = (uint32_t)info->len;
    }
    if (info->len <= 0) {
        return;
    }
    if (info->len > CONFIG_CSI_MAX_LEN) {
        s_oversize_count++;
        return;
    }

    const wifi_pkt_rx_ctrl_t *rx_ctrl = &info->rx_ctrl;
    static uint32_t s_gain_count = 0;
    static uint8_t agc_gain = 0;
    static int8_t fft_gain = 0;
    static uint8_t agc_gain_baseline = 0;
    static int8_t fft_gain_baseline = 0;

    esp_csi_gain_ctrl_get_rx_gain(rx_ctrl, &agc_gain, &fft_gain);
    if (s_gain_count < 100) {
        esp_csi_gain_ctrl_record_rx_gain(agc_gain, fft_gain);
    } else if (s_gain_count == 100) {
        esp_csi_gain_ctrl_get_rx_gain_baseline(&agc_gain_baseline, &fft_gain_baseline);
#if CONFIG_FORCE_GAIN
        esp_csi_gain_ctrl_set_rx_force_gain(agc_gain_baseline, fft_gain_baseline);
#endif
    }
    s_gain_count++;

    csi_binary_msg_t msg = {0};
    msg.seq = ++s_recv_count;
    msg.node_id = s_node_id;
    memcpy(msg.node_mac, s_node_mac, sizeof(msg.node_mac));
    msg.rssi = rx_ctrl->rssi;
    msg.rate = rx_ctrl->rate;
    msg.noise_floor = rx_ctrl->noise_floor;
    msg.fft_gain = fft_gain;
    msg.agc_gain = agc_gain;
    msg.channel = rx_ctrl->channel;
    msg.first_word_invalid = info->first_word_invalid;
    memcpy(msg.ap_mac, info->mac, sizeof(msg.ap_mac));
    msg.timestamp = rx_ctrl->timestamp;
    msg.uptime_us = (uint64_t)esp_timer_get_time();   // waktu capture
    msg.sent_us = 0;                                  // diisi tcp_send_task
    msg.sig_len = rx_ctrl->sig_len;
    msg.rx_state = rx_ctrl->rx_state;
    msg.len = (uint16_t)info->len;

    for (int i = 0; i < info->len; i++) {
        msg.csi_buf[i] = (int16_t)info->buf[i];
    }

    // Hanya kirim header + CSI yang terpakai, bukan seluruh struct.
    size_t pkt_size = CSI_HEADER_SIZE + (size_t)msg.len * sizeof(int16_t);
    // Timeout 0: callback driver TIDAK boleh blocking. Kalau buffer penuh
    // (kolektor lambat / link putus), paket sengaja dibuang dan dihitung.
    if (xMessageBufferSend(s_msg_buf, &msg, pkt_size, 0) == 0) {
        s_drop_count++;
    }
}

static void wifi_csi_init(void)
{
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));

    // Spesifik HE-SU: hanya paket HE SU yang menghasilkan CSI. Kalau router
    // jatuh ke mode legacy/HT, callback akan sunyi meski WiFi sehat.
    wifi_csi_config_t csi_config = {
        .enable                 = true,
        .acquire_csi_legacy     = false,
        .acquire_csi_ht20       = false,
        .acquire_csi_ht40       = false,
        .acquire_csi_su         = true,
        .acquire_csi_mu         = false,
        .acquire_csi_dcm        = true,
        .acquire_csi_beamformed = true,
        .acquire_csi_he_stbc    = 2,
        .val_scale_cfg          = false,
        .dump_ack_en            = false,
        .reserved               = false
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

// Task diagnostik: satu baris status per 5 detik. Aman karena lewat ESP_LOG
// di task sendiri, bukan dari konteks callback driver.
static void stats_task(void *arg)
{
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        ESP_LOGI(TAG,
                 "node=%02x rx=%" PRIu32 " sent=%" PRIu32 " drop=%" PRIu32
                 " filt=%" PRIu32 " max_len=%" PRIu32 " oversize=%" PRIu32 " link=%s",
                 s_node_id, s_recv_count, s_sent_count, s_drop_count,
                 s_filtered_count, s_max_seen_len, s_oversize_count,
                 s_stream_connected ? "up" : "down");
    }
}

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Identitas node dari MAC factory: satu binary untuk semua board.
    ESP_ERROR_CHECK(esp_read_mac(s_node_mac, ESP_MAC_WIFI_STA));
    s_node_id = node_id_from_mac(s_node_mac);
    ESP_LOGI(TAG, "Node MAC " MACSTR " -> node_id 0x%02x", MAC2STR(s_node_mac), s_node_id);

    s_msg_buf = xMessageBufferCreate(MSG_BUF_SIZE);
    assert(s_msg_buf != NULL);

    s_wifi_event_group = xEventGroupCreate();
    assert(s_wifi_event_group != NULL);

    s_reconnect_timer = xTimerCreate("wifi_reconnect",
                                     pdMS_TO_TICKS(WIFI_RECONNECT_DELAY_MS),
                                     pdFALSE, NULL, reconnect_timer_cb);
    assert(s_reconnect_timer != NULL);

    // Urutan penting: event loop -> daftar handler -> wifi_init(). wifi_init()
    // memanggil esp_wifi_connect() di akhir; kalau handler belum terdaftar,
    // event CONNECTED/GOT_IP pertama bisa terlewat.
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_event_handler_instance_t inst_wifi = NULL;
    esp_event_handler_instance_t inst_ip = NULL;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                        &wifi_event_handler, NULL, &inst_wifi));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                        &wifi_event_handler, NULL, &inst_ip));

    wifi_init();

    // Lapisan kedua di atas auto-retry handler: menangani kasus asosiasi
    // menggantung tanpa event disconnect sama sekali.
    while (1) {
        EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                               WIFI_CONNECTED_BIT,
                                               pdFALSE, pdTRUE,
                                               pdMS_TO_TICKS(WIFI_CONNECT_TIMEOUT_MS));
        if (bits & WIFI_CONNECTED_BIT) {
            break;
        }
        ESP_LOGW(TAG, "Connect timeout after %d ms, retrying", WIFI_CONNECT_TIMEOUT_MS);
        esp_wifi_connect();
    }

    // Prioritas 3 > ping (2): pengiriman harus menang atas traffic generator,
    // karena buffer penuh berarti data hilang permanen.
    xTaskCreatePinnedToCore(tcp_send_task, "tcp_send_task", 4096, NULL, 3, NULL, tskNO_AFFINITY);
    // ESP32-C6 single-core (CONFIG_FREERTOS_UNICORE=y) -> tskNO_AFFINITY.
    xTaskCreatePinnedToCore(icmp_ping_task, "icmp_ping_task", 4096, NULL, 2, NULL, tskNO_AFFINITY);
    xTaskCreatePinnedToCore(stats_task, "stats_task", 3072, NULL, 1, NULL, tskNO_AFFINITY);

    wifi_csi_init();
}
