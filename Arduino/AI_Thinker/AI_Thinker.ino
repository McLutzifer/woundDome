#include "esp_camera.h"
#include "FS.h"
#include "LittleFS.h"
#include <WiFi.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>

// ================= WLAN =================
const char* ssid     = "AndroidAP";
const char* password = "stcl6416";

// ================= MQTT =================
const char* mqtt_host  = "10.167.157.206";
const uint16_t mqtt_port = 1883;
const char* mqtt_user  = "";
const char* mqtt_pass  = "";
const char* topic_cmd  = "esp32cam/cmd";
const char* topic_url  = "esp32cam/url";
const char* topic_stat = "esp32cam/status";

// ================= Webserver =============
WebServer server(80);

// ================= Kamera-Pins XIAO ESP32S3 Sense =================
// #define PWDN_GPIO_NUM  -1
// #define RESET_GPIO_NUM -1
// #define XCLK_GPIO_NUM  10
// #define SIOD_GPIO_NUM  40
// #define SIOC_GPIO_NUM  39

// #define Y9_GPIO_NUM    48
// #define Y8_GPIO_NUM    11
// #define Y7_GPIO_NUM    12
// #define Y6_GPIO_NUM    14
// #define Y5_GPIO_NUM    16
// #define Y4_GPIO_NUM    18
// #define Y3_GPIO_NUM    17
// #define Y2_GPIO_NUM    15
// #define VSYNC_GPIO_NUM 38
// #define HREF_GPIO_NUM  47
// #define PCLK_GPIO_NUM  13

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
camera_config_t cfg;

// Flags für Aktionen
volatile bool triggerMqttCapture = false;
volatile bool triggerWebCapture  = false;

// ---------- Hilfsfunktion: Bild-URL über MQTT senden ----------
void publishUrl() {
  String url = "http://" + WiFi.localIP().toString() + "/latest.jpg";
  mqtt.publish(topic_url, url.c_str(), true);
}

// ---------- Zentrale Capture+Upload-Funktion ----------
bool captureAndSend(const char* fsPath, const char* serverUrl, bool doUpload) {
  // 1) Frame holen
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("❌ Kamera liefert kein Frame!");
    return false;
  }

  bool fsOk   = false;
  bool httpOk = !doUpload; // wenn kein Upload, ist dieser Teil automatisch "ok"

  // 2) Im LittleFS speichern
  {
    File f = LittleFS.open(fsPath, FILE_WRITE);
    if (!f) {
      Serial.println("❌ Konnte Datei nicht öffnen");
    } else {
      size_t w = f.write(fb->buf, fb->len);
      f.close();
      fsOk = (w == fb->len);
      Serial.println(fsOk ? "✅ Bild im FS gespeichert" : "❌ Fehler beim Schreiben ins FS");
    }
  }

  // 3) HTTP Upload (RAW JPEG), falls gewünscht
  if (doUpload) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "image/jpeg");
    int code = http.POST(fb->buf, fb->len);
    Serial.print("Upload-Response: ");
    Serial.println(code);
    httpOk = (code == 200);
    http.end();
  }

  // 4) Framebuffer freigeben
  esp_camera_fb_return(fb);

  // 5) Bild-URL über MQTT veröffentlichen (nur wenn FS ok)
  if (fsOk) {
    publishUrl();
  }

  return fsOk && httpOk;
}

// ---------- Webserver-Handler ----------
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
  // Nicht direkt Kamera benutzen, nur Flag setzen
  triggerWebCapture = true;
  server.sendHeader("Location", "/");
  server.send(302);
}

void handleLatest() {
  File f = LittleFS.open("/latest.jpg", FILE_READ);
  if (!f) {
    server.send(404, "text/plain", "No image");
    return;
  }
  server.streamFile(f, "image/jpeg");
  f.close();
}

// ---------- MQTT Callback ----------
void mqttCallback(char* topic, byte* payload, unsigned int len) {
  String t(topic);
  String msg;
  msg.reserve(len);
  for (unsigned int i = 0; i < len; i++) msg += (char)payload[i];
  msg.trim();
  msg.toLowerCase();

  if (t == topic_cmd && msg == "capture") {
    Serial.println("MQTT: capture angefordert");
    triggerMqttCapture = true;
  }
}

unsigned long lastMqttAttempt = 0;

