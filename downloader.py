#!/usr/bin/env python

#
#############################################################################
#
# downloader.py - Downloading files: history, renaming, partial transfers, --downloadexec and listings
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
import subprocess
import mtpwifi
import strutil
import rename
from collections import namedtuple
from applog import *
from mtpdef import *
from appstate import *
from camerasession import getMtpObjectInfo, getSlotIndexFromStorageId, mtpSessionKeepAlive
from objectcatalog import MtpObject, doesMtpObjectPassUserFileFilter, getNextUserFilteredMtpFileObject, isMtpFilenameExtInList

#
# returns the size of an object. ObjectInfo stores the size as a UINT32, so objects of 4GB or
# more report 0xFFFFFFFF there; for those the 64-bit ObjectSize property is queried instead
#
def getMtpObjectSize(mtpObject):
	size = mtpObject.mtpObjectInfo.objectCompressedSize
	if size != MTP_SIZE_UNKNOWN_32BIT:
		return size
	if MTP_OP_GetObjectPropValue in g.mtpDeviceInfo.operationsSupportedSet:
		try:
			mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetObjectPropValue, struct.pack('<II', mtpObject.mtpObjectHandle, MTP_OBJPROP_ObjectSize))
			if len(mtpTcpCmdResult.dataReceived) >= 8:
				(size64,) = struct.unpack('<Q', mtpTcpCmdResult.dataReceived[:8])
				return size64
		except mtpwifi.MtpOpExecFailureException as e:
			if e.mtpRespCode == MTP_RESP_COMMUNICATION_ERROR:
				raise
	applog_w("Warning: \"{:s}\" is 4GB or larger but the camera doesn't report its exact size - only the first 4GB can be downloaded".format(mtpObject.mtpObjectInfo.filename))
	return size


#
# generates the operation + arguments to read 'count' bytes at 'offset' of an object.
# GetPartialObject only has a 32-bit offset; beyond 4GB the 64-bit MTP or Nikon variant is used
#
def genGetPartialObjectRequest(objHandle, offset, count):
	if offset + count <= 0xFFFFFFFF:
		return (MTP_OP_GetPartialObject, struct.pack('<III', objHandle, offset, count))
	operationsSupported = g.mtpDeviceInfo.operationsSupportedSet
	if MTP_OP_GetPartialObject64 in operationsSupported:
		return (MTP_OP_GetPartialObject64, struct.pack('<IIII', objHandle, offset & 0xFFFFFFFF, offset >> 32, count))
	if MTP_OP_Nikon_GetPartialObjectEx in operationsSupported:
		return (MTP_OP_Nikon_GetPartialObjectEx, struct.pack('<IIIII', objHandle, offset & 0xFFFFFFFF, offset >> 32, count, 0))
	raise mtpwifi.MtpProtocolException("Camera doesn't support transfers beyond 4GB (no GetPartialObject64/GetPartialObjectEx)")


#
# generates a unique filename based on an original name by
# adding a -new-%d suffix, repeating until it finds a suffix
# number that's unique for the directory the file is in
#
def generateUniqueFilename(origFilenameWithPath):
	newSuffixCounter = 1
	while True:
		rootfilename = os.path.splitext(origFilenameWithPath)
		newFilename = "{:s}-new-{:d}{:s}".format(rootfilename[0], newSuffixCounter, rootfilename[1])
		if not os.path.exists(newFilename):
			return newFilename
		newSuffixCounter += 1
		

#
# prompts the user for a single-character selection (+enter),
# only allowing characters specfied in validKeyList. check
# is case-insensitive.
# 		
def promptWithSingleKeyResponse(promptStr, validKeyListStr):
	while True:
		key = input(promptStr).upper()
		if key and validKeyListStr.upper().find(key.upper()) != -1:
			return key			

	
#
# Open/create download history file for this camera. We use this file to track
# which images we've alread downloaded in previous invocations, allowing the
# user to optionally skip these files for this or future invocations. 
#
# The history file contains one line of text for every file downloaded. The text
# is separated into two areas - a 'key area' and an 'additional info' area. The key
# area doubles as a unique identifier for a particular file along with holding
# information about the file. The 'addtional info' area has extra info about the
# download of the file, including a time stamp of when it was download and the path
# it was downloaded to.
#
# Here's the format of the history line for a file:
#
# 	localFilenameWithoutPath::MTP capture data str::Size in human-readable comma form::::download date/time string::outputDirPathAbsolute
#
# Examples:
#	DSC_0094.NEF::20150804T120900::22,719,774:::05/05/15 13:44::c:\pics
#	DSC_2570.JPG.sthumb.jpg::20150828T112418::3,419,512::::09/02/15 22:22:43::c:\pics\vacation
#
# The 'key area' and 'additional info area' are demarcated by four consecutive colons.
# Each field within those areas are separated by two consecutive colons. The 'key area'
# has enough information to uniquely identify a file and protect against false history
# positives/negatives, since it's the combination of the (camera-generated) filename,
# capture date+time, and file size. The likelihood that the camera's reuse of the filename will 
# have the same capture date+time and size should be nearly impossible.
#
# Generation of the history text to store in the history file is simple. Loading and using that
# history for the skip-alreayd-downloaded feature (on subsequent sessions) requires a little more
# work. To accomplish this we load and parse the file into a Python dictionary, with the 'key area'
# serving as the dictionary key and the 'addtional info area' serving as the value. Before downloading
# a file we build the history key and additional area strings for this session and then do a membership
# test of the key string against the dictionary we built from the history; if the keys match and
# we've been instructed to skip matches for this session then we wont download the file. If those
# conditions aren't met then we do download the file and then use the built key/additional area strings
# to generate the history event in the file.
#
# Some additional notes:
#
# I use 'localFilenameWithoutPath' insead of 'mtpObject.mtpObjectInfo.filename' so that we can
# track separate history for different types of downloads of the same file (full-sized, small thumbnail,
# and large thumbnail). 
#
# Even if we've been instructed to ignore the history this session (ie, to download files even if
# they're in the history), we still store entries for files we download this session, to support
# the ability of future sessions to skip these files if the user desires.
#	
def loadDownloadHistory():
	downloadHistoryFilename = g.cameraLocalMetadataPathAndRootName + "-downloadhist";
	if g.downloadHistoryDict:
		downloadHistoryDict = g.downloadHistoryDict # we already have download history loaded this session
	else:
		downloadHistoryDict = dict() # in case load fails we'll return an empty dictionary
		if (os.path.exists(downloadHistoryFilename)):
			if g.args['downloadhistory'] == 'clear':
				#
				# user instructed clearing the history file. we'll delete the file but then recreate it to allow
				# history to be generated for the files we download this session. since we're deleting the history
				# file there wont be any history to use for this session, thus no files will be skipped this session
				#
				applog_v("Deleting download history file \"{:s}\" per user configuration".format(downloadHistoryFilename))
				os.remove(downloadHistoryFilename)
			else:
				#
				# load download history into a dictionary: the 'key area' (text before the '::::' separator)
				# is the dictionary key and the 'additional info area' (text after it) is the value
				#
				try:
					#
					# lines that can't be parsed (for example a final line truncated by a crash, which has no
					# trailing newline) are skipped individually rather than discarding the whole history
					#
					countCorruptLines = 0
					with open(downloadHistoryFilename, encoding='utf-8', errors='replace') as f:
						for line in f:
							line = line.rstrip('\r\n')
							posSeparator = line.find("::::")
							if posSeparator <= 0:
								if line:
									countCorruptLines += 1
								continue
							downloadHistoryDict[line[:posSeparator]] = line[posSeparator+4:]
					if countCorruptLines:
						applog_w("Download history file \"{:s}\" has {:d} unreadable line(s), which were skipped".format(downloadHistoryFilename, countCorruptLines))
					applog_v("Download history file \"{:s}\" loaded - {:d} entries".format(downloadHistoryFilename, len(downloadHistoryDict)))
				except IOError as e:
					applog_e("Error openg/reading download history file \"{:s}\". No history will be available this session.".format(downloadHistoryFilename))
		else:
			applog_v("Download history file \"{:s}\" not found - will create".format(downloadHistoryFilename))
			
		g.downloadHistoryDict = downloadHistoryDict
		
	#
	# re(open) the download history file for appending to support new history entries generated
	# this session. return both the download history dictionary and the reopened history file
	#
	fileDownloadHistory = open(downloadHistoryFilename, "a", encoding='utf-8')
	return (downloadHistoryDict, fileDownloadHistory)
	
	
