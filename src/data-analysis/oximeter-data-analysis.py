#!/usr/bin/python3

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

import csv
import math
from datetime import datetime
from datetime import timedelta
import io
from plotly.offline import iplot, init_notebook_mode
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import plotly.offline as py
import plotly.graph_objs as go
import plotly.io as pio
from PyPDF2 import PdfFileMerger
import sys
import os

if (len(sys.argv) < 2):
    print("Too few arguments. Please call script with a name and one or more data files. Examples:")
    print(os.path.basename(__file__) + " \"Test test\" oximeter-20200706-002654-29871.csv")
    print(os.path.basename(__file__) + " \"Test test\" oximeter-20200706-002654-29871.csv oximeter-20200706-003426-481146.csv")
    sys.exit()

filenameExtension = sys.argv[1]
print("filenameExtension: " + filenameExtension)
dataFileNames = sys.argv[2:]
dataFileName = dataFileNames[0]
oximeterData = []
emptyEntry = {}
needToRemoveInitial127BPM = True
bpmMax = 0
bpmMin = 255
spo2Max = 0
spo2Min = 255
ppgMax = 0
ppgMin = 255

# parse main data file
with open(dataFileName, 'r', encoding='utf-8') as csvfile:
    print("Parsing main input file " + dataFileName)
    dataReader = csv.reader(csvfile, delimiter=',', quotechar='"')
    headers = next(dataReader)[0:]
    for row in dataReader:
        # newEntry = {key: str(value) for key, value in zip(headers, row[0:])}
        newEntry = {}
        for key, value in zip(headers, row[0:]):
            if value == '':
                newEntry[key] = None
            else:
                newEntry[key] = int(value)
        # remove the initial 127 values for BPM
        if (newEntry["BPM"] != None) and (newEntry["BPM"] != 127): needToRemoveInitial127BPM = False
        if (needToRemoveInitial127BPM): newEntry["BPM"] = None
        # add the value to the list
        oximeterData.append(newEntry)
        #  determine the ranges
        if (newEntry["BPM"] != None):
            bpm = newEntry["BPM"]
            if (bpm > bpmMax): bpmMax = bpm
            if (bpm < bpmMin): bpmMin = bpm
        if (newEntry["SPO2"] != None):
            spo2 = newEntry["SPO2"]
            if (spo2 > spo2Max): spo2Max = spo2
            if (spo2 < spo2Min): spo2Min = spo2
        if (newEntry["PPG"] != None):
            ppg = newEntry["PPG"]
            if (ppg > ppgMax): ppgMax = ppg
            if (ppg < ppgMin): ppgMin = ppg

    csvfile.close()
    emptyEntry = {key: None for key, value in zip(headers, row[0:])}

numberOfSamples = len(oximeterData)
startTimeMs = int(oximeterData[0]["MS-timestamp"])
endTimeMs = int(oximeterData[numberOfSamples - 1]["MS-timestamp"])
durationMs = endTimeMs - startTimeMs
samplesPerMs = numberOfSamples / durationMs
print("samples per ms (first file): " + "{:.5f}".format(samplesPerMs))

