// Copyright (C) 2020  Tobias Isenberg (based on examples by unknown and chegewara)

// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.

// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.


#include "BLEDevice.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <NTPClient.h>        // to sync the time
#include <time.h>

// server and MQTT credentials
//#include "credentials.h"
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "enter_password"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID     "Some Network"
#endif
#ifndef MQTT_HOST
#define MQTT_HOST     "192.168.1.1"
#endif
#ifndef MQTT_PORT
#define MQTT_PORT     "1883"
#endif

// MQTT Server, Wifi SSID & PW, time zone
const char* mqtt_server = MQTT_HOST;
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;
const char* mqtt_data_topic =   "sensors/oximeter/data";
const char* mqtt_time_topic =   "sensors/oximeter/starttime";
const char* mqtt_status_topic = "sensors/oximeter/status";
const char* mqtt_bpm_topic =    "sensors/oximeter/bpm";
const char* mqtt_spo2_topic =   "sensors/oximeter/spo2";
const char* mqtt_alive_topic =  "sensors/oximeter/keepalive";
const char* time_zone_string =  "CET-1CEST,M3.5.0/2,M10.5.0/3"; // Posix TZ string for Europe, including DST 

// The remote service we wish to connect to.
static BLEUUID serviceUUID("49535343-fe7d-4ae5-8fa9-9fafd205e455");
// The characteristic of the remote service we are interested in.
static BLEUUID    charOximeterUUID("49535343-1e4d-4bd9-ba61-23c647249616");
// The address of the target device (needed for connection when the device does not properly advertise services)
static BLEAddress berryMed("00:a0:50:db:83:94");

static boolean doConnect = false;
static boolean connected = false;
static boolean connectionStarted = false;
static boolean doScan = false;
static BLERemoteCharacteristic* pRemoteCharacteristicOximeter;
static BLEAdvertisedDevice* myDevice;
static BLEClient* pClient;
static unsigned int messageCounter = 0;
static unsigned int connectionTimeMs = 0;

const unsigned int numberOfBuffers = 4; // how many buffers to keep, has to be at least 2
const unsigned int secondsPerMqttMessage = 15; // how many seconds worth of data should be send in a packet
const unsigned int bufferSize = (3 * 4 + 4) * 25 * secondsPerMqttMessage; // 3 data bytes, 4 in a notification, plus 4 bytes (32bit) ms time stamp, times 25 notifications per second, times N seconds
const unsigned int bufferSizeMultiple = bufferSize * numberOfBuffers; // the size of both buffers together
uint8_t dataBuffer[bufferSizeMultiple]; // the actual full buffer
unsigned int activeBufferPointer = 0; // the current pointer in the active buffer
unsigned int activeBuffer = 0;        // the pointer to the active buffer
unsigned int bufferToPostNext = 0;    // the pointer to the buffer that needs to be posted to MQTT next
boolean buffersToPost[numberOfBuffers] = {false}; // the array that records which buffers still need to be posted to MQTT
uint32_t timeStampNotification = 0;
uint8_t currentBpm = 0;
uint8_t currentSpo2 = 0;
static boolean sendNewConnectionMessage = false;

WiFiClient espClient;
PubSubClient mqttClient(espClient); //lib required for mqtt

#define DEBUG
#ifdef DEBUG
  #define DEBUG_PRINT(x)    Serial.print(x)
  #define DEBUG_PRINTLN(x)  Serial.println(x)
#else
  #define DEBUG_PRINT(x)
  #define DEBUG_PRINTLN(x)
#endif

////////////////////////////////////////////////////////////////////////////////////
/// time management functions //////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////

time_t timeOffset = 0;

String getCurrentDateTime() {
  time_t timeStructure;
  time(&timeStructure);
  timeStructure = timeStructure + timeOffset;
  char buff[21];
  strftime(buff, 21, "%d.%m.%Y, %H:%M:%S", localtime(&timeStructure));
  return String(buff);
}

String getCurrentDateTimeShort() {
  time_t timeStructure;
  time(&timeStructure);
  timeStructure = timeStructure + timeOffset;
  char buff[21];
  strftime(buff, 21, "%d.%m. %H:%M", localtime(&timeStructure));
  return String(buff);
}