#
# writes data to a file being downloaded from the camera. 
#			
def writeDataToDownloadedFile(fileHandleIfAlreadyOpen, filenameWithPath, data, bCloseAfterWriting, bIsAppending):
	applog_d("{:s} writing 0x{:x} bytes, closeAfterWriting={:d}".format(filenameWithPath, len(data), bCloseAfterWriting))
	#
	# during a download we use a .part name in case we exit abnormally without being able to
	# clean up (delete) the file - that way the user doesn't think he has a valid image/movie file
	# for incomplete downloads
	#
	fileNameTemp = filenameWithPath + ".part"
	fo = fileHandleIfAlreadyOpen
	try:
		if fo == None:
			if fileNameTemp not in g.filesToDeleteOnAppExit:
				#
				# add the file to the delete list in case either the write we're
				# about to perform fails or if the (potentially) ongoing download
				# fails. we do this because we don't want to leave a file around
				# which has only partailly downloaded data. it's up to the
				# caller to remove the file from the delete list when he deems
				# it safe - we can't do it here after writing in case we're only
				# writing one piece and the caller still wants to close the file,
				# such as after receiving a partial piece during an MTP error
				#
				g.filesToDeleteOnAppExit.append(fileNameTemp)
			if not bIsAppending:
				fo = open(fileNameTemp, "wb") # create/truncate and open for binary writing
			else:
				fo = open(fileNameTemp, "ab") # open for binary appending
		fo.write(data)
		if bCloseAfterWriting:
			fo.close()
			return None
		return fo		
	except IOError as e:
		if fo:
			fo.close()
		applog_e("\nError creating or writing to \"{:s}\". {:s}".format(filenameWithPath, str(e)))
		sys.exit(ERRNO_DOWNLOAD_FILE_OP_FAILED)


#
# generates a partial dictionary for use by rename.performRename() with
# keys common to all files this session
#	
def genRenameDictKeysCommonToAllMtpObjects():	
	renameDict = dict()
	renameDict['downloadDateEpoch'] = g.appStartTimeEpoch
	renameDict['cameramake'] = g.mtpDeviceInfo.manufacturerStr.split(' ')[0] # just use the first word. for example, Nikon returns "Nikon Corporation"
	renameDict['cameramodel'] = g.mtpDeviceInfo.modelStr
	renameDict['cameraserial'] = g.mtpDeviceInfo.serialNumberStr
	return renameDict

	
#
# updates a dictionary for use by rename.performRename() with keys specific
# to a particular MTP object
#	
def updateRenameDictKeysSpecificToMtpObject(renameDict, mtpObject, dlnum, dlnum_lifetime, localFilename=None, path=None):
	captureFilename = mtpObject.mtpObjectInfo.filename
	if not localFilename:
		localFilename = captureFilename
	if not path:
		path = g.args['outputdir']
	renameDict['path'] = path
	renameDict['filename'] = localFilename	
	renameDict['capturefilename'] = captureFilename
	renameDict['captureDateEpoch'] = mtpObject.captureDateEpoch
	renameDict['dlnum'] = dlnum+1
	renameDict['dlnum_lifetime'] = dlnum_lifetime+1
	renameDict['camerafolder'] = mtpObject.getImmediateDirectory()
	renameDict['slotnumber'] = getSlotIndexFromStorageId(mtpObject.mtpObjectInfo.storageId)


