#!/usr/bin/env python

#
#############################################################################
#
# camerasession.py - Camera session management: connect, open/close the MTP session, storage and device properties
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
import os
import math
import mtpwifi
import strutil
import ssdp
from applog import *
from mtpdef import *
from appstate import *
from mtpdatasets import convertGuidStrToLongs, mtpCountedUtf16ToPythonUnicodeStr, mtpTimeStrToEpoch, parseMptStorageIds, parseMtpCountedWordList, parseMtpDeviceInfo, parseMtpObjectInfo, parseMtpStorageInfo, parseNikonMtpEventData

#
# called within application wait loops, this method makes
# sure we keep the MTP session alive by periodically sending
# an MTP request. without such requests many cameras will
# drop the MTP session, including Nikon cameras. the first
# call to this function should be with None - the function
# will return an opaque value that is actually a timestamp
# of when we were last called. the caller should
# periodically call this function thereafter with whatever
# return value we last give it - when enough time has elapsed
# we'll send an MTP command to keep the session alive
#						
def mtpSessionKeepAlive(timeProbeLastSent):
	timeCurrent = time.time()
	if timeProbeLastSent == None:
		return timeCurrent
	if timeCurrent - timeProbeLastSent < 5:
		return timeProbeLastSent
	#
	# send an MTP command to keep session alive. I wanted to use
	# sendProbeRequest() since it's lightweight and seemingly made
	# for that purpose but Sony cameras will still time'out
	# the session if we just send those
	#
	mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetDeviceInfo)
	return timeCurrent
						

#
# closes TCP/IP connection sockets to camera's MTP interface
#
def closeSockets():	
	if g.socketPrimary:
		g.socketPrimary.close()
		g.socketPrimary = None
	if g.socketEvents:
		g.socketEvents.close()	# also ends the EventChannel thread
		g.socketEvents = None
	g.eventChannel = None
	mtpwifi.gEventChannel = None

#
# waits up to 'secs' for the camera to report activity on the event connection. returns early
# when an ObjectAdded event arrives so realtime downloads start right away instead of at the
# next polling interval. falls back to a plain sleep when there is no event connection
#
def waitForCameraActivity(secs):
	if not g.eventChannel or g.eventChannel.closed:
		time.sleep(secs)
		return False
	timeEnd = time.time() + secs
	while True:
		timeLeft = timeEnd - time.time()
		if timeLeft <= 0:
			return False
		events = g.eventChannel.waitForEvents(min(timeLeft, 0.25)) # short slices keep <ctrl-c> responsive on Windows
		if any(event.eventCode == MTP_EVENT_ObjectAdded for event in events):
			applog_d("waitForCameraActivity(): ObjectAdded event received")
			return True
		if g.eventChannel.closed:
			time.sleep(max(timeEnd - time.time(), 0))
			return False


#
# retrieves the count of MTP objects for a given storage ID
#
def getNumMtpObjects(storageId):
	#
	# note that Sony cameras require the optional parameters to MTP_OP_GetNumObjects - Canon/Nikon do not
	# oddly a given Sony wont always reject the absence of the optional parameters
	#
	mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetNumObjects, struct.pack('<III', storageId, 0, 0)) 
	return mtpTcpCmdResult.mtpResponseParameter


#
# retrieves list of MTP object handles for a given storage ID
#
def getMtpObjectHandles(storageId):
	#
	# note that Sony cameras require the optional parameters to MTP_OP_GetObjectHandles - Canon/Nikon do not
	# oddly a given Sony wont always reject the absence of the optional parameters
	#
	mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetObjectHandles, struct.pack('<III', storageId, 0, 0))
	(objHandlesList, bytesConsumed) = parseMtpCountedWordList(mtpTcpCmdResult.dataReceived)
	return objHandlesList