void syncTimeWithNTP() {
  WiFiUDP ntpUDP;
  NTPClient timeClient(ntpUDP, "europe.pool.ntp.org", 0, 60000);

  int counter = 0; // do this sync 10 times max in a row
  timeOffset = 0;
  timeClient.begin();
  while ((timeOffset == 0) && (counter < 10)) {
    DEBUG_PRINTLN("Trying NTP sync.");
    counter++;
    time_t currentTime;
    time(&currentTime);
    timeClient.update();
    time_t epochTime = timeClient.getEpochTime();
    if (epochTime < 1000) {
      // ntp update was not successful, let's do that again after a wait of 1s
      timeOffset = 0;
      delay(1000);
    }
    else {
      DEBUG_PRINTLN("NTP sync successful.");
      // no time offsets, we keep time in UTC, time zones interpreted by localtime() and using the TZ setting below in setup()
      timeOffset = epochTime - currentTime;
      DEBUG_PRINT("It is currently ");
      DEBUG_PRINT(getCurrentDateTime());
      DEBUG_PRINTLN(" local time.");
    }
  }
}

////////////////////////////////////////////////////////////////////////////////////
/// BLE helper functions ///////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////

static void notifyCallback(
  BLERemoteCharacteristic* pBLERemoteCharacteristic,
  uint8_t* pData,
  size_t length,
  bool isNotify) {
    // this notification comes about 24--25 times a second
    // each notification has 3 measurement sets
    // so we get about 72--75 measurements per second (50--70ms advertised)
    // i.e. one every 13ms or so
    
//    Serial.print("Notify callback for characteristic ");
//    Serial.print(pBLERemoteCharacteristic->getUUID().toString().c_str());
//    Serial.print(" of data length ");
//    Serial.println(length);
//    Serial.print("data (HEX): ");
//    for (int i = 0; i < length; i++) {
//      Serial.print(pData[i],HEX);
//      Serial.print(" ");
//    }
//    Serial.println();

    // save data to buffer
    int packetCount = length / 5;
    if (packetCount != 4) DEBUG_PRINTLN("Incorrect packet length!!!");
    else {
      timeStampNotification = millis();
      unsigned int bufferPointer = activeBuffer * bufferSize + activeBufferPointer;
      dataBuffer[bufferPointer] = (uint8_t)(timeStampNotification >> 24); bufferPointer++;
      dataBuffer[bufferPointer] = (uint8_t)((timeStampNotification & 0xffffff) >> 16); bufferPointer++;
      dataBuffer[bufferPointer] = (uint8_t)((timeStampNotification & 0xffff) >> 8); bufferPointer++;
      dataBuffer[bufferPointer] = (uint8_t)(timeStampNotification & 0xff); bufferPointer++;
      for (int i = 0; i < packetCount; i++) {
        int basisPointer = i*5;
        dataBuffer[bufferPointer] = pData[basisPointer + 1]; bufferPointer++; // PPG
        dataBuffer[bufferPointer] = pData[basisPointer + 3]; bufferPointer++; // BPM
        dataBuffer[bufferPointer] = pData[basisPointer + 4]; bufferPointer++; // SPO2
      }
      activeBufferPointer = bufferPointer - activeBuffer * bufferSize;
      if (activeBufferPointer >= bufferSize) {
        if (activeBufferPointer > bufferSize) DEBUG_PRINTLN("Incorrect buffer counter when buffer full!!!");
        activeBufferPointer = 0;
        buffersToPost[activeBuffer] = true; // mark that the current buffer is ready to be published to MQTT
        activeBuffer = (activeBuffer + 1) % numberOfBuffers; // record the future data into the next buffer
      }
      // the first values from the notification are enough
      currentBpm =  pData[3];
      currentSpo2 = pData[4];
    }

//#ifdef DEBUG
//    // readable values 
//    char output[65];
//    for (int i = 0; i < length / 5; i++) {
//      uint8_t value0 = pData[i*5 + 0]; // this value is unclear; is around 134--135,
//      // it is once 198, 199 or 200 for the first ppg value below the local maximum
//      uint8_t ppg = pData[i*5 + 1]; // this seems to be the absoption value (pulse oximeter plethysmographic trace, PPG)
//      uint8_t ppg_7 = pData[i*5 + 2]; // this seems to be the PPG value, devided by 7 and rounded to an integer
//      uint8_t bpm = pData[i*5 + 3];
//      uint8_t spo2 = pData[i*5 + 4];
//      sprintf(output, "V1: %3u (was 135); PPG: %3u; PPG/7: %3u; BPM: %3u; SPO2: %2u", value0, ppg, ppg_7, bpm, spo2);
//      DEBUG_PRINTLN(output);
//    }
//#endif

//    // output for use in CSV-based analysis (Excel etc.)
//    for (int i = 0; i < length / 5; i++) {
//      uint8_t value1 = pData[i*5 + 1];
//      uint8_t value2 = pData[i*5 + 2];
//      uint8_t bpm = pData[i*5 + 3];
//      uint8_t spo2 = pData[i*5 + 4];
//      Serial.print(value1,DEC);
//      Serial.print(",");
//      Serial.print(value2,DEC);
//      Serial.print(",");
//      Serial.print(bpm,DEC);
//      Serial.print(",");
//      Serial.print(spo2,DEC);
//      Serial.println("");
//    }

  messageCounter += 1;
}