# parse additional data files
for additionalFileName in dataFileNames[1:]:
    print("Parsing additional input file " + additionalFileName)

    # first, actually parse the file
    needToRemoveInitial127BPM = True
    additionalOximeterData = []
    with open(additionalFileName, 'r', encoding='utf-8') as csvfile:
        dataReader = csv.reader(csvfile, delimiter=',', quotechar='"')
        headers = next(dataReader)[0:]
        for row in dataReader:
            # newEntry = {key: str(value) for key, value in zip(headers, row[0:])}
            newEntry = {}
            for key, value in zip(headers, row[0:]):
                if value == '':
                    newEntry[key] = None
                else:
                    newEntry[key] = int(value)
            # remove the initial 127 values for BPM
            if (newEntry["BPM"] != None) and (newEntry["BPM"] != 127): needToRemoveInitial127BPM = False
            if (needToRemoveInitial127BPM): newEntry["BPM"] = None
            # add the value to the list
            additionalOximeterData.append(newEntry)
            #  determine the ranges
            if (newEntry["BPM"] != None):
                bpm = newEntry["BPM"]
                if (bpm > bpmMax): bpmMax = bpm
                if (bpm < bpmMin): bpmMin = bpm
            if (newEntry["SPO2"] != None):
                spo2 = newEntry["SPO2"]
                if (spo2 > spo2Max): spo2Max = spo2
                if (spo2 < spo2Min): spo2Min = spo2
            if (newEntry["PPG"] != None):
                ppg = newEntry["PPG"]
                if (ppg > ppgMax): ppgMax = ppg
                if (ppg < ppgMin): ppgMin = ppg

        csvfile.close()
    
    # determine how many empty entries we need as a buffer to maintain the flow of time
    startTimeAdditionalMs = int(additionalOximeterData[0]["MS-timestamp"])
    gapDurationMs = startTimeAdditionalMs - endTimeMs
    print("The interruption lasted " + str(gapDurationMs) + " ms.")
    neededNumberOfSamples = round(gapDurationMs * samplesPerMs)
    print("We thus add " + str(neededNumberOfSamples) + " empty samples in the break.")
    endTimeMs = int(additionalOximeterData[len(additionalOximeterData) - 1]["MS-timestamp"])
    durationMs = endTimeMs - startTimeMs
    numberOfSamples = numberOfSamples + neededNumberOfSamples + len(additionalOximeterData)
    samplesPerMs = numberOfSamples / durationMs
    # print("samples per ms (break): " + "{:.5f}".format(neededNumberOfSamples / gapDurationMs))
    # print("samples per ms (additional): " + "{:.5f}".format(len(additionalOximeterData) / (endTimeMs - int(additionalOximeterData[0]["MS-timestamp"]))))
    print("samples per ms (updated): " + "{:.5f}".format(samplesPerMs))

    # then add the buffer to the main data list
    for i in range(0, neededNumberOfSamples):
        oximeterData.append(emptyEntry)

    # then add the new entries to the main data list
    for entry in additionalOximeterData:
        oximeterData.append(entry)

# determine the numbers for the combined file
numberOfSamples = len(oximeterData)
startDate = dataFileName.split(".")[0].split("-")[1]
startTimeStamp = dataFileName.split(".")[0].split("-")[2]
startTimeStampMs = int(dataFileName.split(".")[0].split("-")[3])
startTimeMs = int(oximeterData[0]["MS-timestamp"])
endTimeMs = int(oximeterData[numberOfSamples - 1]["MS-timestamp"])
durationMs = endTimeMs - startTimeMs
durationS = durationMs / 1000
durationMin = durationS / 60
durationH = durationMin / 60
samplesPerSecond = numberOfSamples / durationS
startDateFormatted = startDate[:4] + '/' + startDate[4:6]+ '/' + startDate[6:8]
startTimeStampFormatted = startTimeStamp[:2] + ':' + startTimeStamp[2:4]+ ':' + startTimeStamp[4:6]
startOffsetMs = startTimeMs - startTimeStampMs
startDateTime = datetime.strptime(startDateFormatted + " " + startTimeStampFormatted, '%Y/%m/%d %H:%M:%S') + timedelta(milliseconds=startOffsetMs)  
endDateTime = startDateTime + timedelta(milliseconds=durationMs)
df = pd.DataFrame(oximeterData)

print("read " + str(numberOfSamples) + " samples")
print("start date: " + startDate)
print("start date formatted: " + startDateFormatted)
print("start timestamp: " + startTimeStamp)
print("start timestamp formatted: " + startTimeStampFormatted)
print("start timestamp datetime: " + startDateTime.strftime("%m/%d/%Y, %H:%M:%S"))
print("start timestamp (ms): " + str(startTimeStampMs))
print("start time (ms): " + str(startTimeMs))
print("end time (ms): " + str(endTimeMs))
print("duration (ms): " + str(durationMs))
print("duration (s): " + "{:.2f}".format(durationS))
print("duration (min): " + "{:.2f}".format(durationMin))
print("duration (h): " + "{:.2f}".format(durationH))
print("samples per second: " + "{:.5f}".format(samplesPerSecond))
print("max. SpO2: " + str(spo2Max))
print("min. SpO2: " + str(spo2Min))
print("max. BPM: " + str(bpmMax))
print("min. BPM: " + str(bpmMin))
print("max. PPG: " + str(ppgMax))
print("min. PPG: " + str(ppgMin))

# create the PDF output target
merger = PdfFileMerger(strict=False)

