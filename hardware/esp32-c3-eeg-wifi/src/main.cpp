#include <Arduino.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_system.h>

#include "wifi_config.h"

#define TGAM_RX_PIN 1
#define TGAM_TX_PIN 0
#define TGAM_BAUD 57600
#define USB_BAUD 115200

static const uint16_t SAMPLE_RATE_HZ = 512;
static const size_t RAW_CAPACITY = SAMPLE_RATE_HZ * 4;
static const size_t MAX_API_SAMPLES = 512;
static const uint8_t SYNC_BYTE = 0xAA;
static const uint8_t EXCODE_BYTE = 0x55;
static const uint8_t CODE_POOR_SIGNAL = 0x02;
static const uint8_t CODE_ATTENTION = 0x04;
static const uint8_t CODE_MEDITATION = 0x05;
static const uint8_t CODE_RAW = 0x80;
static const uint8_t CODE_RAW_PAIR = 0x82;
static const uint8_t CODE_EEG_POWER = 0x83;
static const uint8_t MAX_PAYLOAD_LEN = 169;

HardwareSerial TGAMSerial(1);
WebServer server(80);

enum ParserState
{
  WAIT_AA_1,
  WAIT_AA_2,
  READ_LENGTH,
  READ_PAYLOAD,
  READ_CHECKSUM
};
ParserState parserState = WAIT_AA_1;
uint8_t payload[256];
uint8_t payloadLength = 0;
uint8_t payloadIndex = 0;
uint16_t payloadSum = 0;

struct EegState
{
  int16_t raw = 0;
  uint8_t poorSignal = 200;
  uint8_t attention = 0;
  uint8_t meditation = 0;
  uint32_t bands[8] = {0};
};

EegState eeg;
int16_t rawRing[RAW_CAPACITY];
uint32_t nextSampleIndex = 0;
uint32_t validPacketCount = 0;
uint32_t checksumErrorCount = 0;
uint32_t summaryIndex = 0;
uint32_t bootId = 0;
uint32_t nextWifiRetryMs = 0;
bool httpStarted = false;
bool wifiAddressPrinted = false;
uint32_t lastSerialStatusMs = 0;

static int16_t readInt16(uint8_t high, uint8_t low)
{
  return (int16_t)(((uint16_t)high << 8) | low);
}

static uint32_t readUInt24(const uint8_t *value)
{
  return ((uint32_t)value[0] << 16) | ((uint32_t)value[1] << 8) | value[2];
}

void appendRaw(int16_t value)
{
  eeg.raw = value;
  rawRing[nextSampleIndex % RAW_CAPACITY] = value;
  nextSampleIndex++;
}

bool parsePayload(const uint8_t *data, uint8_t length)
{
  uint8_t cursor = 0;
  bool recognized = false;
  bool summaryChanged = false;

  while (cursor < length)
  {
    while (cursor < length && data[cursor] == EXCODE_BYTE)
      cursor++;
    if (cursor >= length)
      break;

    uint8_t code = data[cursor++];
    uint8_t valueLength = 1;
    if (code >= 0x80)
    {
      if (cursor >= length)
        break;
      valueLength = data[cursor++];
    }
    if ((uint16_t)cursor + valueLength > length)
      break;

    const uint8_t *value = data + cursor;
    switch (code)
    {
    case CODE_RAW:
      if (valueLength == 2)
      {
        appendRaw(readInt16(value[0], value[1]));
        recognized = true;
      }
      break;
    case CODE_RAW_PAIR:
      if (valueLength == 4)
      {
        appendRaw(readInt16(value[0], value[1]));
        appendRaw(readInt16(value[2], value[3]));
        recognized = true;
      }
      break;
    case CODE_POOR_SIGNAL:
      if (valueLength == 1)
      {
        eeg.poorSignal = value[0];
        recognized = summaryChanged = true;
      }
      break;
    case CODE_ATTENTION:
      if (valueLength == 1)
      {
        eeg.attention = value[0];
        recognized = summaryChanged = true;
      }
      break;
    case CODE_MEDITATION:
      if (valueLength == 1)
      {
        eeg.meditation = value[0];
        recognized = summaryChanged = true;
      }
      break;
    case CODE_EEG_POWER:
      if (valueLength == 24)
      {
        for (size_t i = 0; i < 8; i++)
          eeg.bands[i] = readUInt24(value + i * 3);
        recognized = summaryChanged = true;
      }
      break;
    default:
      break;
    }
    cursor += valueLength;
  }

  if (summaryChanged)
    summaryIndex++;
  return recognized;
}