class MyClientCallback : public BLEClientCallbacks {
  void onConnect(BLEClient* pclient) {
    DEBUG_PRINTLN("BLE Connected");
    if (mqttClient.connected()) {
      mqttClient.publish(mqtt_status_topic, "Connected to BLE device.");
    }
  }

  void onDisconnect(BLEClient* pclient) {
    connectionStarted = false;
    connected = false;
    DEBUG_PRINTLN("BLE Disconnected");
    if (mqttClient.connected()) {
      mqttClient.publish(mqtt_status_topic, "Disconnected from BLE device.");
    }

    // reset our buffer and pointer management
    activeBufferPointer = 0; // reset the current pointer in the active buffer
    activeBuffer = 0;        // reset the pointer to the active buffer
    bufferToPostNext = 0;    // reset the pointer to the buffer that needs to be posted to MQTT next
    for (int i = 0; i < numberOfBuffers; i++) buffersToPost[i] = false; // reset the array that records which buffers still need to be posted to MQTT
  }
};

bool connectToServer() {
  connectionStarted = true;
  DEBUG_PRINT("Forming a connection to ");
  DEBUG_PRINTLN(myDevice->getAddress().toString().c_str());
  
  if (mqttClient.connected()) {
    String message = String("Connecting to BLE device ") + String(myDevice->getAddress().toString().c_str());
    mqttClient.publish(mqtt_status_topic, message.c_str());
  }

  // Connect to the remove BLE Server.
  boolean connectionSuccessful = pClient->connect(myDevice);  // if you pass BLEAdvertisedDevice instead of address, it will be recognized type of peer device address (public or private)
  DEBUG_PRINTLN(" - Connected to server");
  if ((!connectionStarted) || (!connectionSuccessful)) {
    DEBUG_PRINTLN(" - Got a disconnect before we could complete the connection or connection was not successful");
    return false;
  }

  // Obtain a reference to the service we are after in the remote BLE server.
  BLERemoteService* pRemoteService = pClient->getService(serviceUUID);
  if (pRemoteService == nullptr) {
    DEBUG_PRINT("Failed to find our service UUID: ");
    DEBUG_PRINTLN(serviceUUID.toString().c_str());
    pClient->disconnect();
    return false;
  }
  DEBUG_PRINTLN(" - Found our service");

  // initiate the sending of the new time connection stamp and reset the buffer pointers for the new trace
  sendNewConnectionMessage = true;
  activeBufferPointer = 0; // reset the current pointer in the active buffer
  activeBuffer = 0;        // reset the pointer to the active buffer
  bufferToPostNext = 0;    // reset the pointer to the buffer that needs to be posted to MQTT next
  for (int i = 0; i < numberOfBuffers; i++) buffersToPost[i] = false; // reset the array that records which buffers still need to be posted to MQTT

  // Obtain a reference to the characteristic in the service of the remote BLE server.
  pRemoteCharacteristicOximeter = pRemoteService->getCharacteristic(charOximeterUUID);
  if (pRemoteCharacteristicOximeter == nullptr) {
    DEBUG_PRINT("Failed to find our characteristic UUID: ");
    DEBUG_PRINTLN(charOximeterUUID.toString().c_str());
    pClient->disconnect();
    return false;
  }
  DEBUG_PRINT(" - Found our characteristic ");
  DEBUG_PRINTLN(charOximeterUUID.toString().c_str());

  // Read the value of the characteristic.
  if(pRemoteCharacteristicOximeter->canRead()) {
    DEBUG_PRINTLN(" - Our characteristic can be read.");
//    std::string value = pRemoteCharacteristicOximeter->readValue();
//#ifdef DEBUG
//    byte buf[64]= {0};
//    memcpy(buf,value.c_str(),value.length());
//    Serial.print("The characteristic value was: ");
//    for (int i = 0; i < value.length(); i++) {
//      Serial.print(buf[i],HEX);
//      Serial.print(" ");
//    }
//    Serial.println();
//#endif
  }
  else {
    DEBUG_PRINTLN(" - Our characteristic cannot be read.");
  }

  if(pRemoteCharacteristicOximeter->canNotify()) {
    DEBUG_PRINTLN(" - Our characteristic can notify us, registering notification callback.");
    pRemoteCharacteristicOximeter->registerForNotify(notifyCallback, true);
    
    // needed to actually start the notifications for the BerryMed oximeter:
    const uint8_t notificationOn[] = {0x1, 0x0};
    pRemoteCharacteristicOximeter->getDescriptor(BLEUUID((uint16_t)0x2902))->writeValue((uint8_t*)notificationOn, 2, true);
  }
  else {
    DEBUG_PRINTLN(" - Our characteristic cannot notify us.");
  }

  if (pRemoteCharacteristicOximeter->canIndicate() == true) {
    DEBUG_PRINTLN(" - Our characteristic can indicate.");
  } else {
    DEBUG_PRINTLN(" - Our characteristic cannot indicate.");
  }

  connected = true;

  if (mqttClient.connected()) {
    String message = String("Connection to BLE device ") + String(myDevice->getAddress().toString().c_str()) + String(" completed");
    mqttClient.publish(mqtt_status_topic, message.c_str());
  }
  
  return true;
}
/**
 * Scan for BLE servers and find the first one that advertises the service we are looking for.
 */