#
# uses the rename engine to generate a directory and filename. caller passes a fully-
# initialized rename dict
#	
def performDirAndFileRename(renameDict, fCreateDirs=False):
	filenameAfterRename = renameDict['filename']
	dirAfterRename = g.args['outputdir'] # note this may be an empty string when 'dirnamespec' was specified by user
	# note that syntax for both filenamespec and dirnamespec were verified during cmd-line arg parsing
	if g.args['dirnamespec']:
		dirAfterRename = os.path.join(dirAfterRename, rename.performRename(g.args['dirnamespec'], renameDict))
		if fCreateDirs and not os.path.exists(dirAfterRename):
			applog_v("Creating directory tree \"{:s}\"".format(dirAfterRename))
			os.makedirs(dirAfterRename)	
		renameDict['path'] = dirAfterRename # update dict with possible generated directory from above	
	if g.args['filenamespec']:
		filenameAfterRename = rename.performRename(g.args['filenamespec'], renameDict)
		if not filenameAfterRename:
			applog_e("--filenamespec resulted in an empty filename. Please review your specification string")
			sys.exit(ERRNO_FILENAMESPEC_RESULT_EMPTY_STR)
		if '/' in filenameAfterRename or '\\' in filenameAfterRename:
			applog_e("--filenamespec can not have a path or path characters in it ('/' or '\\')")
			sys.exit(ERRNO_FILENAMESPEC_HAS_PATH_CHARACTERS)
	dirAfterRenameAbsolute = os.path.abspath(dirAfterRename)
	return (dirAfterRenameAbsolute, filenameAfterRename)


#
# performs  launch of application and arguments specified in 'downloadexec' command-line option
#	
def doDownloadExec(renameDict, mtpObject):

	if g.args['downloadexec_extlist'] and isMtpFilenameExtInList(mtpObject.mtpObjectInfo.filename, g.args['downloadexec_extlist']) == False:
		return

	execArgs = []
	# note that syntax for rename args were verified during cmd-line arg parsing
	for arg in g.args['downloadexec']:
		renamedArg = rename.performRename(arg, renameDict)
		if renamedArg != "":
			if 'notildereplacement' not in g.args['downloadexec_options']:
				#
				# replace all tildes with dashes, to support passing arguments with leading - or --.
				# this mechanism must be used because any leading - or -- is intepreted by
				# argparse as an argument to ourselves
				#
				if execArgs: # only do this replacement on args that aren't the first, to allow tidles in application/script name
					renamedArg = renamedArg.replace('~', '-')				
			execArgs.append(renamedArg)
		else:
			#
			# rename resulted in an empty string, which is allowed. if this is the first
			# argument, which corresponds to the name of the app/script we're launching,
			# then treat this as a signal to not launch for this file. this capability
			# allows the use of @replace@ specifiers to create empty strings on files
			# that the user wants to skip
			#
			if not execArgs:
				# first arg - we'll skip exec for this file
				applog_v("Skipping 'downloadexec' for \"{:s}\" due to empty first argument of rename string".format(renameDict['filename']))
				break;
	applog_d("download exec args input: " + str(g.args['downloadexec']))
	applog_d("download exec args output: " + str(execArgs))
	if execArgs:
		applog_v("Launching 'downloadexec': {:s}".format(str(execArgs)))
		try:
			process = subprocess.Popen(execArgs)
		except:
			# different platforms can throw different platform-specific exceptions
			errStr = "Error launching for 'downloadexec' {:s}: {:s} {:s}".format(str(execArgs), str(sys.exc_info()[0]), str(sys.exc_info()[1]))
			if 'ignorelauncherror' in g.args['downloadexec_options']:
				applog_d(errStr)
				return
			applog_e(errStr)
			sys.exit(ERRNO_DOWNLOADEXEC_LAUNCH_ERROR)
		if 'wait' in g.args['downloadexec_options']:
			#
			# we're instructed to wait until launched app exits before
			# continuing to next download. we'll wait in a loop,
			# calling mtpSessionKeepAlive() to make sure the camera
			# keeps the MTP session going
			#
			timeLastCameraKeepAlive = None
			while process.poll() == None:
				timeLastCameraKeepAlive = mtpSessionKeepAlive(timeLastCameraKeepAlive)
				time.sleep(.10) # sleep for 100ms between each process completion check				
			retCode = process.wait()
			if 'exitonfailcode' in g.args['downloadexec_options']:
				if retCode != 0:
					applog_i("Exiting due to non-zero return code ({:d}) of launched app for '--downloadexec'".format(retCode))
					sys.exit(ERRNO_DOWNLOADEXEC_NON_ZERO_EXIT_CODE)
		if 'delay' in g.args['downloadexec_options']:
			time.sleep(5)
			
						
#
# determines if an MTP_RESP_* error encountered during a download was (likely) caused
# by the user deleting the file in the camera while we were downloading it
#	
def respErrorDuringDownload_checkIfFileDeletedOnCamera(mtpObject, localFilename, mtpOpExecFailureException):

	#
	# non-communication error (ie, camera completed request with MTP error).
	# some cameras like Canon allow users to delete images while in WiFi
	# mode (Nikon presently does not). On Canon the error observed when
	# transferring a file that gets deleted was MTP_RESP_GeneralError. Rather
	# than trying to parse specific MTP_RESP_* values instead perform a
	# MTP_OP_GetObjectInfo to see if the object still exists
	#
	applog_d("RESP error downloading \"{:s}\": {:s}".format(localFilename, getMtpRespDesc(mtpOpExecFailureException.mtpRespCode)))
	try:
		objectInfo = getMtpObjectInfo(mtpObject.mtpObjectHandle, False)
		# hmmm, MTP_OP_GetObjectInfo() completed successfully. doesn't appear file was deleted then
		return False
	except mtpwifi.MtpOpExecFailureException as e:
		# guess at which errors are indicactive of an object that was deleter
		mtpRespCodesIndicatingFileDeleted = [ MTP_RESP_InvalidObjectHandle, MTP_RESP_OperationNotSupported, MTP_RESP_ParameterNotSupported,\
			MTP_RESP_AccessDenied, MTP_RESP_PartialDeletion, MTP_RESP_NoValidObjectInfo, MTP_RESP_InvalidParentObject, MTP_RESP_InvalidParameter ]	
		if e.mtpRespCode in mtpRespCodesIndicatingFileDeleted:
			applog_e("Error downloading \"{:s}\" - file appears to have been deleted in-camera by user - ignoring ({:s}/{:s})".format(localFilename,\
				getMtpRespDesc(mtpOpExecFailureException.mtpRespCode), getMtpRespDesc(e.mtpRespCode)))
			return True
		# camera reported an error that we don't think corresponds to a deleted file
		return False


