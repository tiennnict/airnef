#!/usr/bin/env python

#
#############################################################################
#
# appstate.py - Shared state of airnefcmd: constants, error codes, the global state object and small helpers
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Split out of airnefcmd.py; see airnefcmd.py for the overall program flow.
#
#############################################################################
#

import time
import os
import strutil
from applog import *
from mtpdef import *

#
# constants
#

AIRNEFCMD_APP_VERSION	= "1.1"

DEFAULT_MAX_KB_PER_GET_OBJECT_REQUEST				= 1024 		# 1MB - empirically tweaked to get max download performance from Nikon bodies (too large an xfer and Nikon bodies start intermittently dropping connections)
DEFAULT_MAX_KB_TO_BUFFER_FOR_GET_OBJECT_REQUESTS 	= 32768		# 32MB - max bytes we buffer before flushing what we have to disk

# values for g.fileTransferOrder
FILE_TRANSFER_ORDER_USER_CONFIGURED		= 0
FILE_TRANSFER_ORDER_OLDEST_FIRST		= 1
FILE_TRANSFER_ORDER_NEWEST_FIRST		= 2
# values for g.cameraMake
CAMERA_MAKE_UNDETERMINED				= 0
CAMERA_MAKE_NIKON						= 1
CAMERA_MAKE_CANON						= 2
CAMERA_MAKE_SONY						= 3
# values for g.realtimeDownloadMethod
REALTIME_DOWNLOAD_METHOD_NIKON_EVENTS	= 0
REALTIME_DOWNLOAD_METHOD_MTPOBJ_POLLING	= 1
REALTIME_DOWNLOAD_METHOD_SONY_EXIT		= 2
REALTIME_DOWNLOAD_METHOD_MAX			= REALTIME_DOWNLOAD_METHOD_SONY_EXIT
# values for g.args['sonyuniquecmdsenable'] (bitmask)
SONY_UNQIUECMD_ENABLE_SENDING_MSG					= 0x00000001
SONY_UNQIUECMD_ENABLE_UNKNOWN_CMD_1					= 0x00000002
SONY_UNQIUECMD_ENABLE_SAVING_PROCESS_CANCELLED_MSG	= 0x00000004


#
# custom errno from app
#
ERRNO_CAMERA_COMMUNICATION_FAILURE		= 4000	# general communication error with camera
ERRNO_CAMERA_UNEXPECTED_RESP_CODE		= 4001	# an MTP request was successfully delivered but the camera responsed with response code that indicated failure
ERRNO_CAMERA_PROTOCOL_ERROR				= 4002	# unexpected protocol event during PTP-IP exchange
ERRNO_SONY_REALTIME_ENTER_RETRY_LOOP	= 4003  # not an error or exit - for Sony realtime operaiton we simply return to the session retry loop after a transfer operation
ERRNO_COULDNT_CONNECT_TO_CAMERA			= 4004	# initial connection to camera was unsuccessful
# place all errors for which app should bypass retry invocations here, between ERRNO_FIRST_CUSTOM_DONT_RETRY and ERRNO_LAST_CUSTOM_DONT_RETRY
ERRNO_FIRST_CUSTOM_DONT_RETRY			= 5000	# first custom errno that we trigger for which app should bypass any retry invocations
ERRNO_BAD_CMD_LINE_ARG					= 5000	# bad command line argument specified
ERRNO_FILE_EXISTS_USER_SPECIFIED_EXIT	= 5001	# a file exists that we were to write to and user configured app to exit when this occurs
ERRNO_DIFFERENT_CAMREA_DURING_RETRY		= 5002	# during a retry  invocation a different camera was discvered vs the original camera we found
ERRNO_NO_CAMERA_TRANSFER_LIST			= 5003  # no camera transfer list available and user configured app to exit if the list is not available
ERRNO_NO_CARD_MEDIA_AVIALABLE			= 5004  # second slot specified but camera only has 1 slot
ERRNO_MTP_OBJ_CACHE_VALIDATE_FAILED		= 5005	# we're performing a (debug) validation of object cache and found a mismatch
ERRNO_DOWNLOAD_FILE_OP_FAILED			= 5006	# create/append/write/close operation failed on file being downloaded
ERRNO_RENAME_ENGINE_PARSING_ERROR		= 5007  # error parsing --dirnamespec or --filenamespec
ERRNO_REAL_TIME_CAPTURE_NOT_SUPPORTED	= 5008	# realtime capture not supported on the camera we're connected to
ERRNO_TRANSFER_LIST_NOT_SUPPORTED		= 5009	# camera doesn't support MTP transfer lists, which is used to download user-selected images in the camera
ERRNO_FILENAMESPEC_RESULT_EMPTY_STR		= 5010	# the result of the user-specified --filenamespec resulted in an empty string
ERRNO_FILENAMESPEC_HAS_PATH_CHARACTERS  = 5011  # the result of the user-specified --filenamespec had a path or path characters in it
ERRNO_DOWNLOADEXEC_LAUNCH_ERROR			= 5012	# unable to launch app/script specified by --downloadexec
ERRNO_DOWNLOADEXEC_NON_ZERO_EXIT_CODE	= 5013	# a launched '--downloadexec' app returned a non-zero result and user config was to exit on this case
ERRNO_LAST_CUSTOM_DONT_RETRY			= 5099	# last custom errno that we trigger for which app should bypass any retry invocations

