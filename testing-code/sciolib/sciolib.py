'''
sciolib - SCIO spectrometer library
Copyright (C) 2019  kebasaa

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import logging
log = logging.getLogger('root')
log.setLevel(logging.DEBUG)
logging.basicConfig(format='[%(asctime)s] %(levelname)8s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# To identify the OS
import platform

# To identify the device
import glob
import re
import os

# Exceptions / Assert errors
import sys

# Reading the SCIO through USB serial port
import serial
from serial.tools import list_ports_common

# encode & decode data
import struct

READ_DATA = 2        #02
READ_TEMPERATURE = 4 #04
READ_BATTERY = 5     #05
SET_READY = 14       #0e
SET_LED = 11         #0b
PROTOCOL = -70       #ba

def find_scio_dev():
    scio_dev = ""
    # Check the platform
    # https://dzone.com/articles/linux-system-mining-python
    if(platform.uname().system == 'Linux'):
        # TODO: Add check in case multiple /dev/ttyACMs ports are available #######################
        for device in glob.glob('/dev/*'):
            for pattern in ['ttyACM*']:
                if re.compile(pattern).match(os.path.basename(device)):
                    print('Device:           {0}'.format(device))
                    scio_dev = device
                    #manufacturer = self.read_line(device, 'manufacturer')
                    #product = self.read_line(device, 'product')
                    #print(manufacturer)
                    #print(product)
    elif(platform.uname().system == 'Windows'):
        # TODO: Add check in case multiple COM ports are available
        import serial.tools.list_ports as port_list
        if(port_list.comports()):
            scio_dev = port_list.comports()[0][0]
    else:
        log.error("This program currently only works on Linux & Windows.")
        log.error("--> You are running " + platform.uname().system + ".")
        log.error("--> Exiting...")
        quit()
    if scio_dev == "":
        print("If no ttyACM (Linux) or COM (Windows) is detected: Is the SCIO on?")
        quit()
    # TODO: Add a check or manufacturer to determine that this is really the scio and not some arduino
    log.info("Using port: " + scio_dev)
    return(scio_dev)

def encode_b64(bytestring):
    # Encode and decode data as base64 (to store until we know what to do with it)
    import base64
    urlSafeEncodedBytes = base64.urlsafe_b64encode(bytestring)
    urlSafeEncodedStr = str(urlSafeEncodedBytes, "utf-8")
    return(urlSafeEncodedStr)

def decode_b64(b64string):
    # Encode and decode data as base64 (to store until we know what to do with it)
    import base64
    bytestring = base64.urlsafe_b64decode(b64string)
    return(bytestring)

def json_read(filename):
    outdf = [ ]
    import json
    with open(filename) as json_file:
        jsondata = json.load(json_file)
        for p in jsondata['scan']:
            outdf.append(decode_b64(p['part1']))
            outdf.append(decode_b64(p['part2']))
            outdf.append(decode_b64(p['part3']))
    return(outdf)

    jsondata = {}
    jsondata['scan'] = []
    jsondata['scan'].append({
        'part1': encode_b64(raw_df[0]),
        'part2': encode_b64(raw_df[1]),
        'part3': encode_b64(raw_df[2])
    })
    # Write data to JSON file
    import json
    with open(filename, 'w') as outfile:
        json.dump(jsondata, outfile)
    
def protocol_message(cmd):
    byte_command = b"" # empty initialisation
    if(cmd == SET_LED):
        # Setting the LED colour is special (longer command)
        byte_command = struct.pack('<bbbbbbbbbbbbbbb',1,PROTOCOL,cmd,9,0,0,0,0,0,0,0,0,0,0)
    else:
        byte_command = struct.pack('<bbbbb',1,PROTOCOL,cmd,0,0)
    return(byte_command)

def read_data(scio_dev, command):
    # Relevant functions
    def decode_temperature(msg, message_length):
        num_vars = message_length / 4 # divide by 4 because we are dealing with longs
        data_struct = '<' + str(int(num_vars)) + 'l' # This is '<3l' or '<lll'
        # Convert bytes to unsigned int
        message_data = struct.unpack(data_struct ,s)
        # Convert to temperatures
        cmosTemperature = (message_data[0] - 375.22) / 1.4092 # Does this make sense? It's from the disassembled Android app...
        chipTemperature = (message_data[1]) / 100
        objectTemperature = message_data[2] / 100
        temperature_df = [cmosTemperature, chipTemperature, objectTemperature]
        return(temperature_df)
    
    # Send reading command
    # - - - - - - - - - - -
    
    # Create the message
    #byte_msg = protocol_message(READ_TEMPERATURE)
    byte_msg = protocol_message(command)
    
    # Open serial connection
    try:
        ser = serial.Serial(scio_dev)
    except OSError as error:
        log.error(error)
        quit()
    
    # write the message to the serial device
    ser.write(byte_msg)
    
    # Read the response
    # - - - - - - - - - - -
    
    # Start reading the response
    s = ser.read(1)
    message_type    = struct.unpack('<b',s)[0]
    
    # Error check
    assert (message_type == PROTOCOL), 'Wrong message type: {}'.format(message_type)
    
    # Data type
    s = ser.read(1)
    message_content = struct.unpack('<b',s)[0]
    if(message_content == READ_TEMPERATURE):
        log.debug("Receiving temperature data: " + str(message_content))
        # Data length
        s = ser.read(2)
        message_length = struct.unpack('<H',s)[0]
        # Read the number of values specified by the message length
        s = ser.read(message_length)
        ser.close()
        # decode that data
        temperature_df = decode_temperature(s, message_length)
        return(temperature_df)  # cmosTemperature, chipTemperature, objectTemperature
    elif(message_content == READ_DATA):
        raw_df = [ ]
        log.debug("Receiving scan data: " + str(message_content))
        # get rid of first 2 sets to get
        for i in range(3):
            log.debug("--> Part: " + str(i+1))
            if(i > 0):
                s = ser.read(1)
                message_type    = struct.unpack('<b',s)[0]
                s = ser.read(1)
                message_content = struct.unpack('<b',s)[0]
            s = ser.read(2)
            message_length = struct.unpack('<H',s)[0]
            s = ser.read(message_length)
            raw_df.append(s)
        ser.close()
        return(raw_df)
    else:
        log.debug("Receiving unknown message: " + str(message_content))
        
    # This divides one list by another
    #print([n/d for n, d in zip(df[0], df[2])])
    
def decode_data(raw_df):
    # 40-bit decoding functions
    def getU40(data, index):
        dat = data[index:(index+5)]
        return float( ((( int(dat[0] & 255)) + (( int(dat[1] & 255)) << 8)) + (( int(dat[2] & 255)) << 16)) + (( int(dat[3] & 255)) << 24) + (( int(dat[4] & 255)) << 32) )
            
    def unpackU40(data, header):
        temp = [ ]
        footer = 145 - header
        data_length = len(data) - header - footer
        for j in range( int(data_length/5) ):
            temp.append( getU40(data, j*5+header) / 100000000)
        return(temp)
        
    def getU40_le(data, index):
        dat = data[index:(index+5)]
        return float( ((( int(dat[4] & 255)) + (( int(dat[3] & 255)) << 8)) + (( int(dat[2] & 255)) << 16)) + (( int(dat[1] & 255)) << 24) + (( int(dat[0] & 255)) << 32) )
        
    def unpackU40_le(data, header):
        temp = [ ]
        footer = 145 - header
        data_length = len(data) - header - footer
        for j in range( int(data_length/5) ):
            temp.append( getU40_le(data, j*5+header) / 100000000)
        return(temp)
        
    
    # Function to try to decode
    def decode(raw_df, header):
        df = [ ]
        for part in range(len(raw_df)):
            if(part == 2):
                header = 0
            df.append( unpackU40_le(raw_df[part], header) )
        return(df)
        
    # iterate over possible number of headers in order to find solution
    solution = False
    for h in range(145):
        #print("Header: " + str(h))
        df = decode(raw_df,h)
        reflectance = [n/d for n, d in zip(df[0], df[2])]
        if(all(i <= 1.0 for i in reflectance)):
            solution = True
            print("Solution with header " + str(header))
    if(not solution):
        print("No solution found")

def save_json(temp_before_df, temp_after_df, scan_df, filename):
    # This will save the data to JSON temporarily. In the end, I'll want to be able to save decoded data
    
    # create the json file
    jsondata = {}
    jsondata['scan'] = []
    jsondata['scan'].append({
        't_cmos_before': temp_before_df[0], # cmosTemperature, chipTemperature, objectTemperature
        't_chip_before': temp_before_df[1],
        't_obj_before':  temp_before_df[2],
        't_cmos_before': temp_after_df[0],
        't_chip_before': temp_after_df[1],
        't_obj_before':  temp_after_df[2],
        'part1': encode_b64(scan_df[0]),
        'part2': encode_b64(scan_df[1]),
        'part3': encode_b64(scan_df[2])
    })
    
    # Write data to JSON file
    import json
    with open(filename, 'w') as outfile:
        json.dump(jsondata, outfile, indent=4)