#
# retrieves the MTP object info for the specified handle
# 	
def getMtpObjectInfo(objHandle, fRetryErrors = True):

	#
	# it's been observed on Nikon bodies that if we attempt to issue a MTP_OP_GetObjectInfo
	# right after the object comes into existence then the camera may return a MTP_RESP_GeneralError.
	# the errors were observed to resolve within a second of the original MTP_OP_GetObjectInfo request
	# but we retry up to 5 seconds just in case there are other factors that may delay the object from
	# becoming ready
	#
	timeStart = secondsElapsed(None)
	while True:
		try:
			mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetObjectInfo, struct.pack('<I', objHandle))
			return parseMtpObjectInfo(mtpTcpCmdResult.dataReceived)
		except mtpwifi.MtpOpExecFailureException as e:
			if fRetryErrors == False or e.mtpRespCode == MTP_RESP_COMMUNICATION_ERROR:
				# instructed not to retry or this is a communication error that isn't retried
				raise
			elapsedTimeSecs = secondsElapsed(timeStart)
			applog_d("getMtpObjectInfo() failed: {:s}, elaspsedTimeSecs={:.2f}".format(getMtpRespDesc(e.mtpRespCode), elapsedTimeSecs))			
			if elapsedTimeSecs >= 5:
				raise
			time.sleep(.25) # wait 1/4 second before retrying


#
# uses SSDP discovery to get the IP address of the first camera that responds.
# Returns the IP address string if found or None if not found
#		
def ssdpDiscoverCameraIpAddress():

	#
	# generate service list
	#
	ssdpServiceNames = [ "urn:microsoft-com:service:MtpNullService:1", 		# Sony
		"urn:schemas-canon-com:service:ICPO-SmartPhoneEOSSystemService:1"	# Canon
	]
	if g.args['ssdp_addservice']:
		ssdpServiceNames = ssdpServiceNames + g.args['ssdp_addservice']
	
	consoleWriteLine("Searching for a Sony or Canon camera via SSDP ")
	try:
		ssdpMessage = ssdp.discover(ssdpServiceNames, lambda ssdpMessage : ssdp.extractIpAddressFromSSDPMessage(ssdpMessage) != None,\
			g.args['ssdp_discoveryattempts'], g.args['ssdp_discoverytimeoutsecsperattempt'], g.args['ssdp_discoveryflags'], g.args['ssdp_addmulticastif'])
		if ssdpMessage  == None:
			raise ssdp.DiscoverFailureException(\
				"No camera found via SSDP Discovery. For Sony cameras please make the camera\n"\
				"is in the 'Send to Computer' WiFi mode.")			
	except ssdp.DiscoverFailureException as e:
		raise ssdp.DiscoverFailureException(">> Connection Failed <<\n\n" + str(e)) # prepend "Connection Failed" message to exception text
	finally:
		consoleClearLine()
	
	ipAddrStr = ssdp.extractIpAddressFromSSDPMessage(ssdpMessage)
	applog_i("Found camera at IP address " + ipAddrStr)
	return ipAddrStr
	
	
