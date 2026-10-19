#!/usr/bin/env python

#
#############################################################################
#
# realtime.py - Realtime download of images as they are taken
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Split out of airnefcmd.py; see airnefcmd.py for the overall program flow.
#
#############################################################################
#

import struct
import sys
from . import strutil
from .applog import *
from .mtpdef import *
from .appstate import *
from .mtpdatasets import genNikonEventListDescription
from .camerasession import getMtpObjectHandles, getMtpObjectInfo, getNikonMtpEvents, getNumMtpObjects, waitForCameraActivity
from .objectcatalog import MtpObject, createMtpObjectFromHandle, createMtpObjectsFromHandleList
from .downloader import downloadMtpFileObjects

#
# sets/changes the capture date filter to our app's start time. this is
# done to limit further downloads to those captured after the app started,
# such as for realtime capture
#
def changeCaptureDateFilterToAppStartTime():
	#
	# I've found a bug in the D7200 and D750 - it may exist on other cameras but I
	# don't see it on a D7100 w/WU-1a nor a J5. The firmware will sometimes misreport
	# the seconds field capture time in the MTP_OP_GetObjectInfo. It's a curious bug -
	# the camera reports a seconds value that is half of the actual value. Here is an
	# actual example taken from a D7200:
	#
	# Data returned from MTP_OP_GetObjectInfo:
	#
	# 	filename           	= DSC_0093.NEF
    # 	captureDateSt       = 20150927T185813
    #	modificationDateStr = 20150927T185813
	#
	# However when the file is viewed on the camera in playback mode the correctly
	# displayed timestamp is 18:58:26, so the MTP seconds timestamp is half what it
	# should be. When the issue does occur it appears to be a capture-time bug - the
	# camera will always misreport the time on  files that had the issue even
	# if it's currently in a state where it doesn't have the issue (ie, where
	# new files deliver the correct timestamp over MTP).
	#
	# Since we use capture-date filtering for our realtime capture having the time
	# skew from this bug will cause us to think the image is older than it is, at least
	# within the first minute of our session where the skew is enough to put the image
	# before our appStartTimeEpoch. To work around this I adjust the capture-date filter
	# back by 35 seconds from realtime (a few extra seconds padding just in case) - since
	# the Nikon bug produces max skew of 30 seconds (for the case of the real timestamp
	# being 59 seconds but the camera reports it as 29, since it rounds down). This runs
	# the risk of us downloading images taken up to 35 seconds before the user launched
	# airnefcmd for realtime transfer (ie, images the user didn't want if he's running
	# airnefcmd in realtime-only mode)
	#
	g.objfilter_dateStartEpoch = g.appStartTimeEpoch - 35
	g.objfilter_dateEndEpoch = None


#
# clears the capture date filters
#	
def clearCaptureDateFilter():
	g.objfilter_dateStartEpoch = None
	g.objfilter_dateEndEpoch = None
	
	
#
# displays the next character of a twirlling ASCII progress character. this routine
# is called multiple times during a long-running loop, giving the appearance of
# a spinning character. it's used to show the user that we're still alive
# 
#
def printSpinningProgressCharToConsole():
	progressChars = "-\\|/"
	
	if not hasattr(printSpinningProgressCharToConsole, "lastProgressCharPrinted"):	# static variable to track last progress character printed
		printSpinningProgressCharToConsole.lastProgressCharPrinted = -1
	
	printSpinningProgressCharToConsole.lastProgressCharPrinted += 1
	if printSpinningProgressCharToConsole.lastProgressCharPrinted >= len(progressChars):
		printSpinningProgressCharToConsole.lastProgressCharPrinted = 0
	consoleWriteLine('\b' + progressChars[printSpinningProgressCharToConsole.lastProgressCharPrinted])
	
