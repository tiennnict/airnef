#!/usr/bin/env python

#
#############################################################################
#
# airnefcmd.py - Wireless file transfer for PTP/MTP-equipped cameras (command-line app)
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# This is the entry point: it sets up the environment and runs the session/retry loop
# (appMain/main). The work is done by these modules, each depending only on the ones
# listed before it:
#
#   appstate.py       constants, error codes, the global state object 'g'
#   mtpdatasets.py    parsers for PTP/MTP datasets
#   camerasession.py  connecting, MTP session, storage and device properties
#   objectcatalog.py  enumerating the camera's objects, object cache, user filters
#   downloader.py     downloading files, history, renaming, --downloadexec, listings
#   realtime.py       realtime download of images as they are taken
#   cmdline.py        command-line argument processing
#
#############################################################################
#

import time
import sys
import os
import errno
import traceback
import platform
import socket
import mtpwifi
import strutil
import ssdp
from applog import *
from mtpdef import *
from appstate import *
from camerasession import closeSockets, endMtpSession, getMtpStorageInfo, notifyCameraUserTransferSessionStarting, selectMtpStorageId, startMtpSession, syncCameraDateTimeIfNecessary
from objectcatalog import buildMtpObjects
from downloader import downloadMtpFileObjects, printMtpObjectDirectoryListing
from realtime import changeCaptureDateFilterToAppStartTime, realTimeCapture
from cmdline import processCmdLine

#
# verifies user is running version a modern-enough version of python for this app
#		
def verifyPythonVersion():
	if sys.version_info < (3, 12):
		applog_i("Warning: You are running a Python version older than app was tested with.")
		applog_i("Version running is {:d}.{:d}.{:d}, app requires 3.12 or newer".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro))


#
# sets app-level globals related to the platform we're running under and
# creates path to app directories, creating them if necessary
#			
def establishAppEnvironment():

	g.isWin32 = (platform.system() == 'Windows')
	g.isOSX = (platform.system() == 'Darwin') 
	g.isFrozen = (getattr(sys, 'frozen', False)) # note for OSX isFrozen is always false because py2app only marks airnef.pyw as frozen when we're a py2app

	#
	# determine the directory our script resides in, in case the
	# user is executing from a different working directory.
	#
	g.appDir = os.path.dirname(os.path.realpath(sys.argv[0]))

	#
	# determine directory for our APPDATA, which contains log
	# and configuration files. For Win32 if we're frozen this
	# goes in the dedicated OS area for application data files
	#
	g.appDataDir = os.getenv('AIRNEF_APPDATA')	# explicit override (used by the test suite)
	if g.appDataDir:
		pass
	elif g.isFrozen and g.isWin32:
		if os.getenv('LOCALAPPDATA'):
			g.appDataDir = os.path.join(os.getenv('LOCALAPPDATA'), "airnef\\appdata") # typically C:\Users\<username>\AppData\Local\airnef\appdata
	elif g.isOSX: # for OSX we always try to store our app data under Application Support
		userHomeDir = os.getenv('HOME')
		if userHomeDir:
			applicationSupportDir = os.path.join(userHomeDir, 'Library/Application Support')
			if os.path.exists(applicationSupportDir): # probably not necessary to check existence since every system should have this directory
				g.appDataDir = os.path.join(applicationSupportDir, 'airnef/appdata')
	if not g.appDataDir:
		# none of runtime-specific cases above selected an app data directory - use directory based off our app directory
		g.appDataDir = os.path.join(g.appDir, "appdata")
	# create our app-specific subdirectories if necessary
	if not os.path.exists(g.appDataDir):
		os.makedirs(g.appDataDir)
		
