#include "esp_camera.h"
#include "FS.h"
#include "LittleFS.h"
#include <WiFi.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <ESPmDNS.h>

// Dein WLAN
const char* ssid = "AndroidAP";
const char* password = "stcl6416";

// ===== MQTT =====
const char* mqtt_host = "10.154.228.206";    // Broker-IP/Hostname
const uint16_t mqtt_port = 1883;
const char* mqtt_user = "";                // falls nötig
const char* mqtt_pass = "";                // falls nötig
const char* topic_cmd   = "esp32cam/cmd";  // Payload: "capture"
const char* topic_url   = "esp32cam/url";  // publiziert Bild-URL
const char* topic_stat  = "esp32cam/status"; // "online"/"offline"

// ===== Webserver =====
WebServer server(80);

// ===== Kamera-Pins (AI Thinker) =====
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WiFiClient espClient;
PubSubClient mqtt(espClient);

bool takePhotoTo(const char* path) {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) return false;
  File f = LittleFS.open(path, FILE_WRITE);
  if (!f) { esp_camera_fb_return(fb); return false; }
  size_t w = f.write(fb->buf, fb->len);
  f.close();
  esp_camera_fb_return(fb);
  return (w == fb->len);
}

// ---------- Webserver ----------
void handleRoot() {
  String html =
    "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>ESP32-CAM</title></head><body style='font-family:sans-serif'>"
    "<h1>ESP32-CAM</h1>"
    "<p><a href='/capture'><button>📷 Neues Foto</button></a></p>"
    "<p><img src='/latest.jpg?ts=" + String(millis()) + "' style='max-width:100%'></p>"
    "</body></html>";
  server.send(200, "text/html", html);
}
void handleCapture() {
  if (takePhotoTo("/latest.jpg")) {
    server.sendHeader("Location", "/");
    server.send(302);
  } else {
    server.send(500, "text/plain", "Capture/Save failed");
  }
}
void handleLatest() {
  File f = LittleFS.open("/latest.jpg", FILE_READ);
  if (!f) { server.send(404, "text/plain", "No image"); return; }
  server.streamFile(f, "image/jpeg");
  f.close();
}

// ---------- MQTT ----------
void publishUrl() {
  String url = "http://" + WiFi.localIP().toString() + "/latest.jpg";
  mqtt.publish(topic_url, url.c_str(), true);
}

void mqttCallback(char* topic, byte* payload, unsigned int len) {
  String t(topic);
  String msg; msg.reserve(len);
  for (unsigned int i=0;i<len;i++) msg += (char)payload[i];
  msg.trim(); msg.toLowerCase();

  if (t == topic_cmd && msg == "capture") {
    bool ok = takePhotoTo("/latest.jpg");
    if (ok) publishUrl();
    mqtt.publish(topic_stat, ok ? "captured" : "capture_failed", false);
  }
}

void ensureMqtt() {
  if (mqtt.connected()) return;
  mqtt.setServer(mqtt_host, mqtt_port);
  mqtt.setCallback(mqttCallback);
  while (!mqtt.connected()) {
    String cid = "esp32cam-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    if (mqtt.connect(cid.c_str(), mqtt_user, mqtt_pass, topic_stat, 0, true, "offline")) {
      mqtt.publish(topic_stat, "online", true);
      mqtt.subscribe(topic_cmd);
      publishUrl(); // aktuelle URL bereitstellen
    } else {
      delay(1000);
    }
  }
}

// ---------- Setup ----------
void setup() {
  Serial.begin(115200);
  delay(150);
  Serial.println("\nESP32-CAM MQTT/Webserver");

  // FS
  if (!LittleFS.begin(true)) {
    Serial.println("LittleFS mount failed");
    return;
  }

  // Kamera
  camera_config_t cfg;
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer   = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM;  cfg.pin_d1 = Y3_GPIO_NUM;
  cfg.pin_d2 = Y4_GPIO_NUM;  cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM;  cfg.pin_d5 = Y7_GPIO_NUM;
  cfg.pin_d6 = Y8_GPIO_NUM;  cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk = XCLK_GPIO_NUM; cfg.pin_pclk = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM; cfg.pin_href = HREF_GPIO_NUM;
  cfg.pin_sccb_sda = SIOD_GPIO_NUM; cfg.pin_sccb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn = PWDN_GPIO_NUM; cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;
  if (psramFound()) { cfg.frame_size = FRAMESIZE_VGA; cfg.jpeg_quality = 12; cfg.fb_count = 2; }
  else { cfg.frame_size = FRAMESIZE_QVGA; cfg.jpeg_quality = 12; cfg.fb_count = 1; }
  if (esp_camera_init(&cfg) != ESP_OK) {
    Serial.println("Camera init failed"); return;
  }

  // WLAN
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(ssid, password);
  Serial.print("WLAN verbinden");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println(); Serial.print("IP: "); Serial.println(WiFi.localIP());
  if (MDNS.begin("esp32cam")) Serial.println("mDNS: http://esp32cam.local/");

  // Webserver
  server.on("/", handleRoot);
  server.on("/capture", handleCapture);
  server.on("/latest.jpg", handleLatest);
  server.begin();
  Serial.println("HTTP server ready");

  // MQTT
  ensureMqtt();

  // optional: direkt ein erstes Foto
  if (takePhotoTo("/latest.jpg")) publishUrl();
}

// ---------- Loop ----------
void loop() {
  server.handleClient();
  if (!mqtt.connected()) ensureMqtt();
  mqtt.loop();
}