void parseByte(uint8_t value)
{
  switch (parserState)
  {
  case WAIT_AA_1:
    if (value == SYNC_BYTE)
      parserState = WAIT_AA_2;
    break;
  case WAIT_AA_2:
    parserState = value == SYNC_BYTE ? READ_LENGTH : WAIT_AA_1;
    break;
  case READ_LENGTH:
    if (value == SYNC_BYTE)
      break;
    payloadLength = value;
    payloadIndex = 0;
    payloadSum = 0;
    parserState = payloadLength > 0 && payloadLength <= MAX_PAYLOAD_LEN
                      ? READ_PAYLOAD
                      : WAIT_AA_1;
    break;
  case READ_PAYLOAD:
    payload[payloadIndex++] = value;
    payloadSum += value;
    if (payloadIndex >= payloadLength)
      parserState = READ_CHECKSUM;
    break;
  case READ_CHECKSUM:
    if (value == ((~payloadSum) & 0xFF))
    {
      validPacketCount++;
      parsePayload(payload, payloadLength);
    }
    else
    {
      checksumErrorCount++;
    }
    parserState = WAIT_AA_1;
    break;
  }
}

void appendBandsJson(String &json)
{
  static const char *names[] = {"delta", "theta", "lowAlpha", "highAlpha",
                                "lowBeta", "highBeta", "lowGamma", "midGamma"};
  json += "\"bands\":{";
  for (size_t i = 0; i < 8; i++)
  {
    if (i)
      json += ',';
    json += '"';
    json += names[i];
    json += "\":";
    json += String(eeg.bands[i]);
  }
  json += '}';
}

void handleEegApi()
{
  uint32_t firstAvailable =
      nextSampleIndex > RAW_CAPACITY ? nextSampleIndex - RAW_CAPACITY : 0;
  uint32_t requestedAfter =
      server.hasArg("after") ? strtoul(server.arg("after").c_str(), nullptr, 10)
                             : firstAvailable;
  uint32_t after = requestedAfter;
  size_t limit = server.hasArg("limit") ? (size_t)server.arg("limit").toInt()
                                        : MAX_API_SAMPLES;
  limit = constrain(limit, 1, MAX_API_SAMPLES);

  bool overflow = after < firstAvailable;
  if (overflow)
    after = firstAvailable;
  if (after > nextSampleIndex)
    after = nextSampleIndex;
  uint32_t end = min(nextSampleIndex, after + (uint32_t)limit);

  String json;
  json.reserve(7000);
  json += "{\"schemaVersion\":1,\"deviceId\":\"";
  json += EEG_DEVICE_ID;
  json += "\",\"bootId\":";
  json += String(bootId);
  json += ",\"sampleRateHz\":";
  json += String(SAMPLE_RATE_HZ);
  json += ",\"firstAvailableIndex\":";
  json += String(firstAvailable);
  json += ",\"startIndex\":";
  json += String(after);
  json += ",\"nextSampleIndex\":";
  json += String(nextSampleIndex);
  json += ",\"returnedUntilIndex\":";
  json += String(end);
  json += ",\"overflow\":";
  json += overflow ? "true" : "false";
  json += ",\"lostSamples\":";
  json += String(overflow ? firstAvailable - requestedAfter : 0);
  json += ",\"summaryIndex\":";
  json += String(summaryIndex);
  json += ",\"poorSignal\":";
  json += String(eeg.poorSignal);
  json += ",\"attention\":";
  json += String(eeg.attention);
  json += ",\"meditation\":";
  json += String(eeg.meditation);
  json += ",\"rssi\":";
  json += WiFi.status() == WL_CONNECTED ? String(WiFi.RSSI()) : "0";
  json += ",\"validPackets\":";
  json += String(validPacketCount);
  json += ",\"checksumErrors\":";
  json += String(checksumErrorCount);
  json += ',';
  appendBandsJson(json);
  json += ",\"samples\":[";
  for (uint32_t index = after; index < end; index++)
  {
    if (index > after)
      json += ',';
    json += String(rawRing[index % RAW_CAPACITY]);
  }
  json += "]}";

  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json; charset=utf-8", json);
}

void handleLegacyDataApi()
{
  uint32_t start = nextSampleIndex > 256 ? nextSampleIndex - 256 : 0;
  String json;
  json.reserve(3500);
  json += "{\"ms\":";
  json += String(millis());
  json += ",\"wifi\":\"";
  json += WiFi.status() == WL_CONNECTED ? "connected" : "disconnected";
  json += "\",\"ip\":\"";
  json += WiFi.localIP().toString();
  json += "\",\"rssi\":";
  json += String(WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0);
  json += ",\"raw\":";
  json += String(eeg.raw);
  json += ",\"poor\":";
  json += String(eeg.poorSignal);
  json += ",\"att\":";
  json += String(eeg.attention);
  json += ",\"med\":";
  json += String(eeg.meditation);
  json += ",\"packet\":";
  json += String(validPacketCount);
  json += ",\"err\":";
  json += String(checksumErrorCount);
  json += ",\"raw_samples\":";
  json += String(nextSampleIndex);
  static const char *legacyBandNames[] = {
      "delta", "theta", "lowAlpha", "highAlpha",
      "lowBeta", "highBeta", "lowGamma", "middleGamma"};
  for (size_t i = 0; i < 8; i++)
  {
    json += ",\"";
    json += legacyBandNames[i];
    json += "\":";
    json += String(eeg.bands[i]);
  }
  json += ",\"raw_points\":[";
  for (uint32_t index = start; index < nextSampleIndex; index++)
  {
    if (index > start)
      json += ',';
    json += String(rawRing[index % RAW_CAPACITY]);
  }
  json += "],\"lines\":[]}";
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json; charset=utf-8", json);
}