#
# main work routine
#
def appMain():

	if not hasattr(appMain, "lastConnectErrMsg"):
		appMain.lastConnectErrMsg = "" # static var to track last connect err msg to allow supressing reporting while waiting for connection across retries

	bSessionStarted = False
	bAttemptCloseSessionAtTermination = False
	bEchoNewlineBeforeReturning = True
	try:
		#
		# start wireless session
		#
		startMtpSession()
		bSessionStarted = True						# we're now in a session
		bAttemptCloseSessionAtTermination = True	# we're now in a session, so set flag to close it when we're done
		appMain.lastConnectErrMsg = ""				# clear out last connection error msg now that we're connected
		
		#
		# sync clocks if necessary
		#
		syncCameraDateTimeIfNecessary()
							
		#
		# select appropriate media card slot (storage ID)
		#
		selectMtpStorageId()
		
		#
		# get information on media card
		#
		getMtpStorageInfo()
		
		#
		# notify camera user that we're about to start any potential transfers
		#
		notifyCameraUserTransferSessionStarting()
		
		#
		# populate our list of MTP objects. we bypass this if we've retrieved all objects
		# on a previous retry this session and if we haven't already entered the realtime capture
		# phase. we can't bypass if we've entered realtime operation in case the user captured images
		# while we were re-establishing the connection to the camera during a retry, otherwise we'd miss
		# those objects and fail to download them. Note that we bypass the initial object retrieval (which
		# can be very time consuming depending on the camera and how many images are on the cards) if
		# we're in realtime-only mode and we were able to establish a connection to the camera within
		# 10 seconds (configurable) of the user starting our app (any longer and we run the risk that the
		# user already started taking photos that he expects us to download and since the realtime logic
		# only detects images taken after they enter their polling loop we would miss those initial images)
		#
		if (g.fRetrievedMtpObjects == False and g.args['realtimedownload'] != 'only') or g.fRealTimeDownloadPhaseStarted\
			or secondsElapsed(g.appStartTimeEpoch) > g.args['rtd_maxsecsbeforeforceinitialobjlistget']:
			buildMtpObjects()
			g.fRetrievedMtpObjects = True
			
		#
		# do primary action
		#
		if g.args['action'] == 'listfiles':
			printMtpObjectDirectoryListing()
		else:
		
			applog_i("") # newline separator for logging

			#
			# download files. we skip this if if we're in realtime-only capture mode
			# and this isn't a recovery invocation (for recovery invocations we need
			# to download even in realtime-only mode to get any files we missed while
			# in recovery) and if we established an initial connection to the camera
			# fast enough to allow us to avoid worrying about missing any initial photos
			#
			if g.fRetrievedMtpObjects:
			
				if g.fRealTimeDownloadPhaseStarted or g.args['realtimedownload'] == 'only':
					#
					# either the realtime phase has already started (and so we're in a recovery
					# cycle) or we had to download all objectsbefore reaching the realtime phase
					# due to the time elapsed between app launchand when we were able to establish
					# our initial connection to the camera. we need to download any files we
					# potentially missed since launch or while performing recovery (plus also to support
					# the workflow where the user can turn WiFi off on the camera for as long as he
					# wants for intervals he doesn't want realtime capture). for this recovery
					# buildMtpObjects() retrieved all objects from the camera, including those captured
					# before the user launched airnefcmd. to exclude those files we set the capture date
					# filter to our app's launch time. rather than permanently keeping this capture date
					# filter in place for realtime operation we only set while perfomring downloadMtpFileObjects();
					# that way we're only sensitive to camera vs system time skew during the recovery
					# downloads (such as for camera models we don't support synching the clock to). the
					# launch-time capture date filter will be removed by realTimeCapture()
					#
					changeCaptureDateFilterToAppStartTime()
			
				downloadMtpFileObjects()
				g.dlstats.reportDownloadStats(g.fRealTimeDownloadPhaseStarted or g.args['realtimedownload'] == 'only') # don't print stats if no files downloaded if we're in realtime phase or in a session recovery of a realtime-only session

				
			#
			# enter realtime image download loop if enabled
			#
			if g.args['realtimedownload'] != 'disabled':
				realTimeCapture()
		
		#
		# successful completion
		#
		bEchoNewlineBeforeReturning = False
		return (0, False)
		
	except (mtpwifi.MtpConnectionFailureException, ssdp.DiscoverFailureException) as e:
		newConnectErrMsg = str(e)
		if newConnectErrMsg != appMain.lastConnectErrMsg or g.args['suppressdupconnecterrmsgs'] == 'no':
			applog_e(newConnectErrMsg)
			appMain.lastConnectErrMsg = newConnectErrMsg
		else:
			# don't do newline since we're keeping the last connection error message displayed
			bEchoNewlineBeforeReturning = False
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())				
		return (ERRNO_COULDNT_CONNECT_TO_CAMERA, True)
	except mtpwifi.MtpOpExecFailureException as e:
		applog_e(str(e))
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())				
		if e.mtpRespCode == MTP_RESP_COMMUNICATION_ERROR:
			bAttemptCloseSessionAtTermination = False	# since there was a communication error, no sense in attempting to close the MTP session (wastes time, will likely fail anyway)
			return (ERRNO_CAMERA_COMMUNICATION_FAILURE, True)
		else:
			return (ERRNO_CAMERA_UNEXPECTED_RESP_CODE, False) # don't retry on a high-level MTP error - we're trying to do something the camera doesn't like
	except mtpwifi.MtpProtocolException as e:
		applog_e(str(e))
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())
		bAttemptCloseSessionAtTermination = False	# since there was a communication error, no sense in attempting to close the MTP session (wastes time, will likely fail anyway)
		return (ERRNO_CAMERA_PROTOCOL_ERROR, True)
	except socket.error as e:
		applog_e("Socket Error: " + str(e))
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())
		bAttemptCloseSessionAtTermination = False	# since there was a communication error, no sense in attempting to close the MTP session (wastes time, will likely fail anyway)		
		if e.errno != 0: # make sure we're returning a non-zero exit code (not all socket exceptions can be relied on to do so)
			return (e.errno, True)
		else:
			# socket.timeout doesn't define errno. use errno.ETIMEDOUT. also in case the
			# other socket excpetions don't place an errno either
			return (errno.ETIMEDOUT, True)
	except IOError as e:
		applog_e("IOError: " + str(e))
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())
		return (e.errno, False)
	except KeyboardInterrupt as e:
		applog_e("\n>> Terminated by user keypress - cleaning up, please wait... <<")
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())			
		return (errno.EINTR, False)
	except SystemExit as e:
		#
		# someone called sys.exit(). we use sys.exit() for cases where the
		# error condition was captured by higher-level code and a user message
		# generated, thus to avoid printing an exception by this routine.
		# we can still retry these conditions - it depends on whether the caller
		# selected an errno within the "don't retry" range
		#
		if g.args['printstackframes'] == 'yes':
			applog_e(traceback.format_exc())			
		return (e.code, e.code < ERRNO_FIRST_CUSTOM_DONT_RETRY or  e.code > ERRNO_LAST_CUSTOM_DONT_RETRY)
	except: # capture remainder of exceptions, in particular syntax/programming exceptions
		applog_e("An exception occurred. Here is the stack trace information:\n" + traceback.format_exc()) # we always print stack frames for programming errors ('printstackframes' is  ignored)
		return (errno.EFAULT, False)
			
	finally:
		bEndMtpSessionIssuedSuccessfully = False
		if bAttemptCloseSessionAtTermination:
			#
			# end MTP session (MTP_OP_CloseSession). We avoid doing this if we got here from
			# a communication error, since the MTP_OP_CloseSession would likely fail
			# anyway and just take up extra time. However even if a communication error
			# didn't occur there are other situations where the MTP_OP_CloseSession we're about
			# to send might be expected to fail, such as if we were in the middle of an MTP
			# command when the user quit via KeyboardInterrupt. For this reason we squelch
			# any errors/exceptions that might occur during MTP_OP_CloseSession, only reporting
			# the exception to the debug log
			#
			try:
				endMtpSession()
				bEndMtpSessionIssuedSuccessfully = True
			except:
				applog_d("Exception during endMtpSession()")
				applog_d(traceback.format_exc())
		if g.cameraMake == CAMERA_MAKE_SONY:
			if bSessionStarted and (not bEndMtpSessionIssuedSuccessfully or g.args['camerasleepwhendone'] == 'no'):
				#
				# if we started a session and did not put the Sony camera to sleep afterwards then it
				# will remain in the 'Send to Computer' screen/mode. the camera will accept future TCP/IP
				# socket connections but will not respond to any MTP requests, so warn user about this
				#
				applog_i("\nBefore running airnef again please press 'Cancel' on your Sony camera's\n"\
						 "'Send to Computer' screen and select 'Send to Computer' again. Failing to\n"\
						 "do this will cause the next airnef session to not negotiate successfully.")
						 
		if bEchoNewlineBeforeReturning:
			applog_i("")
				
		closeSockets()