#
# starts an MTP session with the camera, including opening the TCP/IP
# socket connections, sending the MTP-WiFi host introduction primitive,
# and performing an MTP_OP_OpenSession
#		
def startMtpSession():

	(guidHigh,guidLow) = convertGuidStrToLongs(g.args['initcmdreq_guid'])
	
	#
	# discover camera/IP address if configured to do so
	#
	if g.args['ipaddress'] == "auto":
		ipAddressStr = ssdpDiscoverCameraIpAddress()
	else:
		ipAddressStr = g.args['ipaddress']
	
	#
	# open TCP/IP socket connection to camera
	#
	g.socketPrimary = mtpwifi.openConnection(ipAddressStr, True, g.args['connecttimeout'], g.args['socketreadwritetimeout'], g.args['port'])

	#
	# get session ID
	#
	mtpwifi.resetTransactionIds()
	initCommandAck = mtpwifi.sendInitCmdReq(g.socketPrimary, (guidHigh, guidLow), g.args['initcmdreq_hostname'], g.args['initcmdreq_hostver'])
	g.sessionId = initCommandAck.connectionNumber
	applog_d("Session ID = 0x{:08x}, camera name = \"{:s}\", PTP-IP version = {:s}".format(g.sessionId, initCommandAck.responderName,
		"0x{:08x}".format(initCommandAck.protocolVersion) if initCommandAck.protocolVersion is not None else "not reported"))
	if initCommandAck.protocolVersion is not None and (initCommandAck.protocolVersion >> 16) != (mtpwifi.MTP_TCPIP_PROTOCOL_VERSION >> 16):
		# a different major version may not be compatible (CIPA DC-005 5.5) - warn but carry on, some cameras report odd values
		applog_w("Warning: camera reports PTP-IP protocol version 0x{:08x}, airnef implements 0x{:08x}".format(initCommandAck.protocolVersion, mtpwifi.MTP_TCPIP_PROTOCOL_VERSION))
		
	#
	# open secondary socket for events
	#
	g.socketEvents = mtpwifi.openConnection(ipAddressStr, False, g.args['connecttimeout'], g.args['socketreadwritetimeout'], g.args['port'])
	data = mtpwifi.sendInitEvents(g.socketEvents, g.sessionId)

	#
	# send a probe request on the event socket (not sure why this
	# is reqiured but failing to do so will cause the MTP session
	# to hang unless I replace the probe with a one-second delay)
	#
	mtpwifi.sendProbeRequest(g.socketEvents)

	#
	# service the event connection in the background from here on: answer the camera's
	# probes and collect its events (used to react to new images in realtime mode)
	#
	g.eventChannel = mtpwifi.EventChannel(g.socketEvents)
	mtpwifi.gEventChannel = g.eventChannel
	
	#
	# get device information, which is needed now because some cameras
	# might require non-standard handling unique to their model
	#
	getMtpDeviceInfo()
	
	#
	# open session. Some newer Nikon cameras like the J5 return 0x0 for the session ID
	# from MTP_TCPIP_REQ_INIT_CMD_REQ, which the camera then rejects. The camera appears
	# to accept any non-zero session ID - Nikon's WMU uses a 0x1 so that's what we'll use
	# as well if the camera rejects the session ID we got from MTP_TCPIP_REQ_INIT_CMD_REQ
	#
	
	if g.args['opensessionid'] == None:
		fSessionIdFromCmdLine = False
	else:
		# cmd-line option to use specific session ID (mostly for debugging)
		fSessionIdFromCmdLine = True
		g.sessionId = g.args['opensessionid']		
	while True:
		try:
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_OpenSession, struct.pack('<I', g.sessionId))
			break # successful
		except mtpwifi.MtpOpExecFailureException as e:
			if not fSessionIdFromCmdLine and e.mtpRespCode != MTP_RESP_COMMUNICATION_ERROR:
				applog_d("MTP_OP_OpenSession failed: {:s} for sessionID 0x{:08x}".format(getMtpRespDesc(e.mtpRespCode), g.sessionId))
				if g.sessionId != 0x1:
					applog_d("Retrying MTP_OP_OpenSession with hard-coded ID of 0x1 (for some Nikons)")
					g.sessionId = 0x1
					continue
			# failed
			raise
		
	g.openSessionTimeEpoch = time.time()
	
	
#
# notifies the user via the camera that an airnefcmd transfer sequence is starting,
# for cameras that don't automatically notify the user of this
#	
def notifyCameraUserTransferSessionStarting():

	if g.cameraMake == CAMERA_MAKE_SONY:
		#
		# this causes the "Sending..." message on the 'Send to Computer' screen on the
		# camera. it was discovered by capturing a wireless session between a Sony camera
		# and Sony's Auto Import utility for OSX. note that all MTP_OP_Sony_Set_Request
		# operations be followed by a MTP_OP_Sony_Get_Request, otherwise the camera
		# reports MTP_RESP_DeviceBusy for all subsequent MTP_OP_Sony_Get_Request attempts
		#
		if g.args['sonyuniquecmdsenable'] & SONY_UNQIUECMD_ENABLE_SENDING_MSG:
			data = struct.pack('<5IB', 0x00000002, 0x00000002, 0x00000000, 0x00000000, 0x00020001, 0x00)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Set_Request, struct.pack('<I', 0x4), data)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Get_Request, struct.pack('<I', 0x4))