#
# download progress callback for MTP get requests issued by downloadMtpFileObjects().
# displays the progress to console as a percentage of completion.
#			
def downloadMtpFileObjects_DownloadProgressCallback(bytesReceivedAllCurrentPayloads, totalBytesExpectedAllCurrentPayloads, bytesReceivedPriorPayloads, totalFileSizeIfKnown):
	if not hasattr(downloadMtpFileObjects_DownloadProgressCallback, "lastPctPrinted"):
		downloadMtpFileObjects_DownloadProgressCallback.lastPctPrinted = -1 # static var to track last percentage printed, to avoid unnecessary updates

	bytesReceived = bytesReceivedAllCurrentPayloads + bytesReceivedPriorPayloads
	if totalFileSizeIfKnown:
		totalObjSizeBytes = totalFileSizeIfKnown
	else:
		totalObjSizeBytes = totalBytesExpectedAllCurrentPayloads		
	pctDone = int(float(bytesReceived) / totalObjSizeBytes * 100)
	if pctDone != downloadMtpFileObjects_DownloadProgressCallback.lastPctPrinted:
		# only update if it's changed. it's ok if we miss a single % update when switching files
		downloadMtpFileObjects_DownloadProgressCallback.lastPctPrinted = pctDone
		consoleWriteLine("\b\b\b{:2d}%".format(pctDone))