#
# structures
#
class DownloadStatsStruct:

	def __init__(self):
		self.countFilesSkippedDueToDownloadHistory = 0
		self.countFilesSkippedDueToFileExistingLocally = 0
		self.countFilesDownloaded = 0
		self.totalBytesDownloaded = 0
		self.totalDownloadTimeSecs = 0
		
	def reportDownloadStats(self, fDontPrintStatsIfNoFilesDownloaded=False):
		if g.dlstats.totalDownloadTimeSecs > 0: # avoid divide-by-zero in case no files downloaded
			averageDownloadRateMbSec = g.dlstats.totalBytesDownloaded / g.dlstats.totalDownloadTimeSecs / 1048576
		else:
			averageDownloadRateMbSec = 0
		if fDontPrintStatsIfNoFilesDownloaded and g.dlstats.countFilesDownloaded==0:
			return
		applog_i("\n{:d} files downloaded in {:.2f} seconds (Average Rate = {:.2f} MB/s)".format(g.dlstats.countFilesDownloaded, g.dlstats.totalDownloadTimeSecs, averageDownloadRateMbSec))
		if g.dlstats.countFilesSkippedDueToDownloadHistory:
			applog_i("{:d} previously-downloaded files skipped".format(g.dlstats.countFilesSkippedDueToDownloadHistory))
		if g.dlstats.countFilesSkippedDueToFileExistingLocally:
			applog_i("{:d} files skipped because they already existed in output directory".format(g.dlstats.countFilesSkippedDueToFileExistingLocally))


class GlobalVarsStruct:
	def __init__(self):
	
		self.isWin32 = None								# True if we're running on a Windows platform
		self.isOSX = None								# True if we're runnong on an OSX platform
		self.isFrozen = None							# True if we're running in a pyintaller frozen environment (ie, built as an executable)		
		self.args = None								# dictionary of command-line arguments (generated by argparse)
		self.appDir = None								# directory where script is located. this path is used to store all metadata files, in case script is run in different working directory
		self.appDataDir = None							# directory where we keep app metadata
		self.appStartTimeEpoch = None					# time that application started
		self.openSessionTimeEpoch = None				# time when session started with camera
		self.sessionId = None							# MTP session ID
		
		self.objfilter_dateStartEpoch = None			# user-specified starting date filter. any file earlier than this will be filtered.
		self.objfilter_dateEndEpoch = None				# user-specified ending date filter. any file later than this will be filtered.
		self.maxGetObjTransferSize = None				# max size of MTP_OP_GetPartialObject requests
		self.maxGetObjBufferSize = None					# max amount of download file data we buffer before flushing
		
		self.fileTransferOrder = None					# FILE_TRANSFER_ORDER_* constant
	
		self.socketPrimary = None
		self.socketEvents = None
		self.eventChannel = None						# mtpwifi.EventChannel servicing socketEvents
		
		self.cameraMake = CAMERA_MAKE_UNDETERMINED 
		self.realtimeDownloadMethod = None
		
		self.countCardsUsed = None						# number of media cards that airnefcmd will be using/accessing this session
		self.storageId = None
		self.mtpStorageIds = None						# list of storage IDs returned from MTP_OP_GetStorageIDs / parseMptStorageIds()
		self.mtpDeviceInfo = None
		self.mtpStorageInfoList = None
		self.cameraLocalMetadataPathAndRootName = None	# path+root name for all metadata files we associate with a specific model+serial number
		
		self.lastFullMtpHandleListProcessedByBuildMtpObjects = None
		
		self.fAllObjsAreFromCameraTransferList = False	# True if buildMtpObjects() found and retrieved a transfer list from the camera (ie, user picked photos to download on camera)
		self.fRetrievedMtpObjects = False				# True if buildMtpObjects() has successfully completed this session
		self.fRealTimeDownloadPhaseStarted = False		# True if we've completed a "normal" mode transfer (or bypassed it by user config) and have started realtime image download
		
		self.downloadHistoryDict = None					# download history
		self.downloadMtpFileObjects_LastMtpObjectDownload = None # MTP object last downloaded (either last completed or last we were working on)
		
		self.countFilesDownloadedPersistentAcrossStatsReset = 0	# count of files downloaded this session, survives reset of DownloadStatsStruct
			
		# download stats
		self.dlstats = DownloadStatsStruct()

		# exit cleanup tracking vars
		self.filesToDeleteOnAppExit = []
	
#
# global vars
#
g  = GlobalVarsStruct()

#
# global constant data
#
CmdLineActionToMtpTransferOpDict = {				
	'getfiles' 			: MTP_OP_GetObject,			\
	'getsmallthumbs' 	: MTP_OP_GetThumb,			\
	'getlargethumbs'	: MTP_OP_GetLargeThumb		\
}

		
#
# resets all download statistics
#	
def resetDownloadStats():
	g.dlstats = DownloadStatsStruct()	


#
# returns the number of seconds that have elapsed since
# the specified anchor time. if the anchor time is None
# then this routine returns the current time, which
# the caller can use for a subsequent call to get elapsed
# time. time values are floats
#
def secondsElapsed(timeAnchor):
	timeCurrent = time.time()
	if timeAnchor == None:
		return timeCurrent
	return timeCurrent - timeAnchor

				
#
# attempts deletion of a file, ignoring any errors
#
def deleteFileIgnoreErrors(filename):
	try:
		os.remove(filename)
	except:
		pass

			
#
# invoked near  exit, issues a final log message which is used by utils to signify a gracefully
# shutdown and then tells the applog module to shut itself down
#			
def shutdownApplog():
	applog(">>>> airnefcmd session over - App Exit Time: {:s}".format(strutil.getDateTimeStr(fMilitaryTime=True)), APPLOGF_LEVEL_INFORMATIONAL | APPLOGF_DONT_WRITE_TO_CONSOLE) # used by utils to see if we exited gracefully
	applog_shutdown()