#
# notifies the user via the camera that an airnefcmd transfer sequence has ended
# for cameras that don't automatically notify the user of this.
#	
def notifyCameraUserTransferSessionEnding():

	if g.cameraMake == CAMERA_MAKE_SONY:
		#
		# Sony only supports one MTP session per user-initiaited 'Send to Computer'
		# sequence. If you attempt a second session the camera will accept the TCP/IP
		# socket connection but will not respond to the MTP_TCPIP_REQ_INIT_CMD_REQ.
		# The user is required to cancel out of 'Send to Computer' and then go back
		# into it for the camera to accept another MTP session. This is rather messy
		# and most users would be annoyed by it so as an alternative we put the camera
		# into slee mode at the end of a session, which guarantees that the camera
		# is kicked out of 'Send to Computer' mode. It has an additional benefit of
		# serving as a means to notify the user when the transfers are over, which is
		# useful for psuedo-realtime download support we implement for Sony cameras,
		# where the user has to go into 'Send to Computer' while shooting whenever he
		# wants to transfer images he's taken since our last download invocation during
		# this app session - putting the camera to sleep lets the user know all files
		# have been downloaded and he can continue shooting
		#
		# The sleep sequence wsa discovered by capturing a wireless session between a Sony
		# camera and Sony's Auto Import utility for OSX. The sequence the Auto Import utility
		# issues starts with the Sony commands in notifyCameraUserTransferSessionStarting(),
		# which causes a "Sending..." message to be displayed on the 'Send to Computer'
		# screen on the camera. After that the Auto Import utility issues a few more commands,
		# one of which it's not clear what it does, followed by another which causes
		# a "The saving process has been cancelled." message and then finally the command
		# that puts the camera into sleep mode. 
		#

		#
		# don't know what this does - it doesn't appear to have an effect on the camera but
		# is issued by Sony's Auto Import utility after the command that displays "Sending..."
		# on the LCD
		#
		if g.args['sonyuniquecmdsenable'] & SONY_UNQIUECMD_ENABLE_UNKNOWN_CMD_1:
			data = struct.pack('<4I3B', 0x00000000, 0x00000003, 0x00000000, 0x00000000, 0x02, 0x00, 0x30)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Set_Request, struct.pack('<I', 0x4), data)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Get_Request, struct.pack('<I', 0x4))

		#
		# this command causes a "The saving process has been cancelled." message to be displayed
		# on the LCD. The command only works if the command that displays "Sending..." is sentinel
		# first, otherwise it has no effect
		#
		if g.args['sonyuniquecmdsenable'] & SONY_UNQIUECMD_ENABLE_SAVING_PROCESS_CANCELLED_MSG:
			data = struct.pack('<4I3B', 0x00000000, 0x00000004, 0x00000000, 0x00000000, 0x02, 0x00, 0x00)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Set_Request, struct.pack('<I', 0x4), data)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Get_Request, struct.pack('<I', 0x4))			
					
		#
		# this causes the camera to leave 'Send to Computer' mode and sleep. this is necessary because the
		# camera only supports one MTP session per connection and if we try another one it'll
		# hang on the MTP_TCPIP_REQ_INIT_CMD_REQ when we try another session
		#
		if g.args['camerasleepwhendone'] == 'yes':
			data = struct.pack('<4I3B', 0x00000000, 0x00000005, 0x00000000, 0x00000000, 0x02, 0x00, 0x30)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Set_Request, struct.pack('<I', 0x4), data)
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Sony_Get_Request, struct.pack('<I', 0x4))
		
		
#
# sends the high-level MTP_OP_CloseSession primitive to close the session 
# with the camera
#	
def endMtpSession():

	notifyCameraUserTransferSessionEnding()

	#
	# issue close session. There is a bug on Nikon cameras where if we end the session too
	# soon after starting one the camera will not respond to a subsequent MTP_TCPIP_REQ_INIT_CMD_REQ
	# the next time we connect to the camera. This typically only happens during airnef development since
	# not many user cases have us exiting less than 1 second before starting. But it's annoying for
	# me to have to keep cycling the WiFi on the camera during development :) So the fix is to delay
	# issuing the end session so that we allow a full second to elapse from the time the session was started.
	# I've seen this issue on a D7200 and J5 - it likely occurs on most/all of their cameras. I'm guessing
	# there's some deferred session-start processing in the camera that doesn't execute in time if we
	# end the session quickly. It can also be avoided if we delay between the time of issuing the
	# MTP_TCPIP_REQ_INIT_CMD_REQ and starting the session but then that delay would impact every
	# invocation (it actually was in v1.00 until I figured out a MTP_TCPIP_REQ_PROBE worked around the
	# start session issue)
	#
	secsElapsedSinceOpenSession = secondsElapsed(g.openSessionTimeEpoch)
	if secsElapsedSinceOpenSession < 1:
		applog_d("endMtpSession(): Delaying for {:.2f} seconds to work around Nikon bug".format(1 - secsElapsedSinceOpenSession))
		time.sleep(1 - secsElapsedSinceOpenSession)
	mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_CloseSession)