class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
 /**
   * Called for each advertising BLE server.
   */
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    DEBUG_PRINT("\nBLE Advertised Device found: ");
    DEBUG_PRINTLN(advertisedDevice.toString().c_str());

    DEBUG_PRINT("Address: ");
    DEBUG_PRINTLN(advertisedDevice.getAddress().toString().c_str());
    if (advertisedDevice.haveServiceUUID()) {
      DEBUG_PRINTLN("Device has Service UUID");
      if (advertisedDevice.isAdvertisingService(serviceUUID)) {DEBUG_PRINTLN("Device is advertising our Service UUID");}
      else {DEBUG_PRINTLN("Device is not advertising our Service UUID");}
    }
    else {DEBUG_PRINTLN("Device does not have Service UUID");}
    
    // We have found a device, let us now see if it contains the service we are looking for.
    if ((advertisedDevice.haveServiceUUID() && advertisedDevice.isAdvertisingService(serviceUUID)) || (advertisedDevice.getAddress().equals(berryMed))) {
      DEBUG_PRINTLN("Found a device that contains the service we are looking for.");
      BLEDevice::getScan()->stop();
      myDevice = new BLEAdvertisedDevice(advertisedDevice);
      doConnect = true;
      doScan = true;

    } // Found our server
  } // onResult
}; // MyAdvertisedDeviceCallbacks


////////////////////////////////////////////////////////////////////////////////////
/// MQTT helper functions //////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////

void mqttMessageCallback(char* topic, byte* payload, unsigned int length) { //callback includes topic and payload (from which (topic) the payload is comming)
  DEBUG_PRINT("Message arrived [");
  DEBUG_PRINT(topic);
  DEBUG_PRINT("] ");
  for (int i = 0; i < length; i++) {
    DEBUG_PRINT((char)payload[i]);
  }
  DEBUG_PRINTLN();
}