# overall title slide
data = []
layout = go.Layout(
    width=2000,
    height=350,
    margin=dict(l=80, r=80, b=40, t=20, pad=4),
    font=dict(color='rgb(0,0,0)', size=50, family='Helvetica'),
    showlegend=False,
    title=dict(text = "Pulse Oximeter Data Trace<br>" +
        "from " + startDateTime.strftime("%Y/%m/%d, %H:%M:%S") + " to " + endDateTime.strftime("%Y/%m/%d, %H:%M:%S"),
        x = 0.5, y = 0.57, xanchor = 'center', yanchor = 'middle'),
    xaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
    yaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
)
fig = go.Figure(data=data, layout=layout)
pdf_file = io.BytesIO()
pio.write_image(fig, pdf_file, 'pdf')
pdf_file.seek(0)
merger.append(pdf_file)

# data summary slide
data = []
layout = go.Layout(
    width=2000,
    height=350,
    margin=dict(l=80, r=80, b=40, t=20, pad=4),
    font=dict(color='rgb(0,0,0)', size=25, family='Helvetica'),
    showlegend=False,
    title=dict(
        text = "oxygen saturation level (SpO₂) value range: " + str(spo2Min) + "%–" + str(spo2Max) + "%" +
            ", mean: {:.1f}".format(df.SPO2.mean(axis = 0)) + "%<br>" +
            "     heart rate (beats per minute, BPM) value range: " + str(bpmMin) + "–" + str(bpmMax) + 
            ", mean: {:.1f}".format(df.BPM.mean(axis = 0)) + "<br>" +
            "photoplethysmograph (PPG) value range: " + str(ppgMin) + "–" + str(ppgMax) + "<br>" +
            "data trace duration: " + 
            "{:.2f}".format(durationH) + "h ＝ " +
            "{:,.2f}".format(durationMin) + "min ＝ " +
            "{:,.2f}".format(durationS) + "s<br>" +
            "samples (incl. empty samples during interruptions): " + "{:,}".format(numberOfSamples) +
            "     samples per second: " + "{:.5f}".format(samplesPerSecond),
        x = 0.5, y = 0.72, xanchor = 'center', yanchor = 'middle'),
    xaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
    yaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
)
fig = go.Figure(data=data, layout=layout)
pdf_file = io.BytesIO()
pio.write_image(fig, pdf_file, 'pdf')
pdf_file.seek(0)
merger.append(pdf_file)

# write the coarse graphs
print("writing very coarse, averaged BPM and SPO2 graphs")
valuesToAverage = 200 # 100 is about 1 second
timeSectionToGraphMin = 60
detailGraphsToWrite = math.ceil(numberOfSamples / samplesPerSecond / 60 / timeSectionToGraphMin)

# title slide
data = []
layout = go.Layout(
    width=2000,
    height=350,
    margin=dict(l=80, r=80, b=40, t=20, pad=4),
    font=dict(color='rgb(0,0,0)', size=40, family='Helvetica'),
    showlegend=False,
    title=dict(text = "Coarse, Averaged SpO₂ and BPM Graphs<br>" +
        "(" + str(valuesToAverage) + " sample averaging window, " + str(timeSectionToGraphMin) + " minutes per graph)",
        x = 0.5, y = 0.57, xanchor = 'center', yanchor = 'middle'),
    xaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
    yaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
)
fig = go.Figure(data=data, layout=layout)
pdf_file = io.BytesIO()
pio.write_image(fig, pdf_file, 'pdf')
pdf_file.seek(0)
merger.append(pdf_file)