#
# called when we determine the make of a camera, this method sets internal flags
# that will control any make-sepcific behavior/logic 
#
def processCameraMakeDetermination():
	if g.args['rtd_pollingmethod'] != None:
		g.realtimeDownloadMethod = g.args['rtd_pollingmethod']
	else:
		if g.cameraMake == CAMERA_MAKE_NIKON:
			g.realtimeDownloadMethod = REALTIME_DOWNLOAD_METHOD_NIKON_EVENTS
		elif g.cameraMake == CAMERA_MAKE_SONY:
			g.realtimeDownloadMethod = REALTIME_DOWNLOAD_METHOD_SONY_EXIT
		else:
			g.realtimeDownloadMethod = REALTIME_DOWNLOAD_METHOD_MTPOBJ_POLLING


#
# performs a MTP_OP_GetDeviceInfo and saves the information into g.mtpDeviceInfo
#
def getMtpDeviceInfo():
	mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetDeviceInfo)	
	mtpDeviceInfo = parseMtpDeviceInfo(mtpTcpCmdResult.dataReceived)
	if g.mtpDeviceInfo:
		# this is a retry invocation. make sure we're talking with the same camera as before
		if mtpDeviceInfo != g.mtpDeviceInfo:
			applog_e("Discovered different camera during retry invocation. Orig camera was Model \"{:s}\", S/N \":{:s}\", New camera is \"{:s}\", S/N \":{:s}\"".format(\
				g.mtpDeviceInfo.modelStr, g.mtpDeviceInfo.serialNumberStr, mtpDeviceInfo.modelStr, mtpDeviceInfo.serialNumberStr))
			sys.exit(ERRNO_DIFFERENT_CAMREA_DURING_RETRY)
	
	g.mtpDeviceInfo = mtpDeviceInfo
	applog_d(g.mtpDeviceInfo)
	
	#
	# determine make of camera for use in any make-specific logic in our app
	#
	makeStrUpper = g.mtpDeviceInfo.manufacturerStr.upper()	
	if makeStrUpper.find("NIKON") != -1:
		g.cameraMake = CAMERA_MAKE_NIKON
	elif makeStrUpper.find("CANON") != -1:
		g.cameraMake = CAMERA_MAKE_CANON
	elif makeStrUpper.find("SONY") != -1:
		g.cameraMake = CAMERA_MAKE_SONY
	else:
		g.cameraMake = CAMERA_MAKE_UNDETERMINED
				
	#
	# set any program options/behavior that is specific to the make of the camera 
	#
	processCameraMakeDetermination()


	#
	# build path (dir + rootfilename) that will serve as the template for all metadata
	# files we create and store locally. this name needs to be unique to the camera
	# attached and locatable on future invocations, so we use a combination of the camera
	# model and serial number
	#	
	g.cameraLocalMetadataPathAndRootName = os.path.join(g.appDataDir, "{:s}-SN{:s}".format(g.mtpDeviceInfo.modelStr, g.mtpDeviceInfo.serialNumberStr))
	
	applog_i("Camera Model \"{:s}\", S/N \"{:s}\"".format(g.mtpDeviceInfo.modelStr, g.mtpDeviceInfo.serialNumberStr))

	
#
# gets the slot index (1 or 2) from an MTP storage ID
#
def getSlotIndexFromStorageId(storageId):
	return storageId>>16
		

