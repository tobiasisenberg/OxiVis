#!/usr/bin/python3 -u

# Copyright (C) 2020  Tobias Isenberg

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import paho.mqtt.client as mqttClient
import os
from datetime import datetime

broker_address= "192.168.1.1"       # Broker address
port = 1883                         # Broker port
topicData = "sensors/oximeter/data"
topicStatus = "sensors/oximeter/status"
topicStarttime = "sensors/oximeter/starttime"
filenameLocationBasis = "/var/log/openhab2/oximeter-"
if (os.name == "nt"): # FIXME: just for tests, sav files locally when running windows
    filenameLocationBasis = "./oximeter-"
filenameLocationFull = ""

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(str(datetime.now()) + " Connected to broker")
        global Connected                # Use global variable
        Connected = True                # Signal connection

    else:
        print(str(datetime.now()) + " Connection failed")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(str(datetime.now()) + " Unexpected disconnection.")

def on_message(client, userdata, message):
    # print(str(datetime.now()) + " Message received for topic "  + str(message.topic))
    global topicStarttime
    global filenameLocationBasis
    global filenameLocationFull

    if (message.topic == topicStatus):
        print(str(datetime.now()) + " Status: " + str(message.payload, 'utf-8', 'ignore'))

    if (message.topic == topicStarttime):
        timestamp = str(message.payload, 'utf-8', 'ignore')
        startTimeMs = timestamp.split(" = ")[0]
        startTimeDateTime = timestamp.split(" = ")[1]
        startTimeDate = startTimeDateTime.split(", ")[0]
        startTimeYear = startTimeDate.split(".")[2]
        startTimeMonth = startTimeDate.split(".")[1]
        startTimeDay = startTimeDate.split(".")[0]
        startTimeTime = startTimeDateTime.split(", ")[1].replace(":", "")

        filenameLocationFull = filenameLocationBasis + startTimeYear + startTimeMonth + startTimeDay + "-" + startTimeTime + "-" + startTimeMs + ".csv"
        print(str(datetime.now()) + " Filename: " + filenameLocationFull + "")

        with open(filenameLocationFull,'w') as f:
            f.write("PPG,BPM,SPO2,MS-timestamp,buffer-end-marker\n")
            f.close()

    if (message.topic == topicData):
        print(str(datetime.now()) + " Appending data to file "  + filenameLocationFull)
        with open(filenameLocationFull,'a') as f:
            counter = 0
            counterTotal = 0
            msTimestamp = 1<<31
            ppg = 0
            bpm = 0
            spo2 = 0
            bufferIndicator = ""
            messageSize = len(message.payload)
            for byte in message.payload:
                counterTotal += 1
                if (counterTotal == messageSize): bufferIndicator = "127"
                else: bufferIndicator = "0"
                if (counter == 0): msTimestamp = byte<<24
                if (counter == 1): msTimestamp += byte<<16
                if (counter == 2): msTimestamp += byte<<8
                if (counter == 3): msTimestamp += byte
                if (counter > 3): 
                    if ((counter - 4) % 3 == 0): ppg = byte
                    if ((counter - 4) % 3 == 1): bpm = byte
                    if ((counter - 4) % 3 == 2): 
                        spo2 = byte
                        if (spo2 == 127):
                            f.write(str(ppg) + ",,," + str(msTimestamp) + "," + bufferIndicator + "\n")
                        else:
                            f.write(str(ppg) + "," + str(bpm) + "," + str(spo2) + "," + str(msTimestamp) + "," + bufferIndicator + "\n")
                counter += 1
                counter = counter % 16
            f.close()
        print(str(datetime.now()) + " Appending data completed after " + str(counterTotal) + " bytes")

    # with open('/home/pi/test.txt','a+') as f:
    #      f.write("Message received: "  + message.payload + "\n")

Connected = False   #global variable for the state of the connection

client = mqttClient.Client("Python-Oximeter-Data-Recorder-" + os.name) # create new instance
client.on_connect = on_connect                              # attach function to callback
client.on_disconnect = on_disconnect                        # attach function to callback
client.on_message = on_message                              # attach function to callback

print(str(datetime.now()) + " Connecting")
client.connect(broker_address,port,60)                      # connect
print(str(datetime.now()) + " Subscribing")
client.subscribe(topicData)                                 # subscribe to data topic
client.subscribe(topicStarttime)                            # subscribe to starttime topic
client.subscribe(topicStatus)                               # subscribe to status topic
client.loop_forever()                                       # then keep listening forever