void ensureMqtt() {
  if (mqtt.connected()) return;

  mqtt.setServer(mqtt_host, mqtt_port);
  mqtt.setKeepAlive(60);
  mqtt.setCallback(mqttCallback);

  if (millis() - lastMqttAttempt < 3000) return;
  lastMqttAttempt = millis();

  String cid = "esp32cam-" + String((uint32_t)ESP.getEfuseMac(), HEX);

  if (mqtt.connect(cid.c_str(), mqtt_user, mqtt_pass, topic_stat, 0, true, "offline")) {
    mqtt.publish(topic_stat, "online", true);
    mqtt.subscribe(topic_cmd);
    publishUrl();
    Serial.println("✅ MQTT verbunden");
  } else {
    Serial.print("❌ MQTT fehlgeschlagen, rc=");
    Serial.println(mqtt.state());
  }
}

// ---------- WLAN verbinden mit Timeout ----------
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(ssid, password);

  Serial.print("WLAN verbinden");
  unsigned long start = millis();
  const unsigned long timeout = 15000;

  while (WiFi.status() != WL_CONNECTED && millis() - start < timeout) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n❌ WLAN Timeout – Neustart");
    delay(1000);
    ESP.restart();
  }

  Serial.println("\n✅ WLAN verbunden");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
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
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer   = LEDC_TIMER_0;
  cfg.pin_d0       = Y2_GPIO_NUM;
  cfg.pin_d1       = Y3_GPIO_NUM;
  cfg.pin_d2       = Y4_GPIO_NUM;
  cfg.pin_d3       = Y5_GPIO_NUM;
  cfg.pin_d4       = Y6_GPIO_NUM;
  cfg.pin_d5       = Y7_GPIO_NUM;
  cfg.pin_d6       = Y8_GPIO_NUM;
  cfg.pin_d7       = Y9_GPIO_NUM;
  cfg.pin_xclk     = XCLK_GPIO_NUM;
  cfg.pin_pclk     = PCLK_GPIO_NUM;
  cfg.pin_vsync    = VSYNC_GPIO_NUM;
  cfg.pin_href     = HREF_GPIO_NUM;
  cfg.pin_sccb_sda = SIOD_GPIO_NUM;
  cfg.pin_sccb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn     = PWDN_GPIO_NUM;
  cfg.pin_reset    = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;

  // Beim S3 lieber konservativ:
  cfg.frame_size   = FRAMESIZE_QVGA; // kleiner = stabiler
  cfg.jpeg_quality = 15;             // größere Zahl = kleinere Datei
  if (psramFound()) {
    cfg.fb_count = 2;
    cfg.frame_size = FRAMESIZE_VGA;
    cfg.jpeg_quality = 12;
} else {
    cfg.fb_count = 1;
    cfg.frame_size = FRAMESIZE_QQVGA;
}             // nur ein Framebuffer

  if (esp_camera_init(&cfg) != ESP_OK) {
    Serial.println("Camera init failed");
    return;
  }


  // WLAN
  connectWiFi();
  if (MDNS.begin("esp32cam")) Serial.println("mDNS: http://esp32cam.local/");

  // Webserver
  server.on("/", handleRoot);
  server.on("/capture", handleCapture);
  server.on("/latest.jpg", handleLatest);
  server.begin();
  Serial.println("HTTP server ready");

  // MQTT
  Serial.println("Connecting to MQTT...");
  ensureMqtt();
  if (mqtt.connected()) {
    Serial.println("MQTT connected, continuing setup...");
  } else {
    Serial.println("MQTT not connected (yet), continuing anyway...");
  }
}

// ---------- Loop ----------
void loop() {
  static unsigned long lastLog = 0;
  if (millis() - lastLog > 3000) {
    Serial.println("Loop OK");
    lastLog = millis();
  }

  server.handleClient();
  if (!mqtt.connected()) ensureMqtt();
  mqtt.loop();

  // Zentrale Capture-Logik:
  if (triggerMqttCapture || triggerWebCapture) {
    bool doUpload = triggerMqttCapture; // nur MQTT will Upload
    triggerMqttCapture = false;
    triggerWebCapture  = false;

    // kleine Pause, damit Kamera / WiFi sich "fangen"
    delay(200);

    bool ok = captureAndSend("/latest.jpg", "http://10.167.157.26:8000/upload", doUpload);

    if (doUpload) {
      mqtt.publish(topic_stat, ok ? "captured" : "capture_failed", false);
    }
  }
}