#
# deletes all files marked for deletion upon exit. this mechanism is necessary to
# delete a file we were downloading/writing but failed before the operation could
# completed. we don't want to leave a partially written file, otherwise the user
# might think it's a valid file
#
def deleteFilesMarkedForDeletionOnExit():
	for filenameWithPath in g.filesToDeleteOnAppExit:
		applog_d("deleteFilesMarkedForDeletionOnExit(): Processing {:s}".format(filenameWithPath))
		try: # ignore os.path.exists() errors
			if (os.path.exists(filenameWithPath)):
				applog_v("Deleting \"{:s}\" because of a failed download or file operation".format(filenameWithPath))
				deleteFileIgnoreErrors(filenameWithPath)
		except:
			pass

	
#
# main app routine
#			
def main():	

	#
	# establish our app environment, including our app-specific subdirectories
	#
	establishAppEnvironment()
	
	#
	# init applog, to allow logging of output to log files
	#
	_errno = applog_init(APPLOGF_LEVEL_INFORMATIONAL | APPLOGF_LEVEL_ERROR, os.path.join(g.appDataDir, "airnefcmd-log-last.txt"),\
		os.path.join(g.appDataDir, "airnefcmd-log-lifetime.txt"))
	if _errno:
		sys.exit(_errno)
	
	#
	# display app banner
	#
	applog_i("\nairnef v{:s} - Wireless transfer of images/movies for Nikon cameras [GPL v3]".format(AIRNEFCMD_APP_VERSION))
	applog_i("Copyright (c) TestCams.com, Time: {:s}, Py: {:d}.{:d}.{:d}, OS: {:s}\n".format(strutil.getDateTimeStr(fMilitaryTime=True),\
		sys.version_info.major, sys.version_info.minor, sys.version_info.micro,
		platform.system()))
	g.appStartTimeEpoch = time.time()
	
	#
	# verify we're running under a tested version of python
	#
	verifyPythonVersion()	
	
	#
	# process command line arguments
	#
	processCmdLine()
		
	#
	# do app's main work
	#
	attemptNumber = 0
	while True:	
		try:
		
			(_errno, retryRecommended) = appMain()
			if retryRecommended == False:
				# if successful or if user terminated app
				break;
				
			attemptNumber += 1
			if attemptNumber >= g.args['retrycount']:
				applog_i("\nNumber of attempts ({:d}) has reached maximum configured value - exiting".format(attemptNumber))
				break;
						
			# delay until next retry
			secondsToNextRetry = g.args['retrydelaysecs']			
			consoleWriteLine("\rDelaying {:d} seconds before retrying. Press <ctrl-c> to exit [{:d} attempts]: ".format(g.args['retrydelaysecs'], attemptNumber))
			while secondsToNextRetry:
				secondsToNextRetryStr = "{:d}".format(secondsToNextRetry)
				consoleWriteLine(secondsToNextRetryStr)				
				time.sleep(1)
				consoleWriteLine("\b" * len(secondsToNextRetryStr) + " " * len(secondsToNextRetryStr) + "\b" * len(secondsToNextRetryStr))
				secondsToNextRetry -= 1
			consoleClearLine()
			
		except KeyboardInterrupt as e: # in case <ctrl>-c is pressed in delay above
			try: 
				applog_e("\n>> Terminated by user keypress <<\n")
				_errno = errno.EINTR
			except KeyboardInterrupt as e:
				# for some reason we intermittently get a second SIGINT running on Linux frozen; ignore the 2nd
				pass
			break;

	#
	# cleanup and then exit
	#
	deleteFilesMarkedForDeletionOnExit()
	shutdownApplog()
	return _errno

#
# program entry point
#	
if __name__ == "__main__":
	_errno = main()
	sys.exit(_errno)