#
# Performs download of all file objects that pass the user-configured filters.
#
# When I first wrote this routine I was experiencing very flaky wireless behavior from
# all Nikon bodies I tested it with (D7200, J4, D750, WU-1a). About halfway through a
# NEF  download via MTP_OP_GetObject the transfer rate would become erratic and sometimes
# the camera would completely stop transferring and then eventually time out on a socket
# receive. It wouldn't do this on every file but about once every few files. To handle
# this behavior I added significant amounts of recovery logic, both in the low-levels
# of mtpwifi.py and the upper levels of this module (appMain), both of which were designed
# to retain any partially transferred data and allow the retry of downloads. Luckily when
# a Nikon body hits this condition it could  be revived by dropping the TCP/IP connection
# and restarting everything over again, from the opening of the TCP/IP socket through the
# MTP start session and back to this routine to retrieve the portion of the file we have
# left to download via MTP_OP_GetPartialObject.
#
# It later occured to me that the issue might be specific to Nikon's implementation of 
# MTP_OP_GetObject, as it appeared the camera's erratic behavior was related to how large
# the object was - JPEGs were fine but larger NEFs should issues and very large MOV
# files were the worst. It seemed the camera has some type of memory leak associated with
# the command, perhaps committing internal resources to the entire file rather than to each
# payload piece. So I experimented with transfers that relied solely MTP_OP_GetPartialObject,
# using varoius tranfers sizes, and confirmed my suspicion - there's a bug in Nikon's firmware
# related to large transfers, both from the atomic MTP_OP_GetObject request and also 
# large MTP_OP_GetPartialObject requests. Based on these results I rewrote this method
# to use only MTP_OP_GetPartialObject and with smaller transfer sizes and all the erratic
# Nikon behavior disappeared. Fortunately performance did not suffer - I found that using
# a transfer size of 1MB (vs the full object size in the orig implementation) yielded the
# same performance as the latter, and actually much better when you consider that we didn't
# have to go through time-consuming connection tear-downs and re-establishment cycles. On
# both my D7200 and J4 I see approx 2.3 MB/s of sustained xfer performance on the adhoc wifi
# conneciton when the camera is next to the computer.
#
# Resolving the transfer issue meant that all the retry logic I originally put in was now
# unnecessary. Rather than take it out I decided it best to leave it in place, to support
# any scenarios where the wifi connection can be marginal, such as when the camera is further
# away from the computer. I left the max-transfer size configurable, to allow for future
# tweaking/experimentation of different camera models, in g.maxGetObjTransferSize
#
def downloadMtpFileObjects(firstMtpObjectToDownload = None):

	#
	# load download history and open history file for writing for new history to be generated this session
	#
	(downloadHistoryDict, fileDownloadHistory) = loadDownloadHistory()
	fSkipDownloadedFiles = (g.args['downloadhistory'] != 'ignore') # skip files if instructed to do so
	
	#
	# various forms of the filename/path are used in this routine for different purposes. here's a guide to 
	# the variables that hold the filename/path
	#
	# filenameWithObjTypeSuffixBeforeRename - The capture filename with .sthumb.jpg or ".lthumb.jpg" optionally added
	# to it if we're downloading a thumbnail instead of the file. This filename is used as the key in the download history
	#
	# filenameAfterRename - Filename after optionally renaming it using the rename engine (if user used --filenamespec). If
	# the rename engine was not used then filenameAfterRename == filenameWithObjTypeSuffixBeforeRename
	#
	# dirAfterRename - Directory name generated optionally genreated if using the rename engine (if user used --filenamespec). If
	# the rename engine was not used then dirAfterRename == g.args['outputpath'] only
	#
	# localFilenameWithoutPath - Filename actually used to store downloaded image locally. It's set to filenameAfterRename plus
	# an optional suffix '-new-x' suffix in case dirAfterRename conflicted with an existing file.
	#
	# localFilenameWithPath - os.join(dirAfterRename, localFilenameWithoutPath)
	#
	# localFilenameWithPath_TemporaryFilename - localFilenameWithPath + ".part" (temporary filename until complete, then renamed
	# on disk to localFilenameWithPath)
	#
	# mtpObject.partialDownloadObj().getLocalFilenameWithoutPath() - To support recovery/resumption of interrupted downloads we
	# need to save the potentially unique filename generated with the '-new-x' suffix across invocations of this routine. For
	# the path of a retried invocation of this routine we simply regenerate the (same) path again (ie, use dirAfterRename) since
	# nothing should cause it o change change across invocations of this routine
	#
	
	
	fUsingRenameEngineForDirOrFile = g.args['filenamespec'] != None or g.args['dirnamespec'] != None
	fUsingRenameEngineForAnyParameter = fUsingRenameEngineForDirOrFile or g.args['downloadexec']
	if fUsingRenameEngineForAnyParameter:
		renameDict = genRenameDictKeysCommonToAllMtpObjects()		
		
	#
	# scan all objects and download each file that passes the user-configured filters
	#
	if firstMtpObjectToDownload == None:
		#
		# caller didn't specify specific starting point/object. we'll start at the
		# beginning of the object list if this is our first time downloading or at
		# the last file we were downloading/completed downloading if we're resuming
		# a download interrupted by error
		#
		mtpObject = g.downloadMtpFileObjects_LastMtpObjectDownload
		if mtpObject == None:
			mtpObject = getNextUserFilteredMtpFileObject(-1)
	else:
		#
		# caller passed in starting point/object. this object hasn't been checked
		# against the user filters so we'll do so now, skipping until we find
		# an object from the starting point that does pass, or return if no passing
		# object is found
		#
		mtpObject = firstMtpObjectToDownload
		while not doesMtpObjectPassUserFileFilter(mtpObject):
			mtpObject = getNextUserFilteredMtpFileObject(mtpObject)
			if mtpObject == None:
				return		
			
	fFirstLoopIteration = True # unfortunate hack because Python doesn't support do-while or post conditions on for loops
	while True:
	
		#
		# get next file object to process
		#
		if fFirstLoopIteration:
			# use first object set in 'mtpObject' before start of while loop
			fFirstLoopIteration = False
		else:
			mtpObject = getNextUserFilteredMtpFileObject(mtpObject)
						
		if not mtpObject:
			# no more files to process
			break
	
		if mtpObject.wasDownloadedThisSession():
			# file was already downloaded on a previous invocation of downloadMtpFileObjects()
			applog_d("Skipping {:s} - already downloaded this session".format(mtpObject.mtpObjectInfo.filename))
			continue
			
		g.downloadMtpFileObjects_LastMtpObjectDownload = mtpObject
				
		mtpOpGet = CmdLineActionToMtpTransferOpDict[g.args['action']]
		
		# build local filename that will hold image
		filenameWithObjTypeSuffixBeforeRename = mtpObject.mtpObjectInfo.filename
		if mtpOpGet == MTP_OP_GetThumb:
			filenameWithObjTypeSuffixBeforeRename += ".sthumb.jpg"
		elif mtpOpGet == MTP_OP_GetLargeThumb:
			filenameWithObjTypeSuffixBeforeRename += ".lthumb.jpg"
			
		#
		# perform rename engine on directory and/or filename if specified by user
		#
		if fUsingRenameEngineForAnyParameter:
			# update dict with fields that change for each file
			updateRenameDictKeysSpecificToMtpObject(renameDict, mtpObject, g.countFilesDownloadedPersistentAcrossStatsReset, len(downloadHistoryDict), filenameWithObjTypeSuffixBeforeRename)
		if fUsingRenameEngineForDirOrFile:
			(dirAfterRename, filenameAfterRename) = performDirAndFileRename(renameDict, True)
		else:
			filenameAfterRename = filenameWithObjTypeSuffixBeforeRename
			dirAfterRename = os.path.abspath(g.args['outputdir'])
			
			
		#
		# build download history description, which is used both to check if we've already
		# downloaded the file (to optionally skip it) and also to write the history for
		# this file if we do download it. to uniquely identify the file we use a combination
		# of the filename, capture date, and size - these three elements togethre should
		# prevent us from any false positives/negatives for future images. note that for
		# filename we use the original name with the appended sthumb/lthumb suffix if we'read
		# downloading thumbs - that way we can uniquely track the downloading of the thumbs vs
		# the actual image/video file. see the comments for loadDownloadHistory() for
		# more information on how the history is handled
		#
		# format:
		# 	filenameWithObjTypeSuffixBeforeRename::MTP capture data str::Size in human-readable comma form::::current time str::outputDirAnFilename
		# example:
		#   DSC_0094.NEF::20150804T120900::22,719,774:::05/05/15 13:44::c:\pics\DSC_0094.NEF
		#
		downloadHistoryDescStr_Key = "{:s}::{:s}::{:,}".format(filenameWithObjTypeSuffixBeforeRename, mtpObject.mtpObjectInfo.captureDateStr, mtpObject.mtpObjectInfo.objectCompressedSize)
		if fSkipDownloadedFiles and downloadHistoryDescStr_Key in downloadHistoryDict:
			#
			# this file is in history. put the 'additional info area' into a named tuple for clarity and then
			# log the information so the user knows the file has been skipped and when and where it was originally
			# downloaded. note that a file may have been previously  downloaded multiple times, which is possible
			# if the user instructed us to ignore history on one of those sessions - we only write the history on
			# the first/original download, thus the history reflects that instead a more recent re-download
			#
			DownloadHistoryElement = namedtuple('DownloadHistoryElement', 'dateDownloadedStr pathDownloadedToStr')
			listDownloadHistory = str.split(downloadHistoryDict[downloadHistoryDescStr_Key], '::') # each field of the additional info area is separated by two colons
			downloadHistoryElementTuple = DownloadHistoryElement(listDownloadHistory[0], listDownloadHistory[1])				
			applog_v("Skipping \"{:s}\" - downloaded on {:s} to \"{:s}\" ".\
				format(filenameWithObjTypeSuffixBeforeRename, downloadHistoryElementTuple.dateDownloadedStr, downloadHistoryElementTuple.pathDownloadedToStr))
			g.dlstats.countFilesSkippedDueToDownloadHistory += 1
			mtpObject.setAsDownloadedThisSession() # mark as downloaded so it wont be re-evaluated on subsequent scans
			continue
						
			
		#
		# check if the output file already exists (if this isn't a file we're resuming a
		# failed download on)
		#
		if mtpObject.partialDownloadObj().getLocalFilenameWithoutPath() == None:
			localFilenameWithoutPath = filenameAfterRename
			localFilenameWithPath = os.path.join(dirAfterRename, localFilenameWithoutPath)
			if (os.path.exists(localFilenameWithPath)):
				if g.args['ifexists'] == 'prompt':
					applog_i("\"{:s}\" exists".format(localFilenameWithPath))
					#
					# note that if the user takes too long to respond the MTP session may
					# time out. we'll recover but it'll look messy. need to implement a
					# multi-platform method  to poll for keys so that we can mtpSessionKeepAlive()
					# while we're waiting for a keypress (todo-todo)
					#
					keyResponse = promptWithSingleKeyResponse("(S)kip, (O)verwrite, (U)niquename, (E)xit [+enter]: ", 'soue')
				else:
					keyResponse = ''			
				if g.args['ifexists'] == 'skip' or keyResponse == 'S':
					if not keyResponse:
						applog_i("Skipping \"{:s}\" - file exists".format(localFilenameWithPath))
					g.dlstats.countFilesSkippedDueToFileExistingLocally += 1
					continue
				elif g.args['ifexists'] == 'overwrite' or keyResponse == 'O':
					if not keyResponse:
						applog_v("\"{:s}\" exists - will be overwritten".format(localFilenameWithPath))
					applog_d("{:s} - deleting existing file per user config".format(localFilenameWithPath))
					os.remove(localFilenameWithPath)
				elif g.args['ifexists'] == 'uniquename' or keyResponse == 'U':
					uniqueFilenameWithPath = generateUniqueFilename(localFilenameWithPath)
					uniqueFilenameWithoutPath = os.path.basename(uniqueFilenameWithPath)
					if not keyResponse:
						applog_v("\"{:s}\" exists - will write to \"{:s}\"".format(localFilenameWithPath, uniqueFilenameWithoutPath))
					localFilenameWithPath = uniqueFilenameWithPath
					localFilenameWithoutPath = uniqueFilenameWithoutPath
				elif g.args['ifexists'] == 'exit' or keyResponse == 'E':
					applog_i("\"{:s}\" exists - exiting per user config".format(localFilenameWithPath))
					sys.exit(ERRNO_FILE_EXISTS_USER_SPECIFIED_EXIT)
			#
			# save the local filename in case we had to generate a unique name and the
			# transfer fails this invocation (we'll need the potentially unique filename
			# on the retry invocation)
			#
			mtpObject.partialDownloadObj().setLocalFilenameWithoutPath(localFilenameWithoutPath)
					
		else:
			#
			# this is a retry of a failed transfer and we generated the
			# local filename when the transfer was started. we need to use
			# that originally generated name in case it involved creating
			# a unique filename due to an pre-existing local file
			#
			localFilenameWithoutPath = mtpObject.partialDownloadObj().getLocalFilenameWithoutPath()
			localFilenameWithPath = os.path.join(dirAfterRename, localFilenameWithoutPath)

		#
		# generate download history strings based on the final path and filename. note that the key
		# was already generated and is based on the pre-rename of the filename
		# 
		currentTimeStr = strutil.getDateTimeStr(fMilitaryTime=True)
		downloadHistoryDescStr_Info = "{:s}::{:s}\n".format(currentTimeStr, localFilenameWithPath)
		downloadHistoryDescStr_Full = downloadHistoryDescStr_Key + "::::" + downloadHistoryDescStr_Info
			
					
		# notify camera of acquisition start for this object if it was selected by the user in the camera (in camera transfer list)
		if g.fAllObjsAreFromCameraTransferList:
			mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_NotifyFileAcquisitionStart, struct.pack('<I', mtpObject.mtpObjectHandle))
		
		# get the object
		applog_d(">> {:s}".format(getMtpOpDesc(mtpOpGet)))
		
		consoleWriteLine("Downloading \"{:s}\":  0%".format(localFilenameWithoutPath))

		#
		# do the get/download
		#			
		bUsingGetPartialObject = (mtpOpGet == MTP_OP_GetObject) # as opposed to MTP_OP_GetThumb or MTP_OP_GetLargeThumb
		foDownloadedFile = None # no (new) data written to file yet this invocation
		fFileDeletedOnCamera = False
		localFilenameWithPath_TemporaryFilename = localFilenameWithPath + ".part"
		if bUsingGetPartialObject:
			
			try:

				#
				# we may have already written some of the file on a previous invocation. if
				# so it will be reflected in the partialDownloadObj()
				# 
				fileSizeBytes = getMtpObjectSize(mtpObject)
				bytesWritten = mtpObject.partialDownloadObj().getBytesWritten()
	
				if bytesWritten > 0:
					#
					# as a data integrity safeguard, make sure the size of the file is equal to
					# the number of bytes we think we've written
					#
					applog_d("{:s} - resuming download - bytesWritten=0x{:x}, fileSize=0x{:x}".format(localFilenameWithoutPath, bytesWritten, fileSizeBytes))
					if (os.path.exists(localFilenameWithPath_TemporaryFilename)):
						statInfo = os.stat(localFilenameWithPath_TemporaryFilename)
						if statInfo.st_size != bytesWritten:									
							raise AssertionError("About to resume download for \"{:s}\" but it's filesize is not equal the how much data we've already downloaded and written (expected 0x{:x}, actual 0x{:x}".format(localFilenameWithoutPath, bytesWritten, statInfo.st_size))
					else:
						raise AssertionError("About to resume download for \"{:s}\" but the file is missing. It should be present and have a size of 0x{:x}".format(localFilenameWithoutPath, bytesWritten))									

						
				#
				# note there's a corner case where bytesWritten can already
				# be equal to fileSizeBytes. this can happen if there was a
				# communication error on the previous invocation after we
				# received the final data payload but during the cmd response
				# phase. the logic below is designed to gracefully handle this case
				#

				#
				# loop to download and write each piece of the object. the size of each
				# transfer is constrained by g.maxGetObjTransferSize
				#
				offsetIntoImage = bytesWritten
				dataReceived = bytearray()	# appended in place; bytes += would recopy up to maxGetObjBufferSize per piece
				while offsetIntoImage < fileSizeBytes:
					bytesToDownloadThisPiece = min(g.maxGetObjTransferSize, fileSizeBytes-offsetIntoImage)
					if len(dataReceived)+bytesToDownloadThisPiece > g.maxGetObjBufferSize:
						# the amount of data we already have + size of this transfer would exceed our configure maxgetobjbuffersize - constrain it
						bytesToDownloadThisPiece -= (len(dataReceived)+bytesToDownloadThisPiece) - g.maxGetObjBufferSize
					if bytesToDownloadThisPiece == 0:
						# shouldn't happen
						raise AssertionError("bytesToDownloadThisPiece is zero! offset=0x{:x}, fileSize=0x{:x}, dataReceived=0x{:x}, max=0x{:x}/0x{:x}".format(\
							offsetIntoImage, fileSizeBytes, len(dataReceived), g.maxGetObjTransferSize, g.maxGetObjBufferSize))
					applog_d("{:s} - downloading next piece, offset=0x{:x}, count=0x{:x}".format(localFilenameWithoutPath, offsetIntoImage, bytesToDownloadThisPiece))
					timeStart = secondsElapsed(None)
					(mtpOpPartial, partialArgs) = genGetPartialObjectRequest(mtpObject.mtpObjectHandle, offsetIntoImage, bytesToDownloadThisPiece)
					mtpTcpCmdResultGetObj = mtpwifi.execMtpOp(g.socketPrimary, mtpOpPartial, partialArgs,\
						rxTxProgressFunc=lambda bytesReceivedAllCurrentPayloads, totalBytesExpectedAllCurrentPayloads :\
						downloadMtpFileObjects_DownloadProgressCallback(bytesReceivedAllCurrentPayloads, totalBytesExpectedAllCurrentPayloads, offsetIntoImage, fileSizeBytes))
					mtpObject.partialDownloadObj().addDownloadTimeSecs(secondsElapsed(timeStart))
												
					#
					# advance by the number of bytes the camera actually sent, not the number requested. ISO 15740
					# 10.5.27 lets the responder return fewer bytes (response parameter 1 holds the actual count);
					# advancing by the requested count would silently leave holes in the file
					#
					bytesReceivedThisPiece = len(mtpTcpCmdResultGetObj.dataReceived)
					if bytesReceivedThisPiece == 0 or bytesReceivedThisPiece > bytesToDownloadThisPiece:
						raise mtpwifi.MtpProtocolException("Camera Protocol Error: GetPartialObject returned 0x{:x} bytes for a request of 0x{:x} bytes at offset 0x{:x}".format(							bytesReceivedThisPiece, bytesToDownloadThisPiece, offsetIntoImage))
					dataReceived += mtpTcpCmdResultGetObj.dataReceived
					offsetIntoImage += bytesReceivedThisPiece

					bIsFinalPiece = (offsetIntoImage == fileSizeBytes)
					if bIsFinalPiece or len(dataReceived) >= g.maxGetObjBufferSize:
						# we've reached/exceeded our max buffer size or this is the final piece. write out the data we have
						foDownloadedFile = writeDataToDownloadedFile(foDownloadedFile, localFilenameWithPath, dataReceived, bIsFinalPiece, (bytesWritten != 0)) # close file if this is the last piece
						mtpObject.partialDownloadObj().addBytesWritten(len(dataReceived))
						bytesWritten += len(dataReceived)
						dataReceived = bytearray()

				#
				# we've completed the download and writing of the file
				#
				fileDownloadTimeSecs = mtpObject.partialDownloadObj().getDownloadTimeSecs()
				
			except mtpwifi.MtpOpExecFailureException as e:

				applog_i("") # newline since console is on "Downloading ...." message

				if e.mtpRespCode != MTP_RESP_COMMUNICATION_ERROR and respErrorDuringDownload_checkIfFileDeletedOnCamera(mtpObject, localFilenameWithoutPath, e):
					# file was deleted on camera - ignore error so we can move on to next file
					fFileDeletedOnCamera = True
						
				if fFileDeletedOnCamera == False:
			
					mtpObject.partialDownloadObj().addDownloadTimeSecs(secondsElapsed(timeStart))
					applog_d("{:s} - error during download, writing 0x{:x} bytes of buffered data".format(localFilenameWithoutPath, len(dataReceived)))
					
					# flush out any unwritten data we have in 'dataReceived'
					if dataReceived:
						foDownloadedFile = writeDataToDownloadedFile(foDownloadedFile, localFilenameWithPath, dataReceived, False, (bytesWritten != 0))
						bytesWritten += len(dataReceived)
						mtpObject.partialDownloadObj().addBytesWritten(len(dataReceived))
					if e.partialData:
						#
						# more data was received before the communication failure. write
						# that partial data to the file so that we don't have to incur the
						# performance penalty of re-downloading it on the next retry invocation
						# 
						applog_d("{:s} - writing partial payload data of 0x{:x} bytes".format(localFilenameWithoutPath, len(e.partialData)))
						foDownloadedFile = writeDataToDownloadedFile(foDownloadedFile, localFilenameWithPath, e.partialData, False, (bytesWritten != 0))
						bytesWritten += len(e.partialData)
						mtpObject.partialDownloadObj().addBytesWritten(len(e.partialData))
					if foDownloadedFile:
						foDownloadedFile.close()
					raise
					
		else: # else of if bUsingGetPartialObject

			timeStart = secondsElapsed(None)
			try:
				mtpTcpCmdResultGetObj = mtpwifi.execMtpOp(g.socketPrimary, mtpOpGet, struct.pack('<I', mtpObject.mtpObjectHandle),\
					rxTxProgressFunc=lambda bytesReceivedAllCurrentPayloads, totalBytesExpectedAllCurrentPayloads : downloadMtpFileObjects_DownloadProgressCallback(bytesReceivedAllCurrentPayloads, totalBytesExpectedAllCurrentPayloads, 0, 0))
				dataReceived = mtpTcpCmdResultGetObj.dataReceived
				fileDownloadTimeSecs = secondsElapsed(timeStart)
				fileSizeBytes = len(dataReceived)
				writeDataToDownloadedFile(foDownloadedFile, localFilenameWithPath, dataReceived, True, False)					
			except mtpwifi.MtpOpExecFailureException as e:
				applog_i("") # newline since console is on "Downloading ...." message
				if e.mtpRespCode != MTP_RESP_COMMUNICATION_ERROR and respErrorDuringDownload_checkIfFileDeletedOnCamera(mtpObject, localFilenameWithoutPath, e):
					# file was deleted on camera - ignore error so we can move on to next file
					fFileDeletedOnCamera = True
				else:
					# error doesn't appear to be due to a file deleted in camera
					raise

		#
		# this completion path is common for both the get-object case and the small/large thumb case
		# both paths are required to have these vars set:
		#
		#		fileDownloadTimeSecs - total download time of file
		#		fileSizeBytes - size of file
		#
		# now write data to file. for the get-object case this will be the last piece of
		# data received for the file (after zero or more other pieces have already
		# been written). for the small/large thumb case this will always been the
		# only piece of data for the file
		#
		consoleClearLine()	# erase "Downloading..." status line
		
		if not fFileDeletedOnCamera:
		
			# success
									
			#
			# mark the file as downloaded. this means any exception that occurs
			# in logic after marking the download complete wont trigger a re-download
			# on a subsequent invocation of this routine. as such, be careful where
			# any future logic is place relative to this sentinel
			#
			mtpObject.setAsDownloadedThisSession()
			mtpObject.releasePartialDownloadObj()
			os.rename(localFilenameWithPath_TemporaryFilename, localFilenameWithPath) # download done - safe to rename to final filename
			g.filesToDeleteOnAppExit.remove(localFilenameWithPath_TemporaryFilename)
			
			#
			# print download completion message with transfer rate calculation
			#
			if fileDownloadTimeSecs > 0: # avoid divide-by-zero, though not expecting ever expecting 'fileDownloadTimeSecs' to be zero
				thisFileDownloadRateMbSec = fileSizeBytes / fileDownloadTimeSecs / 1048576
			else:
				thisFileDownloadRateMbSec = 0
			applog_i("{:s} [size = {:,}] in {:.2f} seconds ({:.2f} MB/s)".format(localFilenameWithPath,\
				fileSizeBytes, fileDownloadTimeSecs, thisFileDownloadRateMbSec))
									
			#
			# update running stats and mark the file as downloaded
			#
			g.dlstats.totalDownloadTimeSecs += fileDownloadTimeSecs
			g.dlstats.totalBytesDownloaded += fileSizeBytes
			g.dlstats.countFilesDownloaded += 1
			g.countFilesDownloadedPersistentAcrossStatsReset += 1


			#
			# notify camera of acquisition end for this object if it was selected by the user in the camera (in camera transfer list).
			# this action removes the image/file from the transfer list in the camera
			#
			if g.fAllObjsAreFromCameraTransferList:
				mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_NotifyFileAcquisitionEnd, struct.pack('<I', mtpObject.mtpObjectHandle))

			#
			# add this file to the download history file. also note when
			# fSkipDownloadedFiles==FALSE (user specified to ignore download history and
			# force download), there may already be an entry in the history file for
			# this image - to prevent duplicates we check membership first
			#
			if downloadHistoryDescStr_Key not in downloadHistoryDict:
				# if this file is not already in the history
				fileDownloadHistory.write(downloadHistoryDescStr_Full)
				fileDownloadHistory.flush()
				# add file to the in-memory copy of the history
				downloadHistoryDict[downloadHistoryDescStr_Key] = downloadHistoryDescStr_Info

									
			#
			# set the file's last modification+access time to the original creation
			# time reported that the camera reported for this object, which is the
			# behavior the user gets when he transfers images off the camera or media
			# card directly. note that we're doing this *after* we've marked the download
			# complete - the call to os.utime() is not critical in terms of retrying it,
			# so we still want to consider the download/file complete even if this call fails
			#
			os.utime(localFilenameWithPath, (mtpObject.captureDateEpoch, mtpObject.captureDateEpoch))
			
			#
			# launch optional user-specific program for this downloaded file
			#
			if g.args['downloadexec']:
				renameDict['filename'] = localFilenameWithoutPath # update dict in case filename changed due to ifexists unique creation
				doDownloadExec(renameDict, mtpObject)
					
		else:
			
			#
			# file was deleted on the camera before/during the download. we could delete the
			# object but instead we'll just mark it as downloaded so it'll be skip on any future
			# loop (same result)
			#
			if foDownloadedFile:
				foDownloadedFile.close()			
			mtpObject.setAsDownloadedThisSession()
			mtpObject.releasePartialDownloadObj()
			
			#
			# delete the partially-downloaded portion of file (if any of it was written
			# before we detected the deletion)
			#
			if localFilenameWithPath_TemporaryFilename in g.filesToDeleteOnAppExit:
				deleteFileIgnoreErrors(localFilenameWithPath_TemporaryFilename)
				g.filesToDeleteOnAppExit.remove(localFilenameWithPath_TemporaryFilename)
				

	# do any post-operation cleanup
	fileDownloadHistory.close()	
		