#
# selects the storage ID on the camera (ie, media card/slot) to use for this session
#	
def selectMtpStorageId():

	mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetStorageIDs)
	mtpStorageIds = parseMptStorageIds(mtpTcpCmdResult.dataReceived)
	
	countCardSlots = len(mtpStorageIds.storageIdsList)

	applog_d("All Storage IDs:")
	for i in range(0, len(mtpStorageIds.storageIdsList)):
		applog_d("  storageId[{:d}] = 0x{:08x}".format(i, mtpStorageIds.storageIdsList[i]))
		
	# build a bitmap of which cards slots have media cards
	cardsPresentBitmap = 0x00
	firstCardPresent = -1
	countCardsPresent = 0
	for i in range(0, countCardSlots):
		if (mtpStorageIds.storageIdsList[i] & MTP_STORAGEID_PresenceBit):
			if firstCardPresent == -1:
				firstCardPresent = i
			cardsPresentBitmap |= 1<<i
			countCardsPresent += 1
			
			
	if not cardsPresentBitmap:
		applog_e("There are no media card(s) present or card(s) are busy!")
		sys.exit(ERRNO_NO_CARD_MEDIA_AVIALABLE)
		
	if g.args['slot'] == 'firstfound':
		# use first slot that's populated
		storageId = mtpStorageIds.storageIdsList[firstCardPresent]
		countCardsUsed = 1
	elif g.args['slot'] == 'first' or g.args['slot'] == 'second':		
		if g.args['slot'] == 'second' and countCardSlots <= 1:
			applog_e("Second card slot specified but camera only has one card slot!")
			sys.exit(ERRNO_NO_CARD_MEDIA_AVIALABLE)
		storageId = mtpStorageIds.storageIdsList[0 if g.args['slot'] == 'first' else 1]
		if (storageId & MTP_STORAGEID_PresenceBit) == 0:
			applog_e("No card present in specified slot or card is busy!")
			sys.exit(ERRNO_NO_CARD_MEDIA_AVIALABLE)
		countCardsUsed = 1			
	else: # both card slots to be used
		storageId = MTP_STORAGEID_ALL_CARDS
		countCardsUsed = countCardsPresent
	applog_d("  storageId to be used for this invocation: {:08x} [cardsPresentBitmap=0x{:04x}]".format(storageId, cardsPresentBitmap))
	g.countCardsUsed = countCardsUsed
	g.storageId = storageId
	g.mtpStorageIds = mtpStorageIds

	
#
# performs a MTP_OP_GetStorageInfo and saves the information into g.mtpStorageInfoList
#
def getMtpStorageInfo():
	g.mtpStorageInfoList = []
	if g.storageId != MTP_STORAGEID_ALL_CARDS:
		mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetStorageInfo, struct.pack('<I', g.storageId))
		mtpStorageInfo = parseMtpStorageInfo(mtpTcpCmdResult.dataReceived)
		applog_d(mtpStorageInfo)
		g.mtpStorageInfoList.append(mtpStorageInfo)
	else:
		countCardSlots = len(g.mtpStorageIds.storageIdsList)
		for i in range(0, countCardSlots):
			storageId = g.mtpStorageIds.storageIdsList[i]
			if (storageId & MTP_STORAGEID_PresenceBit):				
				mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetStorageInfo, struct.pack('<I', storageId))
				mtpStorageInfo = parseMtpStorageInfo(mtpTcpCmdResult.dataReceived)
				applog_d(mtpStorageInfo)
				g.mtpStorageInfoList.append(mtpStorageInfo)


#
# retrieves an MTP device property from the camera. mtpPropteryCode is a
# MTP_DeviceProp_* value. If fIgnoreIfNotSupported is TRUE then
# empty data is returned if the camera reports that the property is
# not supported.
#		
def getMtpDeviceProperty(mtpDevicePropCode, fIgnoreIfNotSupported=False):
	try:
		mtpTcpCmdResultGetObj = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetDevicePropValue, struct.pack('<I', mtpDevicePropCode))
		return mtpTcpCmdResultGetObj.dataReceived
	except mtpwifi.MtpOpExecFailureException as e:
		if fIgnoreIfNotSupported and e.mtpRespCode != MTP_RESP_COMMUNICATION_ERROR:
			return b'' # empty data
		raise


#
# sets an MTP property in the camera. mtpDevicePropCode is a
# MTP_DeviceProp_* value. If fIgnoreIfNotSupported is TRUE then
# any "not-supported" error will be ignored
#		
def setMtpDeviceProperty(mtpDevicePropCode, devicePropData, fIgnoreIfNotSupported=False):
	try:
		mtpTcpCmdResultGetObj = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_SetDevicePropValue, struct.pack('<I', mtpDevicePropCode), devicePropData)
		return False
	except mtpwifi.MtpOpExecFailureException as e:
		if fIgnoreIfNotSupported and e.mtpRespCode != MTP_RESP_COMMUNICATION_ERROR:
			return True
		raise

		
#
# sets an MTP property for a Canon property. If fIgnoreIfNotSupported is
# TRUE then any "not-supported" error will be ignored
#		
def setMtpDeviceProperty_Canon(devicePropData, fIgnoreIfNotSupported=False):
	try:
		mtpTcpCmdResultGetObj = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_Canon_SetDevicePropValue, dataToSend=devicePropData)
		return False
	except mtpwifi.MtpOpExecFailureException as e:
		if fIgnoreIfNotSupported and e.mtpRespCode != MTP_RESP_COMMUNICATION_ERROR:
			return True
		raise