#
# realtime download loop using Nikon-specific event mechanism
#
def realTimeCapture_NikonEventsMethod():

	fRedrawWaitingMessage = True
	try:
		while True:
		
			if fRedrawWaitingMessage:
				consoleWriteLine("\rWaiting for realtime photos from camera to download. Press <ctrl-c> to exit  ")
				fRedrawWaitingMessage = False
			printSpinningProgressCharToConsole()
		
			#
			# retrieve any pending events
			#		
			nikonMtpEventList = getNikonMtpEvents()
			if nikonMtpEventList:

				#
				# process the events, creating MTP objects for any new directories/files
				#
				applog_d(genNikonEventListDescription(nikonMtpEventList))
				countNewFileObjects = 0
				firstNewMtpFileObject = None
				for nthEvent in range(len(nikonMtpEventList)):
					if nikonMtpEventList[nthEvent].eventCode == MTP_EVENT_ObjectAdded:
						objHandle = nikonMtpEventList[nthEvent].eventParameter
						if MtpObject.getByMtpObjectHandle(objHandle):
							applog_d("realTimeCapture: MtpObject for handle 0x{:08x} already exists, skipping".format(objHandle))
							continue
						mtpObjectInfo = getMtpObjectInfo(objHandle)
						if g.storageId != MTP_STORAGEID_ALL_CARDS and mtpObjectInfo.storageId != g.storageId:
							if isVerboseLog():
								consoleClearLine()
								fRedrawWaitingMessage = True
								applog_v("Ignoring \"{:s}\" because it's not from your configured --slot".format(mtpObjectInfo.filename))
						else:
							# create MTP object for this new obj
							mtpObject = createMtpObjectFromHandle(objHandle, mtpObjectInfo=mtpObjectInfo)
							if mtpObject.mtpObjectInfo.associationType != MTP_OBJASSOC_GenericFolder:
								countNewFileObjects += 1
								if firstNewMtpFileObject == None:
									firstNewMtpFileObject = mtpObject
							
				if countNewFileObjects:
					consoleClearLine()
					fRedrawWaitingMessage = True
					downloadMtpFileObjects(firstNewMtpFileObject)
					continue # check for new events immediately without sleeping first
			
			#
			# no new files in this event list. sleep before checking again
			#
			waitForCameraActivity(g.args['realtimepollsecs'])
			
	except KeyboardInterrupt as e: # <ctrl-c> pressed
		consoleClearLine()
		g.dlstats.reportDownloadStats(g.args['realtimedownload'] != 'only') # print stats even if no files downloaded only if this was a realtime-only session
		raise

		
#
# realtime download loop using generic MTP-object count polling method
#
def realTimeCapture_MtpObjPollingMethod():

	#
	# there are two polling methods for detecting the possibility of
	# new images - either poll the object count and when it changes
	# download the new object handle list or poll the object handle list
	# itself by downloading it every interval. it would seem polling the
	# couunt would be more efficient since there is less data to move every
	# polling interval, and possibly less work for the camera to do
	# to deliver the data (ie, may have to do media access to retrieve
	# the object handle list but not the count). however a big drawback
	# of polling the object count is that it'll miss the case of the user
	# deleting an image in the camera and then taking another, which
	# will result in a non-changing object count if both events occur between
	# our polling inteval. so we're going to use the objlist polling method
	# instead, but I've left in the numobjs polling method just in case the
	# objlist method causes problems for some cameras (method selectable via
	# a command-line argument). during development I timed both methods on
	# a Canon 6D and it actually turned out that retrieving the object handle
	# list was faster than retrieving the object handle count (20ms vs 50ms).
	#
	# whichever polling method is used, the end result is we download the
	# new object handle list and do a subtraction between it and the previous
	# object handle list we have to get a list of new objects, then insert those
	# new objects into the MTP object tree and do a download cycle starting
	# from the first newly-inserted object.
	#
	# for the initial full object list we use the list obtained by
	# the most recent invocation of buildMtpObjects(). using that list
	# gurantees we wont miss any images taken between the interval of
	# the most recent build/download sequence. note that this initial
	# full object list will be empty for realtime-only configuraitons 
	# and this is the first invocation of the realtime phase - in this
	# case we simply download the list now (no risk of missing images
	# because the user hasn't been told we're ready for realtime until
	# the message that will be posted below to the console)
	#
	
	lastFullMtpHandleList = g.lastFullMtpHandleListProcessedByBuildMtpObjects
	if not lastFullMtpHandleList:
		# this is a realtime-only session and this is first invocation (no recovery retries yet)
		lastFullMtpHandleList = getMtpObjectHandles(g.storageId)
		if isDebugLog():
			applog_d("realTimeCapture_MtpObjPollingMethod(): First MTP object list (count={:d}):".format(len(lastFullMtpHandleList)))
			applog_d(strutil.hexdump(struct.pack('<' + 'I'*len(lastFullMtpHandleList), *lastFullMtpHandleList), bytesPerField=4, includeASCII=False))
		
	fRedrawWaitingMessage = True
	try:
		while True:
		
			if fRedrawWaitingMessage:
				consoleWriteLine("\rWaiting for realtime photos from camera to download. Press <ctrl-c> to exit  ")
				fRedrawWaitingMessage = False
			printSpinningProgressCharToConsole()
			
			fNumObjsChanged = False
			if g.args['rtd_mtppollingmethod_newobjdetection'] == 'numobjs':
				#
				# see if the number of MTP objects on the camera has changed since
				# the last time we've processed the camera's object list
				#
				numMtpObjects = getNumMtpObjects(g.storageId)
				fNumObjsChanged = numMtpObjects != len(lastFullMtpHandleList)
				if fNumObjsChanged:
					applog_d("fNumObjsChanged TRUE: (previous=0x{:d}, new=0x{:d}".format(len(lastFullMtpHandleList), numMtpObjects))
				
			if fNumObjsChanged or g.args['rtd_mtppollingmethod_newobjdetection'] == 'objlist':
			
				#
				# get current list of object handles from camera if we're using the
				# numobjs method for detection and the number of objects changed or if
				# we're using the objlist method (to see if there are new objects)
				#
				currentFullMtpHandleList = getMtpObjectHandles(g.storageId)
				newMtpHandleList = list(set(currentFullMtpHandleList).difference(lastFullMtpHandleList))				
				lastFullMtpHandleList = currentFullMtpHandleList
				
				if isDebugLog() and (fNumObjsChanged or newMtpHandleList):
					applog_d("realTimeCapture_MtpObjPollingMethod(): Current MTP object list (count={:d}):".format(len(currentFullMtpHandleList)))
					applog_d(strutil.hexdump(struct.pack('<' + 'I'*len(currentFullMtpHandleList), *currentFullMtpHandleList), bytesPerField=4, includeASCII=False))
					applog_d("realTimeCapture_MtpObjPollingMethod(): New MTP object list (count={:d}):".format(len(newMtpHandleList)))
					applog_d(strutil.hexdump(struct.pack('<' + 'I'*len(newMtpHandleList), *newMtpHandleList), bytesPerField=4, includeASCII=False))				
								
				if newMtpHandleList:
										
					# we have new objects to process
					consoleClearLine()
					fRedrawWaitingMessage = True
														
					createMtpObjectsFromHandleList(newMtpHandleList)
					downloadMtpFileObjects()
					
					continue # check for new objects immediately without sleeping first
				
			#
			# no new objects. sleep before checking again
			#
			waitForCameraActivity(g.args['realtimepollsecs'])
			
	except KeyboardInterrupt as e: # <ctrl-c> pressed
		consoleClearLine()
		g.dlstats.reportDownloadStats(g.args['realtimedownload'] != 'only') # print stats even if no files downloaded only if this was a realtime-only session
		raise

		