#
# prints a directory listing of all MTP file objects that pass the user-configured filters
#
def printMtpObjectDirectoryListing():	

	applog_i("") # newline separator for logging

	fUsingRenameEngine = g.args['filenamespec'] != None or g.args['dirnamespec'] != None
	if fUsingRenameEngine:
		renameDict = genRenameDictKeysCommonToAllMtpObjects()
		
	#
	# scan all objects and generate listing for each file that passes the user-configured filters
	#
	totalBytesOfImagesInObjectsListed = 0
	countFilesListed = 0
	mtpObject = getNextUserFilteredMtpFileObject(-1)
	while mtpObject:
	
		if fUsingRenameEngine:		
			# update dict with fields that change for each file. note we're using session download count as lifetime for the preview of the renaming
			updateRenameDictKeysSpecificToMtpObject(renameDict, mtpObject, countFilesListed, countFilesListed)
			(dirAfterRename, filenameAfterRename) = performDirAndFileRename(renameDict, False)
			dirAndFilenameAfterRename = os.path.join(dirAfterRename, filenameAfterRename)
	
		#
		# print information about this file
		#
		timeStr = strutil.getDateTimeStr(mtpObject.captureDateEpoch, fMilitaryTime=False)
		sizeStr = "{:13,}".format(mtpObject.mtpObjectInfo.objectCompressedSize)
		fullPathStr = mtpObject.genFullPathStr()
		if g.countCardsUsed > 1:
			# prepend slot number of file to path string
			fullPathStr = "CARD{:d}\\".format(getSlotIndexFromStorageId(mtpObject.mtpObjectInfo.storageId)) + fullPathStr		
		if not fUsingRenameEngine:
			applog_i("{:s}  {:s} {:s}".format(timeStr, sizeStr, fullPathStr))
		else:
			applog_i("{:s}  {:s} {:s} -> {:s}".format(timeStr, sizeStr, fullPathStr, dirAndFilenameAfterRename))
		totalBytesOfImagesInObjectsListed += mtpObject.mtpObjectInfo.objectCompressedSize
		countFilesListed += 1
		# get next file that passes user-configured filters
		mtpObject = getNextUserFilteredMtpFileObject(mtpObject)
	
	#
	# print listing summary
	#		
	applog_i("        {:4d} File(s)  {:13,} bytes".format(countFilesListed, totalBytesOfImagesInObjectsListed))
	applog_i("        {:4d} Dir(s)  {:13,} bytes free {:s}".format(MtpObject._CountMtpObjectDirectories, g.mtpStorageInfoList[0].freeSpaceBytes,\
				"[CARD 1]" if g.countCardsUsed > 1 else ""))
	for cardIndex in range(1, g.countCardsUsed):
		applog_i("                     {:13,} bytes free [CARD {:d}]".format(g.mtpStorageInfoList[cardIndex].freeSpaceBytes, cardIndex+1))