# data slides
for detailGraph in range(0, detailGraphsToWrite):
    print("creating graph: " + str(detailGraph+1) + "/" + str(detailGraphsToWrite))
    timeOffsetS = detailGraph * timeSectionToGraphMin * 60
    samplesOffset = round(timeOffsetS * samplesPerSecond)
    # print("samplesOffset: " + str(samplesOffset))
    timeSectionToGraphMs = timeSectionToGraphMin * 60 * 1000
    sampleSizeToGraph = round(numberOfSamples * timeSectionToGraphMs / durationMs)
    # print("samples in subset: " + str(sampleSizeToGraph))

    timeSequence = []
    for i in range(samplesOffset, sampleSizeToGraph + samplesOffset):
        millisecondsTick = timeSectionToGraphMs * i / sampleSizeToGraph
        timeSequence.append(startDateTime + timedelta(milliseconds=millisecondsTick))

    oximeterDataSubset = []
    if (sampleSizeToGraph+samplesOffset <= numberOfSamples): # if we are well before the end, all is fine
        oximeterDataSubset = oximeterData[samplesOffset:sampleSizeToGraph+samplesOffset]
    else: # otherwise we have to make sure that we do not access data that does not exist, and fill it up with empty values
        oximeterDataSubset = oximeterData[samplesOffset:numberOfSamples]
        for i in range(0, sampleSizeToGraph+samplesOffset - numberOfSamples):
            oximeterDataSubset.append(emptyEntry)

    # print("samples in subset: " + str(len(oximeterDataSubset)))
    ppgDataSubset = []
    bpmDataSubset = []
    spo2DataSubset = []
    for i in range(0, sampleSizeToGraph):
        # if oximeterDataSubset[i]['PPG'] == '': ppgDataSubset.append(None)
        # else: ppgDataSubset.append(int(oximeterDataSubset[i]['PPG']))
        bpmDataSubset.append(oximeterDataSubset[i]['BPM'])
        spo2DataSubset.append(oximeterDataSubset[i]['SPO2'])
    
    # print("averaging values")
    dfBpm = pd.DataFrame(bpmDataSubset)
    dfBpm['MA'] = dfBpm.rolling(valuesToAverage, center = True).mean()
    dfSpo2 = pd.DataFrame(spo2DataSubset)
    dfSpo2['MA'] = dfSpo2.rolling(valuesToAverage, center = True).mean()

    # print("preparing plot")
    data = [
        # go.Scatter(
        #     x=timeSequence,
        #     y=bpmDataSubset,
        #     mode='lines',
        #     name='BPM',
        #     line=dict(color='rgb(0,100,80)', width=0.5),
        #     yaxis='y2',
        # ),
        # go.Scatter(
        #     x=timeSequence,
        #     y=spo2DataSubset,
        #     mode='lines',
        #     name='SPO₂',
        #     line=dict(color='rgb(49,130,189)', width=0.5),
        #     yaxis='y1',
        # ),
        go.Scatter(
            x=timeSequence,
            y=dfBpm.MA,
            mode='lines',
            name='BPM',
            line=dict(color='rgb(0,100,80)', width=2),
            yaxis='y2',
        ),
        go.Scatter(
            x=timeSequence,
            y=dfSpo2.MA,
            mode='lines',
            name='SpO₂',
            line=dict(color='rgb(49,130,189)', width=2),
            yaxis='y1',
        ),
    ]
    spo2LowValue = 90
    if (spo2Min < spo2LowValue): spo2LowValue = spo2Min
    bpmLowValue = 55
    if (bpmMin < bpmLowValue): bpmLowValue = bpmMin
    bpmHighValue = 120
    if (bpmMax > bpmHighValue): bpmHighValue = bpmMax
    layout = go.Layout(
        width=2000,
        height=350,
        margin=dict(l=80, r=80, b=40, t=20, pad=4),
        font=dict(color='rgb(0,0,0)', size=25, family='Helvetica'),
        showlegend=False,
        yaxis=dict(title='SpO₂ in % (blue)', range=[spo2LowValue, 100]),
        yaxis2=dict(title='BPM (green)', overlaying='y', side='right', range=[bpmLowValue, bpmHighValue]),
        # legend=dict(x=0.03, y=1.0, font=dict(size=20),bordercolor='rgb(0,0,0)',borderwidth=1),
    )
    # print("creating figure")
    fig = go.Figure(data=data, layout=layout)
    # print("getting stream")
    pdf_file = io.BytesIO()
    # print("writing image")
    pio.write_image(fig, pdf_file, 'pdf')
    # print("seeking")
    pdf_file.seek(0)
    # print("appending PDF")
    merger.append(pdf_file)

# write the coarse graphs
print("writing coarse BPM and SPO2 graphs")
timeSectionToGraphMin = 10
detailGraphsToWrite = math.ceil(numberOfSamples / samplesPerSecond / 60 / timeSectionToGraphMin)

# title slide
data = []
layout = go.Layout(
    width=2000,
    height=350,
    margin=dict(l=80, r=80, b=40, t=20, pad=4),
    font=dict(color='rgb(0,0,0)', size=40, family='Helvetica'),
    showlegend=False,
    title=dict(text = "Coarse SpO₂ and BPM Graphs<br>(" + str(timeSectionToGraphMin) + " minutes per graph)",
        x = 0.5, y = 0.57, xanchor = 'center', yanchor = 'middle'),
    xaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
    yaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
)
fig = go.Figure(data=data, layout=layout)
pdf_file = io.BytesIO()
pio.write_image(fig, pdf_file, 'pdf')
pdf_file.seek(0)
merger.append(pdf_file)

