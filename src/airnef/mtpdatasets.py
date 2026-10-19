#!/usr/bin/env python

#
#############################################################################
#
# mtpdatasets.py - Parsers for PTP/MTP datasets (DeviceInfo, StorageInfo, ObjectInfo, Nikon events, ...)
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Split out of airnefcmd.py; see airnefcmd.py for the overall program flow.
#
#############################################################################
#

import struct
import time
import sys
from . import strutil
from collections import namedtuple
from .applog import *
from .mtpdef import *
from .appstate import *

#
# Converts counted utf-16 MTP string to unicode string
#
def mtpCountedUtf16ToPythonUnicodeStr(data):
	# format of string: first byte has character length of string inlcuding NULL (# bytes / 2)
	if not data:
		return "", 0
	(utf16CharLenIncludingNull,) = struct.unpack('<B', data[0:1])
	if utf16CharLenIncludingNull ==  0:
		# count byte of zero indicates no string.
		return "", 1
	
	utf16ByteLenIncludingNull = utf16CharLenIncludingNull*2
	unicodeStr = str(data[1:1+utf16ByteLenIncludingNull-2], 'utf-16')
	
	# some Nikon strings have trailing NULLs for padding - remove them
	for charPos in reversed(range(len(unicodeStr))):
		if unicodeStr[charPos] != '\x00':
			break;
	unicodeStr = unicodeStr[0:charPos+1]	# ok if original string was null-only string
	
	return unicodeStr, 1+utf16ByteLenIncludingNull	# 1+ for first byte containing character length
	

#
# Removes specified leading characters from string
#
def removeLeadingCharsFromStr(str, charsToRemoveSet):
	for charPos in range(len(str)):
		if str[charPos] not in charsToRemoveSet:
			break;
	return str[charPos:]


#
# Converts a raw MTP-obtained counted array of values into a list format
# of string: first word has count of entries, followed by array of entries,
# each of which is 'elementSizeInBytes' in size. Returns (list, bytesConsumedFromData),
# where 'list' is the list of entries and 'bytesConsumedFromData' is the number of
# bytes used from 'data' to generate the list
#
def parseMtpCountedList(data, elementSizeInBytes):

	elementSizeToUnpackStr = { 1 : 'B', 2 : 'H', 4 : 'I' }

	theList = list()
	(countEntries,) = struct.unpack('<I', data[0:4])
	offset = 4
	for entryIndex in range(countEntries):
		(entry,) = struct.unpack('<' + elementSizeToUnpackStr[elementSizeInBytes], data[offset:offset+elementSizeInBytes])
		offset += elementSizeInBytes
		theList.append(entry)
	return theList, countEntries*elementSizeInBytes + 4		# +4 to include count field itself
def parseMtpCountedWordList(data):
	return parseMtpCountedList(data, 4)
def parseMtpCountedHalfwordList(data):
	return parseMtpCountedList(data, 2)


#
# parses the raw data from MTP_OP_GetStorageIDs into a MptStorageIds tuple
#	
def parseMptStorageIds(data):
	(storageIdsList,bytesConsumed) = parseMtpCountedWordList(data)
	return MptStorageIdsTuple(storageIdsList)


#
# parses the raw data from MTP_OP_GetStorageInfo into a MtpStorageInfo tuple
#		
def parseMtpStorageInfo(data):
	(storageType,fileSystemType,accessCapability,maxCapacityBytes,freeSpaceBytes,freeSpaceInImages,storageDescription) = struct.unpack('<HHHQQIB', data[0:27])
	(volumeLabel,byteLen) = mtpCountedUtf16ToPythonUnicodeStr(data[27:])	
	return MtpStorageInfoTuple(storageType, fileSystemType, accessCapability, maxCapacityBytes,
						freeSpaceBytes, freeSpaceInImages, storageDescription, volumeLabel)						
	

#
# parses the raw data from MTP_OP_GetDeviceInfo into a MtpDeviceInfo tuple
#			
def parseMtpDeviceInfo(data):

	(standardVersion, vendorExtensionID, vendorExtensionVersion) = struct.unpack('<HIH', data[0:8])
	
	offset = 8
	(vendorExtensionDescStr,bytesConsumed) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	offset += bytesConsumed
	offset += 2			# skip 'FunctionalMode' field
	
	(operationsSupportedList,bytesConsumed) = parseMtpCountedHalfwordList(data[offset:])
	offset += bytesConsumed
	
	(eventsSupportedList,bytesConsumed) = parseMtpCountedHalfwordList(data[offset:])
	offset += bytesConsumed
	
	(devicePropertiesSupportedList,bytesConsumed) = parseMtpCountedHalfwordList(data[offset:])
	offset += bytesConsumed
	
	(captureFormatsSupportedList,bytesConsumed) = parseMtpCountedHalfwordList(data[offset:])
	offset += bytesConsumed
	
	(imageFormatsSupportedList,bytesConsumed) = parseMtpCountedHalfwordList(data[offset:])
	offset += bytesConsumed

	(manufacturerStr,byteLen) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	offset += byteLen
	(modelStr,byteLen) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	offset += byteLen
	(deviceVersionStr,byteLen) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	offset += byteLen
	(serialNumberStr,byteLen) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	serialNumberStr = removeLeadingCharsFromStr(serialNumberStr, {' ', '0'}) # remove leading spaces/zeros from serial number

	return MtpDeviceInfoTuple(	standardVersion, vendorExtensionID, vendorExtensionVersion, vendorExtensionDescStr,\
						set(operationsSupportedList), set(eventsSupportedList), set(devicePropertiesSupportedList), \
						set(captureFormatsSupportedList), set(imageFormatsSupportedList), manufacturerStr, \
						modelStr, deviceVersionStr, serialNumberStr)	