void mqttReconnect() {
  String clientID = "Oximeter_"; // 13 chars
  clientID += WiFi.macAddress(); // 17 chars

  delay(100); // wait just a bit before attempting to reconnect, in case a reconnect is going on and is being completed

  while (!mqttClient.connected()) {
    DEBUG_PRINTLN("Attempting MQTT connection ...");
    if (mqttClient.connect(clientID.c_str())) {
      DEBUG_PRINTLN("connected");
      // Once connected, publish an announcement...
      mqttClient.publish(mqtt_status_topic, "Controller reconnected to MQTT");
    } else {
      DEBUG_PRINT("failed, rc=");
      DEBUG_PRINT(mqttClient.state());
      DEBUG_PRINTLN(" try again in 5 seconds");
      // Wait 5 seconds before retrying
      delay(5000);
    }
  }
}

void mqttConnect() {
  String clientID = "Oximeter_"; // 13 chars
  clientID += WiFi.macAddress();//17 chars

  if (mqttClient.connect(clientID.c_str())) { // ESP will connect to mqtt broker with clientID
    DEBUG_PRINTLN("connected to MQTT");
    // Once connected, publish an announcement ...
    mqttClient.publish(mqtt_status_topic, "Controller connected to MQTT");
  }
  else {
    mqttReconnect();
  }
}

////////////////////////////////////////////////////////////////////////////////////
/// Setup //////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////

void setup() {
  Serial.begin(115200);
  DEBUG_PRINTLN("");
  delay(1000); // wait a bit for things to stabelize (otherwise first wifi connection is not successful)

  WiFi.persistent(false);
  WiFi.disconnect();
  WiFi.mode(WIFI_OFF);
  WiFi.mode(WIFI_STA);
  DEBUG_PRINT("Connecting to ");
  DEBUG_PRINTLN(ssid);
  WiFi.begin(ssid, password);
 
  // Wait for WiFi
  int wifiCounter = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    DEBUG_PRINT(".");
    wifiCounter += 1;
    if (wifiCounter > 10) WiFi.begin(ssid, password);
    if (wifiCounter > 30) ESP.restart();
  }
  DEBUG_PRINTLN("");
  DEBUG_PRINT("Wifi connected, IP-Adress: ");
  DEBUG_PRINTLN(WiFi.localIP());

  mqttClient.setServer(mqtt_server, atoi(MQTT_PORT)); //connecting to mqtt server
  mqttClient.setCallback(mqttMessageCallback);
  mqttClient.setBufferSize(MQTT_MAX_PACKET_SIZE + bufferSize); // otherwise our long data messages do not get sent
  mqttConnect();
  DEBUG_PRINTLN("MQTT connected.");
  
  // set time zone
  setenv("TZ", time_zone_string, 1);
  tzset();

  syncTimeWithNTP();
  
  connectionTimeMs = millis();
  
  DEBUG_PRINTLN("Starting Arduino BLE Client application...");
  BLEDevice::init("");
  DEBUG_PRINTLN(" - Device initialized");
  pClient  = BLEDevice::createClient();
  DEBUG_PRINTLN(" - Created client");
  pClient->setClientCallbacks(new MyClientCallback());
  DEBUG_PRINTLN(" - Client callbacks set");
    
  // Retrieve a Scanner and set the callback we want to use to be informed when we
  // have detected a new device.  Specify that we want active scanning and start the
  // scan to run for 5 seconds.
  BLEScan* pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setInterval(1349);
  pBLEScan->setWindow(449);
  pBLEScan->setActiveScan(true);
  pBLEScan->start(5, false);
} // End of setup.


////////////////////////////////////////////////////////////////////////////////////
/// Loop ///////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////