# data slides
for detailGraph in range(0, detailGraphsToWrite):
    print("creating graph: " + str(detailGraph+1) + "/" + str(detailGraphsToWrite))
    timeOffsetS = detailGraph * timeSectionToGraphMin * 60
    samplesOffset = round(timeOffsetS * samplesPerSecond)
    # print("samplesOffset: " + str(samplesOffset))
    timeSectionToGraphMs = timeSectionToGraphMin * 60 * 1000
    sampleSizeToGraph = round(numberOfSamples * timeSectionToGraphMs / durationMs)
    # print("samples in subset: " + str(sampleSizeToGraph))

    timeSequence = []
    for i in range(samplesOffset, sampleSizeToGraph + samplesOffset):
        millisecondsTick = timeSectionToGraphMs * i / sampleSizeToGraph
        timeSequence.append(startDateTime + timedelta(milliseconds=millisecondsTick))

    oximeterDataSubset = []
    if (sampleSizeToGraph+samplesOffset <= numberOfSamples): # if we are well before the end, all is fine
        oximeterDataSubset = oximeterData[samplesOffset:sampleSizeToGraph+samplesOffset]
    else: # otherwise we have to make sure that we do not access data that does not exist, and fill it up with empty values
        oximeterDataSubset = oximeterData[samplesOffset:numberOfSamples]
        for i in range(0, sampleSizeToGraph+samplesOffset - numberOfSamples):
            oximeterDataSubset.append(emptyEntry)

    # print("samples in subset: " + str(len(oximeterDataSubset)))
    ppgDataSubset = []
    bpmDataSubset = []
    spo2DataSubset = []
    for i in range(0, sampleSizeToGraph):
        # if oximeterDataSubset[i]['PPG'] == '': ppgDataSubset.append(None)
        # else: ppgDataSubset.append(int(oximeterDataSubset[i]['PPG']))
        bpmDataSubset.append(oximeterDataSubset[i]['BPM'])
        spo2DataSubset.append(oximeterDataSubset[i]['SPO2'])

    data = [
        go.Scatter(
            x=timeSequence,
            y=bpmDataSubset,
            mode='lines',
            name='BPM',
            line=dict(color='rgb(0,100,80)', width=2),
            yaxis='y2',
        ),
        go.Scatter(
            x=timeSequence,
            y=spo2DataSubset,
            mode='lines',
            name='SpO₂',
            line=dict(color='rgb(49,130,189)', width=2),
            yaxis='y1',
        ),
    ]
    spo2LowValue = 90
    if (spo2Min < spo2LowValue): spo2LowValue = spo2Min
    bpmLowValue = 55
    if (bpmMin < bpmLowValue): bpmLowValue = bpmMin
    bpmHighValue = 120
    if (bpmMax > bpmHighValue): bpmHighValue = bpmMax
    layout = go.Layout(
        width=2000,
        height=350,
        margin=dict(l=80, r=80, b=40, t=20, pad=4),
        font=dict(color='rgb(0,0,0)', size=25, family='Helvetica'),
        showlegend=False,
        yaxis=dict(title='SpO₂ in % (blue)', range=[spo2LowValue, 100]),
        yaxis2=dict(title='BPM (green)', overlaying='y', side='right', range=[bpmLowValue, bpmHighValue]),
        # legend=dict(x=0.03, y=1.0, font=dict(size=20),bordercolor='rgb(0,0,0)',borderwidth=1),
    )
    fig = go.Figure(data=data, layout=layout)
    pdf_file = io.BytesIO()
    pio.write_image(fig, pdf_file, 'pdf')
    pdf_file.seek(0)
    merger.append(pdf_file)

# write the detailed graphs
print("writing detailed PPG, BPM, and SPO2 graphs")
timeSectionToGraphMin = 1
detailGraphsToWrite = math.ceil(numberOfSamples / samplesPerSecond / 60 / timeSectionToGraphMin)

# title slide
data = []
layout = go.Layout(
    width=2000,
    height=350,
    margin=dict(l=80, r=80, b=40, t=20, pad=4),
    font=dict(color='rgb(0,0,0)', size=40, family='Helvetica'),
    showlegend=False,
    title=dict(text = "Detailed PPG, SpO₂, and BPM Graphs<br>(" + str(timeSectionToGraphMin*60) + " seconds per graph)",
        x = 0.5, y = 0.57, xanchor = 'center', yanchor = 'middle'),
    xaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
    yaxis = dict(showticklabels=False, showgrid=False, zeroline=False),
)
fig = go.Figure(data=data, layout=layout)
pdf_file = io.BytesIO()
pio.write_image(fig, pdf_file, 'pdf')
pdf_file.seek(0)
merger.append(pdf_file)