void handleLegacyCsv()
{
  uint32_t start = nextSampleIndex > 256 ? nextSampleIndex - 256 : 0;
  String csv = "sample_index,raw\n";
  csv.reserve(4096);
  for (uint32_t index = start; index < nextSampleIndex; index++)
  {
    csv += String(index);
    csv += ',';
    csv += String(rawRing[index % RAW_CAPACITY]);
    csv += '\n';
  }
  server.sendHeader("Content-Disposition", "attachment; filename=\"tgam_recent.csv\"");
  server.send(200, "text/csv; charset=utf-8", csv);
}

void handleStatusApi()
{
  String json = "{\"deviceId\":\"" EEG_DEVICE_ID "\",\"bootId\":" + String(bootId) +
                ",\"wifiConnected\":" +
                String(WiFi.status() == WL_CONNECTED ? "true" : "false") +
                ",\"ip\":\"" + WiFi.localIP().toString() + "\",\"rssi\":" +
                String(WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0) +
                ",\"sampleRateHz\":512,\"nextSampleIndex\":" +
                String(nextSampleIndex) + "}";
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json; charset=utf-8", json);
}

void startHttp()
{
  if (httpStarted)
    return;
  server.on("/", []()
            { server.send(200, "text/html; charset=utf-8",
                          "<!doctype html><meta charset=utf-8><title>EEG WiFi</title>"
                          "<h1>ESP32-C3 EEG WiFi</h1><pre id=o>loading...</pre>"
                          "<script>setInterval(async()=>o.textContent=JSON.stringify("
                          "await(await fetch('/api/status')).json(),null,2),500)</script>"); });
  server.on("/api/status", handleStatusApi);
  server.on("/api/eeg", handleEegApi);
  server.on("/api/data", handleLegacyDataApi);
  server.on("/export.csv", handleLegacyCsv);
  server.onNotFound([]()
                    { server.send(404, "text/plain", "Not found"); });
  server.begin();
  httpStarted = true;
  Serial.println();
  Serial.println("========================================");
  Serial.println("EEG WiFi device is ready");
  Serial.print("Device ID: ");
  Serial.println(EEG_DEVICE_ID);
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());
  Serial.print("Base URL: http://");
  Serial.println(WiFi.localIP());
  Serial.print("Status API: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/api/status");
  Serial.print("EEG API: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/api/eeg?after=0&limit=20");
  Serial.println("========================================");
  Serial.println();
  wifiAddressPrinted = true;
}

void serviceWiFi()
{
  if (WiFi.status() == WL_CONNECTED)
  {
    startHttp();
    server.handleClient();
    if (millis() - lastSerialStatusMs >= 5000)
    {
      lastSerialStatusMs = millis();
      Serial.print("EEG_WIFI_STATUS,connected,ssid=");
      Serial.print(WiFi.SSID());
      Serial.print(",ip=");
      Serial.print(WiFi.localIP());
      Serial.print(",baseUrl=http://");
      Serial.print(WiFi.localIP());
      Serial.print(",rssi=");
      Serial.print(WiFi.RSSI());
      Serial.print(",samples=");
      Serial.println(nextSampleIndex);
    }
    return;
  }
  httpStarted = false;
  if (wifiAddressPrinted)
  {
    Serial.println("WiFi disconnected. Waiting to reconnect...");
    wifiAddressPrinted = false;
  }
  if (millis() < nextWifiRetryMs)
    return;
  nextWifiRetryMs = millis() + 5000;
  lastSerialStatusMs = millis();
  Serial.print("Connecting to WiFi: ");
  Serial.println(EEG_WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(EEG_WIFI_SSID, EEG_WIFI_PASSWORD);
}

void setup()
{
  Serial.begin(USB_BAUD);
  delay(1500);
  Serial.println();
  Serial.println("ESP32-C3 EEG WiFi firmware starting...");
  Serial.print("Device ID: ");
  Serial.println(EEG_DEVICE_ID);
  Serial.print("WiFi SSID: ");
  Serial.println(EEG_WIFI_SSID);
  bootId = esp_random();
  TGAMSerial.setRxBufferSize(4096);
  TGAMSerial.begin(TGAM_BAUD, SERIAL_8N1, TGAM_RX_PIN, TGAM_TX_PIN);
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  Serial.println("Connecting to WiFi...");
  WiFi.begin(EEG_WIFI_SSID, EEG_WIFI_PASSWORD);
}

void loop()
{
  while (TGAMSerial.available())
    parseByte((uint8_t)TGAMSerial.read());
  serviceWiFi();
}