#
# realtime download entry for Sony cameras. There is no support
# for camera option while in Sony's 'Send to Computer' mode so
# we implement an offline method where the user selecitvely goes
# back into 'Send to Computer' mode whenever he wants to transfer
# images he's taken. To trigger this we'll do a sys.exit() here
# with a retryable exit code, which will execute the usualy Sony-sleep
# end session logic but then re-enter the retry loop.
#
def realTimeCapture_SonyExitMethod():
	applog_i("\nSony transfer session done - entering staged realtime wait for new images")
	sys.exit(ERRNO_SONY_REALTIME_ENTER_RETRY_LOOP)


#
# function that implements realtime capture of images
#
def realTimeCapture():

	#
	# modify the filter configuration so that it functions with realtime downloads.
	# we have to be careful that any filters added in future versions are properly
	# accounted for here as well - I put a note in processCmdLine() to that effect
	#
	
	#
	# reset any capture filter in place from the 'normal' download phase. I clear
	# the capture date filter rather than setting it to the app launch time because
	# we don't have to worry about downloading files created before launch time because
	# all the realtime polling methods prevent the MTP Object list from being scanned,
	# meaning we don't run the risk of older files being found for download. I go out
	# of my way to avoid having to rely on the launch-time capture date filter so that
	# we can accommodate clock skew between camera and system (for cameras we don'tail
	# support time sync for)
	# 
	clearCaptureDateFilter()
		
	g.args['cameratransferlist']  = 'ignore'	# so that recovery operations use the full camera object list rather than any transfer list already processed
	g.fAllObjsAreFromCameraTransferList = False	# we'll be adding non-transfer list objects (ie, the files we download in realtime)
	g.args['transferorder'] = 'oldestfirst'		# so that downloadMtpFileObjects() will properly enumerate through multiple realtime images as we add them
	g.fRealTimeDownloadPhaseStarted = True		# used by logic when making decisions on reporting for downloads, recovery operations, etc..
			
	#
	# reset download stats of the original, non-real time download. this way we
	# capture stats specific to the realtime phase
	#
	resetDownloadStats()
	
	#
	# start realtime capture loop
	#
	if g.realtimeDownloadMethod == REALTIME_DOWNLOAD_METHOD_NIKON_EVENTS:
		realTimeCapture_NikonEventsMethod()
	elif g.realtimeDownloadMethod == REALTIME_DOWNLOAD_METHOD_MTPOBJ_POLLING:
		realTimeCapture_MtpObjPollingMethod()
	elif g.realtimeDownloadMethod == REALTIME_DOWNLOAD_METHOD_SONY_EXIT:
		realTimeCapture_SonyExitMethod()