void loop() {
  // If the flag "doConnect" is true then we have scanned for and found the desired
  // BLE Server with which we wish to connect.  Now we connect to it.  Once we are 
  // connected we set the connected flag to be true.
  if (doConnect == true) {
    if (connectToServer()) {
      DEBUG_PRINTLN("We are now connected to the BLE Server.");
    } else {
      DEBUG_PRINTLN("We have failed to connect to the server; there is nothing more we will do.");
    }
    doConnect = false;
  }

  // If we are connected to a peer BLE Server, update the characteristic each time we are reached
  // with the current time since boot.
  if (connected) {
//    DEBUG_PRINT("Notifications during the last second: ");
//    DEBUG_PRINTLN(messageCounter);
    messageCounter = 0;
  }
  else {
    if (doScan) {
      BLEDevice::getScan()->start(5, false);  // scan for 5 seconds
    }
    else { // enable connects if no device was found on first boot
      if (millis() > connectionTimeMs + 6000) {
        DEBUG_PRINTLN("Enabling scanning.");
        doScan = true;
      }
    }
  }

  // reconnect to MQTT if needed
  if (!(mqttClient.connected())) mqttReconnect();

  if ( (sendNewConnectionMessage) && (mqttClient.connected()) ) {
    DEBUG_PRINTLN("Starting new trace, publishing new Oximeter connection timestamp to MQTT.");
    unsigned int newConnectionTimeMs = millis();
    boolean result = mqttClient.publish(mqtt_time_topic, (String(newConnectionTimeMs) + String(" = ") + getCurrentDateTime()).c_str());
//    DEBUG_PRINT("Result of Timestamp message was: ");
//    DEBUG_PRINTLN(result);

    sendNewConnectionMessage = false;
  }

//unsigned int bufferToPostNext = 0;    // the pointer to the buffer that needs to be posted to MQTT next
//boolean buffersToPost = {false};      // the array that records which buffers still need to be posted to MQTT


  if ( (buffersToPost[bufferToPostNext]) && (mqttClient.connected()) ) {
    DEBUG_PRINT("\nPosting data to MQTT from buffer ");
    DEBUG_PRINTLN(bufferToPostNext);
    uint32_t timeStampBeforePublish = millis();
    boolean result = mqttClient.publish(mqtt_data_topic, &dataBuffer[bufferToPostNext * bufferSize], bufferSize);
    uint32_t timeStampAfterPublish = millis();
    DEBUG_PRINT("Posting data to MQTT took ");
    DEBUG_PRINT(timeStampAfterPublish - timeStampBeforePublish);
    DEBUG_PRINTLN("ms.");
    DEBUG_PRINT("Result of data message was: ");
    DEBUG_PRINTLN(result);
//    DEBUG_PRINT("MQTT buffer size is: ");
//    DEBUG_PRINTLN(mqttClient.getBufferSize());
//    DEBUG_PRINT("Posted buffer size: ");
//    DEBUG_PRINT(bufferSize);
//    DEBUG_PRINTLN(" bytes.");

    if (result) {
      char outputBuffer[25];
      sprintf(outputBuffer, "posted to buffer %i", bufferToPostNext);
      mqttClient.publish(mqtt_status_topic, outputBuffer);
//      DEBUG_PRINT("Result of status message was: ");
//      DEBUG_PRINTLN(result);
      if (currentSpo2 != 127) {
        char outputBpm[5];
        sprintf(outputBpm, "%u", currentBpm);
        result = mqttClient.publish(mqtt_bpm_topic, outputBpm);
//        DEBUG_PRINT("Result of BPM message was: ");
//        DEBUG_PRINTLN(result);
        char outputSpo2[5];
        sprintf(outputSpo2, "%u", currentSpo2);
        result = mqttClient.publish(mqtt_spo2_topic, outputSpo2);
//        DEBUG_PRINT("Result of SPO2 message was: ");
//        DEBUG_PRINTLN(result);
//        DEBUG_PRINT("Check if MQTT server is connected: ");
//        DEBUG_PRINTLN(mqttClient.connected());
      }

      // record that we were successful
      buffersToPost[bufferToPostNext] = false;
      // set the pointer to the next buffer to publish
      bufferToPostNext = (bufferToPostNext + 1) % numberOfBuffers;
    }
  }

  // publish at least one message per second to keep the MQTT connection alive
  if (mqttClient.connected()) {
    char runtimeMs[15];
    sprintf(runtimeMs, "%u", millis());
//    DEBUG_PRINT("Publishing alive message: ");
//    DEBUG_PRINTLN(runtimeMs);
    mqttClient.publish(mqtt_alive_topic, runtimeMs);
  }
  
  delay(1000); // Delay a second between loops.
} // End of loop