#
# parses the raw data from MTP_OP_GetObjectInfo into a MtpObjectInfo tuple
#									
def parseMtpObjectInfo(data):

	(storageId, objectFormat, protectionStatus) = struct.unpack('<IHH', data[0:8])
	(objectCompressedSize, thumbFormat, thumbCompressedSize) = struct.unpack('<IHI', data[8:18])
	(thumbPixWidth, thumbPixHeight, imagePixWidth, imagePixHeight) = struct.unpack('<IIII', data[18:34])			
	(imageBitDepth, parentObject, associationType) = struct.unpack('<IIH', data[34:44])
	(associationDesc, sequenceNumber) = struct.unpack('<II', data[44:52])
				
	offset = 52
	(filename, bytesConsumed) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	offset = offset + bytesConsumed			
	(captureDateStr, bytesConsumed) = mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	captureDateStr = captureDateStr[:15] # Canon adds a ".0"... to the capture date/time - trim that off
	offset = offset + bytesConsumed
	(modificationDateStr, bytesConsumed) =  mtpCountedUtf16ToPythonUnicodeStr(data[offset:])
	modificationDateStr = modificationDateStr[:15] # Canon adds a ".0"... to the modification date/time - trim that off

	return MtpObjectInfoTuple(	storageId, objectFormat, protectionStatus, \
						objectCompressedSize, thumbFormat, thumbCompressedSize, \
						thumbPixWidth, thumbPixHeight, imagePixWidth, imagePixHeight, \
						imageBitDepth, parentObject, associationType, \
						associationDesc, sequenceNumber, filename, \
						captureDateStr, modificationDateStr)

#
# converts a GUID string to a pair of 64-bit values (high/low).
# the following string formats are support:
#		xxxxxxxx 			presumed hex characters specifying lower 64-bit of GUID
#		xxxxxxxx-yyyyyyyy 	presumed hex characters specifying both high (xx) and low (yy) parts of 128-bit GUID
#		xx:xx:xx:xx:xx:xx	presumed MAC address consisting of hex characters (for Sony)
#
def convertGuidStrToLongs(guidHexStr):
	if guidHexStr.find(':') != -1:
		#
		# GUID specified as a MAC address (for Sony). Sony cameras can either operate
		# in a host-selective mode where they'll only accept connections from a specific MAC
		# address or in a mode where they'll accept any GUID as long as the lower 6-bytes
		# of the GUID corresponding to area Sony uses to identify the MAC address are zero.
		# the logic here is when the user wants to run in the host-selective mode - it's
		# pretty much only for debugging.
		#
		
		
		# string are implicitly big endian. build as little endian and then convert
		# to big endian if necessary when done if we're running on a big-endian platform
		#
		macAddressFieldList = guidHexStr.split(':')
		guidLow = 0x0000000000000000
		for nthField in range(len(macAddressFieldList)):
			guidLow |= int(macAddressFieldList[nthField], 16) << nthField*8		
		if len(macAddressFieldList) == 6:
			# Sony preprends 0xFFFF to MAC addr to form the full 64-bit lower GUID
			guidLow = (guidLow<<16) | 0xFFFF
		if sys.byteorder == 'big':
			guidLow = strutil.invertEndian(guidLow)
		guidHigh = 0x0000000000000000
	else:
		posColon = guidHexStr.find('-')
		if posColon != -1:
			# upper 64-bits of GUID specified
			guidHigh = int(guidHexStr[:posColon], 16)
			guidLow = int(guidHexStr[posColon+1:], 16)
		else:
			guidHigh = 0x0000000000000000
			guidLow = int(guidHexStr, 16)
	return (guidHigh, guidLow)

	
#
# converts an MTP date-time string in the format of 'yyyymmddThhmmss'
# to epoch time. note that this conversion involves using the system's
# local time configuration including time zone and DST setting, so
# if the camera has those elements configured differently then the
# converted time wont match up
# 
def mtpTimeStrToEpoch(mtpDateTimeStr):
	if len(mtpDateTimeStr) != 15 or mtpDateTimeStr[8] != 'T':
		# doesn't appear to be a valid MTP date-time string
		return 0
	if mtpDateTimeStr == '19800000T000000':
		# nikon uses this timestamp for some non folder/file objects
		return 0		
	return time.mktime(time.strptime(mtpDateTimeStr, "%Y%m%dT%H%M%S"))


#
# parses an event list returned from MTP_OP_NkonGetEvent, generating a list of
# of MtpEventTuple's describing each event
# 
MtpEventTuple = namedtuple('MtpEvent', 'eventCode eventParameter')	
def parseNikonMtpEventData(data):
	mtpEventTupleList = []
	(eventCount,) = struct.unpack('<H', data[0:2])
	for nthEvent in range(eventCount):
		(eventCode, eventParameter) = struct.unpack('<HI', data[2+nthEvent*6:2+nthEvent*6 + 6])
		mtpEventTupleList.append(MtpEventTuple(eventCode, eventParameter))
	return mtpEventTupleList

	
#
# prints an event list that was generated by parseNikonMtpEventData()
# 
def genNikonEventListDescription(mtpEventList):
	str = ""
	for nthEvent in range(len(mtpEventList)):
		if mtpEventList[nthEvent].eventCode == MTP_EVENT_DevicePropChanged:
			parameterDesc = getMtpDevicePropDesc(mtpEventList[nthEvent].eventParameter)
		else:
			parameterDesc = "0x{:08x}".format(mtpEventList[nthEvent].eventParameter)
		if nthEvent > 0:
			str += "\n" 
		str += "E#{:d}: {:s}, Param: {:s}".format(nthEvent, getMtpEventDesc(mtpEventList[nthEvent].eventCode), parameterDesc) 
		
	return str		