#
# set's the camera's date using standard MTP device property
#
def setCameraDateTime(timeEpoch=0):

	if not timeEpoch:
		timeEpoch = time.time()
	newCameraTimeHumanReadableStr = strutil.getDateTimeStr(timeEpoch, fMilitaryTime=False)
	
	if g.cameraMake == CAMERA_MAKE_CANON:
		propData = struct.pack('<II', MTP_DeviceProp_Canon_DateTimeUTC, int(timeEpoch))
		fSetDateTimeFailed = setMtpDeviceProperty_Canon(struct.pack('<I', len(propData)+4) + propData, True)
	else:
		newCameraTimeStruct = time.localtime(timeEpoch)
		newCameraTimeMtpStr = time.strftime("%Y%m%dT%H%M%S", newCameraTimeStruct)
		newCameraTimeCountedUtf16 = strutil.stringToCountedUtf16(newCameraTimeMtpStr, True)
		fSetDateTimeFailed = setMtpDeviceProperty(MTP_DeviceProp_DateTime, newCameraTimeCountedUtf16, True)
	if not fSetDateTimeFailed:		
		applog_i("Camera's date/time set to {:s}".format(newCameraTimeHumanReadableStr))
	else:
		applog_w("Failed setting camera's date/time to {:s}".format(newCameraTimeHumanReadableStr))
		
#
# retrieves the camera's date-time and converts it to local epoch time
#
def getCameraDateTime():
	mtpDateTime = getMtpDeviceProperty(MTP_DeviceProp_DateTime, True)
	(mtpDateTimeStr, byteLen) = mtpCountedUtf16ToPythonUnicodeStr(mtpDateTime)
	return mtpTimeStrToEpoch(mtpDateTimeStr)


#
# sychronizes the camera's time to the system's time if they're off more than the
# configured allowable delta
#
def syncCameraDateTimeIfNecessary():

	if g.args['maxclockdeltabeforesync'] == 'disablesync':
		# time sync disabled
		return
		
	if g.cameraMake != CAMERA_MAKE_CANON: # we don't suppor retriving current time on Canon bodies, so we always set it unconditionally
		
		if MTP_DeviceProp_DateTime not in g.mtpDeviceInfo.devicePropertiesSupportedSet:
			applog_v("Camera does not support synching clock")
			return

		cameraCurrentTimeEpoch = getCameraDateTime()
		if not cameraCurrentTimeEpoch:
			applog_w("Unable to obtain camera's time to decide if clock synching is required")
			return

		systemCurrentTimeEpoch = time.time() # note that is some inherent skew between retrieving the camera's time vs getting system time
		
		cameraTimeStr = strutil.getDateTimeStr(cameraCurrentTimeEpoch, fMilitaryTime=False)
		systemTimeStr = strutil.getDateTimeStr(systemCurrentTimeEpoch, fMilitaryTime=False)
		
		applog_d("Camera time epoch: {:.2f}, System time epoch: {:.2f}".format(cameraCurrentTimeEpoch, systemCurrentTimeEpoch))
		applog_d("Clocks: Camera: {:s}, System: {:s}".format(cameraTimeStr, systemTimeStr))
			
		if g.args['maxclockdeltabeforesync'] != 'alwayssync':	
			# if we're only to sync when the skew is beyond a user-configured threshold
			deltaTime = math.trunc(abs(cameraCurrentTimeEpoch - systemCurrentTimeEpoch))
			if (deltaTime <= int(g.args['maxclockdeltabeforesync'])):
				# time delta between camera and system is within configured allowance
				return		
			applog_i("Clocks skewed: Camera: {:s}, System: {:s}".format(cameraTimeStr, systemTimeStr))			
			
	#
	# set camera's date/time to system's current date/time
	#	
	setCameraDateTime()
	
	
#
# retrieves any queued events from Nikon camera, returning parsed event list
#	
def getNikonMtpEvents():
	mtpTcpCmdResultGetObj = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_NkonGetEvent)
	return parseNikonMtpEventData(mtpTcpCmdResultGetObj.dataReceived)