# data slides
for detailGraph in range(0, detailGraphsToWrite):
    print("creating graph: " + str(detailGraph+1) + "/" + str(detailGraphsToWrite))
    timeOffsetS = detailGraph * timeSectionToGraphMin * 60
    samplesOffset = round(timeOffsetS * samplesPerSecond)
    # print("samplesOffset: " + str(samplesOffset))
    timeSectionToGraphMs = timeSectionToGraphMin * 60 * 1000
    sampleSizeToGraph = round(numberOfSamples * timeSectionToGraphMs / durationMs)
    # print("samples in subset: " + str(sampleSizeToGraph))

    timeSequence = []
    for i in range(samplesOffset, sampleSizeToGraph + samplesOffset):
        millisecondsTick = timeSectionToGraphMs * i / sampleSizeToGraph
        timeSequence.append(startDateTime + timedelta(milliseconds=millisecondsTick))
        # timeSequence.append(timeSectionToGraphMs * i / sampleSizeToGraph / 1000)

    oximeterDataSubset = []
    if (sampleSizeToGraph+samplesOffset <= numberOfSamples): # if we are well before the end, all is fine
        oximeterDataSubset = oximeterData[samplesOffset:sampleSizeToGraph+samplesOffset]
    else: # otherwise we have to make sure that we do not access data that does not exist, and fill it up with empty values
        oximeterDataSubset = oximeterData[samplesOffset:numberOfSamples]
        for i in range(0, sampleSizeToGraph+samplesOffset - numberOfSamples):
            oximeterDataSubset.append(emptyEntry)

    # print("samples in subset: " + str(len(oximeterDataSubset)))
    ppgDataSubset = []
    bpmDataSubset = []
    spo2DataSubset = []
    for i in range(0, sampleSizeToGraph):
        ppgDataSubset.append(oximeterDataSubset[i]['PPG'])
        bpmDataSubset.append(oximeterDataSubset[i]['BPM'])
        spo2DataSubset.append(oximeterDataSubset[i]['SPO2'])

    data = [
        go.Scatter(
            x=timeSequence,
            y=bpmDataSubset,
            mode='lines',
            name='BPM',
            line=dict(color='rgb(0,100,80)', width=2),
            yaxis='y2',
        ),
        go.Scatter(
            x=timeSequence,
            y=spo2DataSubset,
            mode='lines',
            name='SpO₂',
            line=dict(color='rgb(49,130,189)', width=2),
            yaxis='y2',
        ),
        go.Scatter(
            x=timeSequence,
            y=ppgDataSubset,
            mode='lines',
            name='PPG',
            line=dict(color='black', width=1),
            yaxis='y1',
        ),
    ]
    bpmSpo2LowValue = 55
    if (bpmMin < bpmSpo2LowValue): bpmSpo2LowValue = bpmMin
    if (spo2Min < bpmSpo2LowValue): bpmSpo2LowValue = spo2Min
    bpmSpo2HighValue = 120
    if (bpmMax > bpmSpo2HighValue): bpmSpo2HighValue = bpmMax
    layout = go.Layout(
        width=2000,
        height=350,
        margin=dict(l=80, r=80, b=40, t=20, pad=4),
        font=dict(color='rgb(0,0,0)', size=25, family='Helvetica'),
        # xaxis = dict(tickfont = dict(size = 20)),
        # xaxis = dict(tickangle=315, nticks=totalEntryCount+1),
        # yaxis = dict(nticks=9),
        showlegend=False,
        # legend=dict(x=0.03, y=1.0, font=dict(size=20),bordercolor='rgb(0,0,0)',borderwidth=1),
        yaxis=dict(title='PPG (black)', range=[0, 100]),
        yaxis2=dict(title='BPM (green), SpO₂ (blue)', titlefont = dict(size = 25), overlaying='y', side='right', range=[bpmSpo2LowValue, bpmSpo2HighValue]),
    )
    fig = go.Figure(data=data, layout=layout)
    pdf_file = io.BytesIO()
    pio.write_image(fig, pdf_file, 'pdf')
    pdf_file.seek(0)
    merger.append(pdf_file)

# output all of that
print("writing final pdf")
merger.write(dataFileName.split(".")[0] + "-" + filenameExtension + ".pdf")