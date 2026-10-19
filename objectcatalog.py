#!/usr/bin/env python

#
#############################################################################
#
# objectcatalog.py - Catalog of the camera's MTP objects: enumeration, object cache and user filters
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
import datetime
import sys
import os
import json
import mtpwifi
import strutil
import mtpbulk
from collections import namedtuple
from dlinkedlist import *
from applog import *
from mtpdef import *
from appstate import *
from mtpdatasets import mtpTimeStrToEpoch, parseMtpCountedWordList
from camerasession import getMtpObjectHandles, getMtpObjectInfo

		
#
# stats structure used by the createMtpObjectXX methods
# 
class CreateMtpObjectStatsStruct:
	def __init__(self):
		self.recursionNesting = 0
		self.countObjectsProcessed = 0
		self.countMtpObjectsAlreadyExisting = 0
		self.countCacheHits = 0

#
# used to maintain information about current file being downloaded
# across any retry/resumption attempts
# 
class PartialDownloadData():
	def __init__(self):
		self.bytesWritten = 0
		self.downloadTimeSecs = 0
		self.localFilenameWithoutPath = None
	def getBytesWritten(self):
		return self.bytesWritten
	def addBytesWritten(self, moreBytesWritten):
		self.bytesWritten += moreBytesWritten
	def getDownloadTimeSecs(self):
		return self.downloadTimeSecs
	def addDownloadTimeSecs(self, moreTimeSecs):
		self.downloadTimeSecs += moreTimeSecs
	def getLocalFilenameWithoutPath(self):
		return self.localFilenameWithoutPath
	def setLocalFilenameWithoutPath(self, localFilenameWithoutPath):
		self.localFilenameWithoutPath = localFilenameWithoutPath

#
# Main class to manage both individual MTP objects, including  files, directories, etc.., plus collections of these objects
#
class MtpObject(LinkedListObj):

	#
	# class variables
	#
	__MtpObjects_LL_CaptureDateSorted = LinkedList()	# link list of all MtpObject instances, sorted by capture date ([0] = oldest, [n-1]=newest)	
	__MtpObjects_ObjectHandleDict = {}					# dictionary of all objects, keyed by object handle 
	_CountMtpObjectDirectories = 0						# number MtpObjects that represent directories

	#
	# instance variables (documentation only since variables don't need to be declared in Python)
	# self.mtpObjectHandle:			Handle by which camera references this object
	# self.mtpObjectInfo: 			Structure containing information from MTP_OP_GetObjectInfo
	# self.captureDateEpoch:		self.mtpObjectInfo.captureDateStr converted to epoch time
	# self.bInTransferList:			TRUE if user selected this image for transfer in the camera
	# self.bDownloadedThisSession	TRUE if object has been downloaded successfully this session [for possible future retry logic, if implemented]
	#

	def __init__(self, mtpObjectHandle, mtpObjectInfo):
	
		# init some instance vars
		self.bInCameraTransferList = False
		self.bDownloadedThisSession = False
		self.partialDownloadData = None

		# save handle and object info to instance vars
		self.mtpObjectHandle = mtpObjectHandle
		self.mtpObjectInfo = mtpObjectInfo

		if isDebugLog():
			applog_d("Creating MtpObject with the following mtpObjectInfo:\n" + str(self))
		
		# calculate instance vars that are based on mtpObjectInfo data
		self.captureDateEpoch = 0
		if self.mtpObjectInfo.captureDateStr: # there is a non-empty capture date string
			self.captureDateEpoch = mtpTimeStrToEpoch(self.mtpObjectInfo.captureDateStr)
		else:
			#
			# Sony uses a date stamp for the filename of folders. Extract that as the date if this is a folder object. this is
			# important because we rely on folder timestamps for the MTP object cache logic
			#
			if self.mtpObjectInfo.associationType == MTP_OBJASSOC_GenericFolder:
				if len(self.mtpObjectInfo.filename)==10 and self.mtpObjectInfo.filename[4]=='-' and self.mtpObjectInfo.filename[7]=='-':
					# capture date is in in YYYY-MM-DD (Sony uses this for folders)
					self.captureDateEpoch = time.mktime( time.strptime(self.mtpObjectInfo.filename, "%Y-%m-%d"))			
			
		# make sure this object hasn't already been inserted
		if MtpObject.objInList(self):
			raise AssertionError("MtpObject: Attempting to insert mtpObjectHandle that's already in dictionary. newObj:\n{:s}, existingObj:\n{:s}".format(
				str(self), str(MtpObject.__MtpObjects_ObjectHandleDict[self.mtpObjectHandle])))

		# insert into capture-date sorted linked list
		LinkedListObj.__init__(self, self.captureDateEpoch, MtpObject.__MtpObjects_LL_CaptureDateSorted)
			
		# insert into object handle dictionary, which is used for quick lookups by object handle
		MtpObject.__MtpObjects_ObjectHandleDict[self.mtpObjectHandle] = self
		
		# update counts based on this object type
		if self.mtpObjectInfo.associationType == MTP_OBJASSOC_GenericFolder:
			MtpObject._CountMtpObjectDirectories += 1
					
	def setAsDownloadedThisSession(self):
		self.bDownloadedThisSession = True
		
	def wasDownloadedThisSession(self):
		return self.bDownloadedThisSession
		
	def isPartialDownload(self):
		return self.partialDownloadData != None
		
	def partialDownloadObj(self):
		if self.partialDownloadData:
			return self.partialDownloadData
		self.partialDownloadData = PartialDownloadData()
		return self.partialDownloadData
		
	def releasePartialDownloadObj(self):
		if self.partialDownloadData:
			self.partialDownloadData = None
			
	def getImmediateDirectory(self): # gets immediate camera directory that this object is in. ex: "100NC1J4"
		objHandleDirectory = self.mtpObjectInfo.parentObject
		if not objHandleDirectory:
			# no parent to this object
			return ""
		if objHandleDirectory not in MtpObject.__MtpObjects_ObjectHandleDict:
			applog_d("getImmediateDirectory(): Unable to locate parent object for {:s}, parent=0x{:08x}".format(self.mtpObjectInfo.filename, objHandleDirectory))
			return ""			
		dirObject = MtpObject.__MtpObjects_ObjectHandleDict[objHandleDirectory]
		return dirObject.mtpObjectInfo.filename		
							
	def genFullPathStr(self): # builds full path string to this object on camera, including filename itself. Ex: "DCIM\100NC1J4\DSC_2266.NEF"
		# full path built by walking up the parent object tree for this object, prepending the directory of each parent we find
		pathStr = self.mtpObjectInfo.filename
		objHandleAncestorDirectory = self.mtpObjectInfo.parentObject
		loopIterationCounter_EndlessLoopProtectionFromCorruptList = 0
		while (objHandleAncestorDirectory != 0):
			if objHandleAncestorDirectory not in MtpObject.__MtpObjects_ObjectHandleDict:
				# couldn't find next folder up. this shouldn't happen since we always pull down full directory tree for all objects
				applog_d("genFullPathStr(): Unable to locate parent object for {:s}, parent=0x{:08x}".format(self.mtpObjectInfo.filename, objHandleAncestorDirectory))
				return pathStr
			dirObject = MtpObject.__MtpObjects_ObjectHandleDict[objHandleAncestorDirectory]
			pathStr = dirObject.mtpObjectInfo.filename + "\\" + pathStr
			objHandleAncestorDirectory = dirObject.mtpObjectInfo.parentObject
			loopIterationCounter_EndlessLoopProtectionFromCorruptList += 1
			if loopIterationCounter_EndlessLoopProtectionFromCorruptList >= 512:	
				# 512 is arbitrary. wouldn't expect cameras to have more than one or two directory levels
				raise AssertionError("Endless loop detected while building directory chain for {:s}. Local list is corrupt".format(pathStr))
			
		return pathStr
									
	@classmethod
	def getCount(cls):	# returns count of objects
		return MtpObject.__MtpObjects_LL_CaptureDateSorted.count()
		
	@classmethod
	def getOldest(cls):	# returns oldest object in age collection
		if MtpObject.__MtpObjects_LL_CaptureDateSorted.count():		# if list is not empty
			return MtpObject.__MtpObjects_LL_CaptureDateSorted.head()
		else:
			return None
							
	@classmethod
	def getNewest(cls):	# returns newest object in age collection
		if MtpObject.__MtpObjects_LL_CaptureDateSorted.count():		# if list is not empty
			return MtpObject.__MtpObjects_LL_CaptureDateSorted.tail()
		else:
			return None
		
	def getNewer(self):	# returns next newer object
		return self.llNext()
			
	def getOlder(self):	# returns next older object
		return self.llPrev()

	@classmethod
	def getByMtpObjectHandle(cls, mtpObjectHandle):
		if mtpObjectHandle in MtpObject.__MtpObjects_ObjectHandleDict:
			return MtpObject.__MtpObjects_ObjectHandleDict[mtpObjectHandle]
		else:
			return None
			
	@classmethod
	def objInList(cls, mtpObj):		
		return mtpObj.mtpObjectHandle in MtpObject.__MtpObjects_ObjectHandleDict
			
			
	def __str__(self):	# generates string description of object
		s =  "MtpObject instance = 0x{:08x}\n".format(id(self))
		s += "  mtpObjectHandle = 0x{:08x}\n".format(self.mtpObjectHandle)
		s += "  --- mptObjectInfo ---\n"		
		s += "    storageId          = " + getMtpStorageIdDesc(self.mtpObjectInfo.storageId) + "\n"
		s += "    objectFormat       = " + getMtpObjFormatDesc(self.mtpObjectInfo.objectFormat) + "\n"
		s += "    protectionStatus   = " + strutil.hexShort(self.mtpObjectInfo.protectionStatus) + "\n"
		s += "    compressedSize     = " + strutil.hexWord(self.mtpObjectInfo.objectCompressedSize) + "\n"
		s += "    thumbFormat        = " + getMtpObjFormatDesc(self.mtpObjectInfo.thumbFormat) + "\n"
		s += "    thumbCompressedSize= " + strutil.hexWord(self.mtpObjectInfo.thumbCompressedSize) + "\n"
		s += "    thumbPixDimensions = " + str(self.mtpObjectInfo.thumbPixWidth) + "x" + str(self.mtpObjectInfo.thumbPixHeight) + "\n"
		s += "    imagePixDimensions = " + str(self.mtpObjectInfo.imagePixWidth) + "x" + str(self.mtpObjectInfo.imagePixHeight) + "\n"
		s += "    imageBitDepth      = " + str(self.mtpObjectInfo.imageBitDepth) + "\n"
		s += "    parentObject       = " + strutil.hexWord(self.mtpObjectInfo.parentObject) + "\n"
		s += "    associationType    = " + getObjAssocDesc(self.mtpObjectInfo.associationType) + "\n"
		s += "    associationDesc    = " + strutil.hexWord(self.mtpObjectInfo.associationDesc) + "\n"
		s += "    sequenceNumber     = " + strutil.hexWord(self.mtpObjectInfo.sequenceNumber) + "\n"
		s += "    filename           = " + self.genFullPathStr() + "\n"
		s += "    captureDateSt      = " + self.mtpObjectInfo.captureDateStr + "\n"
		s += "    modificationDateStr= " + self.mtpObjectInfo.modificationDateStr
		return s


#
# generates and saves a cache of all the MtpObjectInfo(s) we've retrieved this session.
# this is done to avoid having to re-retrieve these same MtpObjectInfo instances from
# the camera on subsequent sessions. the cache is a versioned JSON document: unlike the
# pickle format used by v1.x it can't execute code when loaded, doesn't depend on module
# names (the old frozen-OSX __main__ vs airnefcmd mismatch) and can be inspected by hand.
# the file is written to a temporary name and renamed so a crash never leaves half a cache
#
MTP_OBJ_CACHE_FORMAT_VERSION = 2		# v1 was the pickle-based "-objinfocache" file
MtpObjectInfoCacheTuple = namedtuple('MtpObjectInfoCacheTuple', 'mtpObjectInfoList objHandlesList timeSavedEpoch')

def getMtpObjectInfoCacheFilename():
	return g.cameraLocalMetadataPathAndRootName + "-objinfocache.json"

def saveMtpObjectsToDiskCache():

	if g.args['mtpobjcache'] == 'disabled' or g.args['mtpobjcache'] == 'readonly':
		return None

	deleteFileIgnoreErrors(g.cameraLocalMetadataPathAndRootName + "-objinfocache")	# obsolete pickle cache from airnef v1.x

	mtpObjectInfoCacheFilename = getMtpObjectInfoCacheFilename()
	entries = []
	mtpObject = MtpObject.getOldest()
	while mtpObject:
		entries.append([mtpObject.mtpObjectHandle] + list(mtpObject.mtpObjectInfo))
		mtpObject = mtpObject.getNewer()
	document = { 'formatVersion' : MTP_OBJ_CACHE_FORMAT_VERSION, 'timeSavedEpoch' : time.time(),
		'fields' : ['handle'] + list(MtpObjectInfoTuple._fields), 'objects' : entries }

	tempFilename = mtpObjectInfoCacheFilename + ".tmp"
	try:
		with open(tempFilename, "w", encoding='utf-8') as f:
			json.dump(document, f, ensure_ascii=False, separators=(',', ':'))
		os.replace(tempFilename, mtpObjectInfoCacheFilename)
	except (OSError, TypeError, ValueError) as e:
		applog_e("Error writing MTP object cache {:s}, cache will not be available next session: {:s}".format(mtpObjectInfoCacheFilename, str(e)))
		deleteFileIgnoreErrors(tempFilename)
		return None
	applog_d("Saved {:d} MTP objects to disk cache".format(len(entries)))

#
# loads the MtpObjectInfo cache info that was saved to disk on a previous session by
# saveMtpObjectsToDiskCache(). if the cache is loaded successfully and is structurally
# valid then a MtpObjectInfoCacheTuple is returned. note that even if the cache is loaded
# successfully the caller must perform his own coherency check to make sure the cache
# contents are valid vs the objects on the camera.
#
def loadMtpObjectInfoCacheFromDisk():

	if g.args['mtpobjcache'] == 'disabled':
		return None

	mtpObjectInfoCacheFilename = getMtpObjectInfoCacheFilename()
	if not os.path.exists(mtpObjectInfoCacheFilename):
		return None
	if g.args['mtpobjcache'] == 'writeonly':
		applog_v("Ignoring found MTP object cache file per user configuration")
		return None

	#
	# any problem reading or validating the file just means there is no cache this session -
	# the cache is only a performance optimization. a structurally invalid file is deleted
	#
	try:
		with open(mtpObjectInfoCacheFilename, encoding='utf-8') as f:
			document = json.load(f)
	except OSError as e:
		applog_e("I/O error reading MTP object cache {:s}: {:s}".format(mtpObjectInfoCacheFilename, str(e)))
		return None
	except ValueError as e:
		applog_e("MTP object cache {:s} is corrupt - will delete and ignore".format(mtpObjectInfoCacheFilename))
		deleteFileIgnoreErrors(mtpObjectInfoCacheFilename)
		return None
	try:
		if document['formatVersion'] != MTP_OBJ_CACHE_FORMAT_VERSION or document['fields'] != ['handle'] + list(MtpObjectInfoTuple._fields):
			raise ValueError("unsupported cache format")
		objHandlesList = []
		mtpObjectInfoList = []
		for entry in document['objects']:
			objHandlesList.append(int(entry[0]))
			mtpObjectInfoList.append(MtpObjectInfoTuple(*entry[1:]))
		mtpObjectInfoCacheTuple = MtpObjectInfoCacheTuple(mtpObjectInfoList, objHandlesList, float(document['timeSavedEpoch']))
	except (KeyError, TypeError, ValueError) as e:
		applog_v("Discarding MTP object cache {:s}: {:s}".format(mtpObjectInfoCacheFilename, str(e)))
		deleteFileIgnoreErrors(mtpObjectInfoCacheFilename)
		return None

	#
	# have valid cache
	#
	cacheAgeSeconds = secondsElapsed(mtpObjectInfoCacheTuple.timeSavedEpoch)

	# display cache info (verbose/debug)
	applog_v("MTP Object cache has {:d} objects, age is {:s}".\
		format(len(mtpObjectInfoCacheTuple.mtpObjectInfoList), str(datetime.timedelta(seconds=cacheAgeSeconds))))
	if isDebugLog():
		applog_d("MTP object cache entries [count={:d}]".format(len(mtpObjectInfoCacheTuple.mtpObjectInfoList)))
		for i in range(len(mtpObjectInfoCacheTuple.mtpObjectInfoList)):
			applog_d("Entry {:4d}, handle = 0x{:08x}: {:s}".format(i, mtpObjectInfoCacheTuple.objHandlesList[i], str(mtpObjectInfoCacheTuple.mtpObjectInfoList[i])))

	#
	# ignore (discard) cache if its older than the max configured age
	#
	if g.args['mtpobjcache_maxagemins'] != 0 and cacheAgeSeconds/60 >= g.args['mtpobjcache_maxagemins']:
		applog_v("Discarding MTP object cache due to age (max age is {:s})".format(str(datetime.timedelta(minutes=g.args['mtpobjcache_maxagemins']))))
		return None

	return mtpObjectInfoCacheTuple


#
# Loads the MPT object info cache from the previous session (if available) and validates
# the cache's coherency. The coherency must be checked because MTP object handles
# aren't guaranteed to be persistent across camera power cycles (per the MTP spec), which
# means an obj handle may refer to a different file on the camera than what we have
# cached from the previous airnef session. This makes the entire proposition of caching
# these objs a bit risky, but the performance beneifts are too great to ignore because
# MTP_OP_GetObjectInfo can operate very slowly on some Nikon bodies. Based on my
# experimentation both Nikon and Canon encode object handles based on the filename
# and/or directory, the slot the media card is in, etc... This of course means that
# object handles can be reused and become stale relative to our cache, such as when
# users reformat cards and the same directory and filenames get reused to new images.
# What's needed is a way to detect when the camera might have reused an object handle
# in this fashion, short of performing MTP_OP_GetObjectInfo for all handles and defeating
# the purporse of the cache in the first place. The solution I came up with is to perform
# a spot check of just the directory objects, ie we perform MTP_OP_GetObjectInfo's for
# the directories we have in our cache, and compare the downloaded copies to our cache.
# If any directory object mismatches, specifically the timestamps, this means it's
# nearly certain that we have a a stale object cache and need to discard it.
#
# The directory timestamps will mismatch for any number of reasons, some of which
# are listed below. All signify a stale cache except for #3, which we'll still
# invalidate for since it doesn't make sense to get tricky for such an uncommon usage case.
#
#   1) There's a different media card in the camera
#   2) The user formatted the same media card
#   3) The user moved the media card to a different slot (on Nikon this flips a bit in the handles)
#   3) The user modified one or more files with the card inserted in an SD reader (unlikely)
#
# It's important to note some observations about how Nikon and Camera maintain timestamps on
# folders. On Nikon, the base DCIM directory uses a fixed timestamp of "19800000T000000" and
# the timestamp is never updated. This would be bad since we're relying on the timestamps for
# this algorithm; luckily this behavior is limited to the base DCIM directory. For all
# subdirectories under DCIM (that actually hold images), Nikon sets the timestamp of the folder
# at the time the folder is created, either after a card format or when a new folder is created
# when the image count in a folder exceeds 999 or 9999. Luckily nether Canon or Nikon keep
# the timestamps of these subfolders updated thereafter - they always keep the same timestamp
# even when images are being added to them (technically a filesystem's folder timestamp should
# update when any file within it is updated - they're probably avoiding doing so for performance
# reasons) - this is lucky for us because if they were to update the timestampsthen our algorithm
# would always find mismatching folder timestamps whenever there are new images in the folder.
# Note that any new directories on the camera (not in our cache) don't influence the algorithm
# since their existence doesn't affect the coherency of the directories we do have cached. 
#
# When a cache has been successfully loaded and validated this function returns a dictionary
# where the key is the object handle and the value is the cached MtpObjectInfo - the caller
# can then use the dictionary to perform a O(1) lookup against the object handle list
# obtained from the camera to know which objects it has available in the cache and thus
# can avoid a time-consuming MTP_OP_GetObjectInfo oeration. If the cache could not be loaded
# or is corrupt or the user has the cache disabled via a command-line arg or if coherency
# check performed by this function determines the cache is stale then None is returned.
#
# FYI, here's some analysis of how Nikon encodes obj handles (from the D7200):
#
# 0x0a19018e for DCIM\100D7200\DSC_0398.NEF (slot 2)
#        ^^^ ----> the 0x18e is the filename number (398 in hex)
#       ^ -------> the 0 is the directory number, encoded in some form
#    ^ ----------> the A means slot 2
#
# 0x0a19418e for DCIM\101D7200\DSC_0398.NEF (slot 2)
#        ^^^ ----> the 0x18e is the filename number (398 in hex)
#       ^ -------> the 4 is the directory number, encoded in some form
#    ^ ----------> the A means slot 2
#
# 0x0919418e for DCIM\101D7200\DSC_0398.NEF (slot 1)
#        ^^^ ----> the 0x18e is the filename number (398 in hex)
#       ^ -------> the 4 is the directory number, encoded in some form
#    ^ ----------> the 9 means slot 1
#
def loadAndValidateMtpObjectInfoCacheFromDisk(objHandlesFromCameraList):

	mtpObjectInfoCacheTuple = loadMtpObjectInfoCacheFromDisk()
	if not mtpObjectInfoCacheTuple:
		# no cache found or it failed its integrity test or usage was disabled by user configuration, etc...
		return None
	
	#
	# build a set of the camera's current object handles so that we can quickly do memebership
	# tests of our cached object handles for the directory entries we're checking. any miss
	# means that the cached directory handle we have is no longer present on the camera (or
	# less likely, the same card was moved to a different slot so that the encoded slot 
	# number in Nikon's object handle will now be different). this doesn't absolutely mean that
	# our other (file) objects are invalid but it probably does, and either way to be safe
	# we'll discard the cache in this case
	#
	objHandlesFromCameraSet = set(objHandlesFromCameraList) 
		
	#
	# the following loop scans through all the cached objects to perform two tasks:
	#
	# 1) Validate all objects that are directory entries by downloading the objects at those handles and verifying
	#    the directories are identical in name, date, etc.. If there is a mismatch then that means the cached object
	#    info we have is stale and the cache needs to be discaded
	#
	# 2) Builds dictionary that hashes the cached object handles to cached cached MtpObjectInfo objects - we'll use this
	#    to match up the object handles in the MTP_OP_GetObjectInfo loop to know which objects we have cached and thus
	#    don't have to fetch from the camera
	#
	# The tasks are somewhat unrelated but I'm performing them in the same loop as an optimziation.
	#
	bInvalidateCache = False
	cachedMtpObjectInfoListDict = {}
	for nObjIndex in range(0, len(mtpObjectInfoCacheTuple.mtpObjectInfoList)):
	
		objHandle = mtpObjectInfoCacheTuple.objHandlesList[nObjIndex]
		cachedMtpObjectInfo = mtpObjectInfoCacheTuple.mtpObjectInfoList[nObjIndex]

		# put cached object in cache dictionary we're building
		cachedMtpObjectInfoListDict[objHandle] = cachedMtpObjectInfo
					
		if mtpObjectInfoCacheTuple.mtpObjectInfoList[nObjIndex].associationType != MTP_OBJASSOC_GenericFolder:
			# this object is not a directory - nothing more to do with it
			continue
			
		#
		# this is a directory object. first make sure that this object handle 
		# still exists on the camera by checking it against the object handle
		# list obtained from the camera. if the handle doesn't even exist then
		# we know the directory is gone and we can immediately establish the 
		# cache is stale
		#
		if objHandle not in objHandlesFromCameraSet:
			applog_d("MTP obj handle 0x{:08x} for cache directory object \"{:s}\" does not exist".format(objHandle, cachedMtpObjectInfo.filename))
			bInvalidateCache = True
			break

		#
		# the directory object handle still exists on the camera. now we need
		# to perform a MTP_OP_GetObjectInfo of the handle and compare it against
		# our cached copy to confirm its the same directory/timestamp
		#		
		try:
			applog_d("Validating MTP obj cache directory object \"{:s}\" on handle 0x{:08x}".format(cachedMtpObjectInfo.filename, objHandle))
			mtpObjectInfo = getMtpObjectInfo(objHandle)
		except mtpwifi.MtpOpExecFailureException as e:
			if e.mtpRespCode == MTP_RESP_COMMUNICATION_ERROR:
				# request failed for reasons other than camera reporting an MPT error on the
				# cmd itself (ie, delivery of command failed) propagate exception and leave
				raise
			#
			# request failed, which really shouldn't happen because we already know the
			# object handle should be valid, even if the object data associated with it
			# might be stale. since we can't determine whether its stale without
			# successfully completing a MTP_OP_GetObjectInfo we'll just invalidate
			#
			applog_d("MTP object cache validation of \"{:s}\" resulted in {:s}".format(cachedMtpObjectInfo.filename, str(e)))
			bInvalidateCache = True
			break
			
		#
		# obtained the object data from the camera. now compare against our cached copy
		#
		if mtpObjectInfo != cachedMtpObjectInfo:
			# mismatches - the most likely cause is the timestamp
			applog_v("Found mismatch in MTP object cached directory \"{:s}\"".format(cachedMtpObjectInfo.filename))
			applog_d("    Cached copy: {:s}".format(str(cachedMtpObjectInfo)))
			applog_d("Downloaded copy: {:s}".format(str(mtpObjectInfo)))
			bInvalidateCache = True
			break;
								
	if bInvalidateCache:
		# generate a message if the cache was invalidated for any reason
		applog_v("The MTP object cache was detected as stale and will be discarded")
		return None
		
	#
	# cached passed all the coherency checks. it's good! hopefully :)
	#
	return cachedMtpObjectInfoListDict


#
# creates an MTP object instance for a given MTP handle, optionally recursing to create
# the MTP objects for the directory tree referenced by the object
# 
def createMtpObjectFromHandle(objHandle, createMtpObjectStatsStruct=None, cachedMtpObjectInfoListDict=None, fFindAndCreateAntecendentDirs=True, mtpObjectInfo=None):

	if not createMtpObjectStatsStruct:
		# use dummy local copy
		createMtpObjectStatsStruct = CreateMtpObjectStatsStruct()

	#
	# endless-recursion detection
	#
	createMtpObjectStatsStruct.recursionNesting += 1	
	if createMtpObjectStatsStruct.recursionNesting >= 100: # 100 is arbitary
		raise AssertionError("Recursive loop detected while building directory tree createMtpObjectFromHandle()")

	mtpObj = MtpObject.getByMtpObjectHandle(objHandle)
	if mtpObj:
		applog_d("MtpObject for handle 0x{:08x} already exists, skipping".format(objHandle))
		createMtpObjectStatsStruct.countMtpObjectsAlreadyExisting += 1
	else:
		fIsInCache = False
		if mtpObjectInfo == None: # caller didn't already retrieive the info for this object
			fIsInCache = cachedMtpObjectInfoListDict and (objHandle in cachedMtpObjectInfoListDict)
			if fIsInCache and g.args['mtpobjcache'] != 'verify':
				# found mtpObjectInfo for this handle in the cache - use cached copy
				applog_d("Found objHandle 0x{:08x} in cache".format(objHandle))
				mtpObjectInfo = cachedMtpObjectInfoListDict[objHandle]
			else:
				# didn't find mtpObjectInfo for this handle in the cache or we're validating cache - get the mtpObjectInfo from the camera
				mtpObjectInfo = getMtpObjectInfo(objHandle)
				if fIsInCache:
					# we're validating cache
					if mtpObjectInfo != cachedMtpObjectInfoListDict[objHandle]:
						applog_e("Found MTP object cache mismatch for \"{:s}\" vs  \"{:s}\"".format(mtpObjectInfo.filename, cachedMtpObjectInfoListDict[objHandle].filename))
						applog_e("    Cached copy: {:s}".format(str(cachedMtpObjectInfoListDict[objHandle])))
						applog_e("Downloaded copy: {:s}".format(str(mtpObjectInfo)))
						sys.exit(ERRNO_MTP_OBJ_CACHE_VALIDATE_FAILED)

		#
		# recurse to create MTP objects for the directory tree referenced by this object if we're instructed to do
		# so and this object has a parent dir and no MtpObject exists for the parent already
		#
		if fFindAndCreateAntecendentDirs and mtpObjectInfo.parentObject and MtpObject.getByMtpObjectHandle(mtpObjectInfo.parentObject)==None:
			applog_d("Recursing to get parent dir of \"{:s}\" - objHandle=0x{:08x}, parent=0x{:08x}".format(mtpObjectInfo.filename, objHandle, mtpObjectInfo.parentObject))
			createMtpObjectFromHandle(mtpObjectInfo.parentObject, createMtpObjectStatsStruct, cachedMtpObjectInfoListDict, fFindAndCreateAntecendentDirs)				

		#
		# create instance of MtpObject for this MtpObjectInfo
		#
		mtpObj = MtpObject(objHandle, mtpObjectInfo)
		if fIsInCache:
			createMtpObjectStatsStruct.countCacheHits += 1
			
	createMtpObjectStatsStruct.countObjectsProcessed += 1
	createMtpObjectStatsStruct.recursionNesting -= 1
	return mtpObj

	
#
# creates MTP object instances for each handle in a list
# 
def createMtpObjectsFromHandleList(objHandlesList, createMtpObjectStatsStruct=None, cachedMtpObjectInfoListDict=None, fFindAndCreateAntecendentDirs=True):
	numObjectHandles = len(objHandlesList)
	for nObjIndex in range(0, numObjectHandles):
		consoleWriteLine("\rRetrieving list of images/files from camera: {:d}/{:d}     ".format(nObjIndex, numObjectHandles))
		createMtpObjectFromHandle(objHandlesList[nObjIndex], createMtpObjectStatsStruct, cachedMtpObjectInfoListDict, fFindAndCreateAntecendentDirs)
	consoleClearLine()
		

#
# retrieves the info for every object on the camera in a single transaction, using
# GetObjectPropList (MTP) or GetFilesystemManifest (PTP 1.1) when the camera supports them.
# this replaces one GetObjectInfo round trip per object, the slowest part of starting a
# session. returns ({ handle : MtpObjectInfoTuple }, description) or (None, None) if
# neither is supported or allowed, or the camera rejects the request
#
def fetchMtpObjectInfosInBulk():
	method = g.args['objinfomethod']
	if method == 'perobject' or g.args['mtpobjcache'] == 'verify':
		return (None, None)
	operationsSupported = g.mtpDeviceInfo.operationsSupportedSet
	defaultStorageId = g.storageId if g.storageId != MTP_STORAGEID_ALL_CARDS else 0
	attempts = []
	if method in ('auto', 'proplist') and (MTP_OP_GetObjectPropList in operationsSupported or method == 'proplist'):
		attempts.append(('GetObjectPropList', MTP_OP_GetObjectPropList,
			struct.pack('<5I', 0xFFFFFFFF, 0, 0xFFFFFFFF, 0, 0xFFFFFFFF),	# all objects, all formats, all properties, all depths
			lambda data : mtpbulk.objectInfosFromPropList(data, defaultStorageId)))
	if method in ('auto', 'manifest') and (MTP_OP_GetFilesystemManifest in operationsSupported or method == 'manifest'):
		attempts.append(('GetFilesystemManifest', MTP_OP_GetFilesystemManifest,
			struct.pack('<3I', g.storageId, 0, 0),
			mtpbulk.objectInfosFromFilesystemManifest))
	for (desc, mtpOp, args, parser) in attempts:
		consoleWriteLine("Retrieving list of images/files from camera ({:s})".format(desc))
		try:
			timeStart = secondsElapsed(None)
			mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, mtpOp, args)
			objectInfos = parser(mtpTcpCmdResult.dataReceived)
			applog_v("Retrieved info for {:d} objects via {:s} in {:.2f} seconds".format(len(objectInfos), desc, secondsElapsed(timeStart)))
			return (objectInfos, desc)
		except mtpwifi.MtpOpExecFailureException as e:
			if e.mtpRespCode == MTP_RESP_COMMUNICATION_ERROR:
				raise
			applog_d("{:s} not usable: {:s}".format(desc, str(e)))
		except mtpbulk.BulkDatasetError as e:
			applog_d("{:s} reply could not be parsed: {:s}".format(desc, str(e)))
		finally:
			consoleClearLine()
	return (None, None)


#
# Enumerates all MTP objects on the camera, creating instances of our MtpObject()
# class for each object found.
#
# Some Background: In MTP, every file and folder on the camera is represented by
# an MTP object, which contains information such as the file's type, name,
# size, image dimensions, timestamps, etc.. Rather than passing full objects
# around for each MTP command, every object is represented by a unique MTP
# object handle, which is an opaque (to us anyway) 32-bit handle.
#
# The full list of all object handles for a given media card can be quickly
# obtained via the MTP_OP_GetObjectHandles. Then the slow part comes - we have
# to perform a MTP_OP_GetObjectInfo against each of those handles to get
# the actual MTP object info (ie, filename, size, type, etc...). The process
# enumerating through all the handles via MTP_OP_GetObjectInfo was found to
# be intermittently very slow on Nikon cameras, esp when performed for the first
# time after the camera has been powered on or if the media card was swapped out
# while the camera was on. To help ameliorate this we cache the MTP objects
# across arnef sessions on a per camera and S/N basis, so that we can at least
# avoid having to download the same objects on subsequent sessions, assuming
# they still exist in the camera on those subsequent sessions. Caching has its
# risks because MTP states that the object handles aren't persistent across
# camera sessions - see the comments in loadAndValidateMtpObjectInfoCacheFromDisk()
# for details on how we maintain coherency of the cache.
#		
def buildMtpObjects(fReportObjectTotals=True):

	#
	# get full list of MTP objects for storage ID
	#
	fullObjHandlesList =  getMtpObjectHandles(g.storageId)
	countFullObjHandlesList = len(fullObjHandlesList)

	# check if camera has a transfer list (user-selected images on camera). if so, download it
	g.fAllObjsAreFromCameraTransferList = False
	if g.args['cameratransferlist'] != 'ignore':
		if g.fRealTimeDownloadPhaseStarted:
			raise AssertionError("buildMtpObjects(): Checking for transfer list but already entered realtime download phase!")	
		#
		# some Nikon models like J4 don't include MTP_OP_GetTransferList in their operationsSupportedSet even
		# though they support MTP_OP_GetTransferList
		#
		if MTP_OP_GetTransferList in g.mtpDeviceInfo.operationsSupportedSet or g.cameraMake == CAMERA_MAKE_NIKON: 
			try:
				mtpTcpCmdResult = mtpwifi.execMtpOp(g.socketPrimary, MTP_OP_GetTransferList)
				(objHandlesListToGet, bytesConsumed) = parseMtpCountedWordList(mtpTcpCmdResult.dataReceived)
				numObjectHandlesToGet = len(objHandlesListToGet)
				g.fAllObjsAreFromCameraTransferList = True
				applog_i("Transfer list detected in camera - {:d} images/file(s) will be downloaded".format(numObjectHandlesToGet))
			except mtpwifi.MtpOpExecFailureException as e:
				#
				# we ignore non-MTP_RESP_COMMUNICATION_ERROR errors, since it's normal for this
				# command to fail when the camera doesn't have a transfer list. Most bodies
				# return MTP_RESP_NoTransferList. The WU-1a returns 0xa081.
				#
				if (e.mtpRespCode == MTP_RESP_COMMUNICATION_ERROR):
					raise
				# else the error is normal and means the user didn't selected any images for upload in the camera
		# else camera does not support transfer lists					
		if not g.fAllObjsAreFromCameraTransferList:
			if g.args['cameratransferlist'] == 'exitifnotavail':
				applog_e("Camera reports no user-selected images/movies to transfer or not-supported")
				if g.args['realtimedownload'] == 'disabled':
					sys.exit(ERRNO_NO_CAMERA_TRANSFER_LIST)
				# even though 'exitifnotavail' is configured, realtime-download means we should proceed to realtime download
				# we don't need to retrieve the initial object list
				return
					
	if not g.fAllObjsAreFromCameraTransferList:
		#
		# not using a user-selected transfer list. use full MTP object list from the camera
		#
		objHandlesListToGet = fullObjHandlesList
		numObjectHandlesToGet = countFullObjHandlesList
	
	if isDebugLog():
		applog_d("All MTP object handles (count={:d}):".format(countFullObjHandlesList))
		applog_d(strutil.hexdump(struct.pack('<' + 'I'*countFullObjHandlesList, *fullObjHandlesList), bytesPerField=4, includeASCII=False))
		if g.fAllObjsAreFromCameraTransferList:
			applog_d("Transfer List MTP object handles (count={:d}):".format(numObjectHandlesToGet))
			applog_d(strutil.hexdump(struct.pack('<' + 'I'*numObjectHandlesToGet, *objHandlesListToGet), bytesPerField=4, includeASCII=False))
			

	#
	# first try to get the info for every object in a single request (GetObjectPropList or
	# GetFilesystemManifest). that is fresh data straight from the camera, so the disk cache
	# isn't needed. otherwise load the MtpObjectInfo cache from the previous session; if the
	# cache was not available or was found to be stale then cachedMtpObjectInfoListDict will be None
	#
	(cachedMtpObjectInfoListDict, bulkMethodDesc) = fetchMtpObjectInfosInBulk()
	if cachedMtpObjectInfoListDict is None:
		cachedMtpObjectInfoListDict = loadAndValidateMtpObjectInfoCacheFromDisk(fullObjHandlesList)

	#
	# create the MTP objects, downloading those not already in cache
	#
	createMtpObjectStatsStruct = CreateMtpObjectStatsStruct()
	createMtpObjectsFromHandleList(objHandlesListToGet, createMtpObjectStatsStruct, cachedMtpObjectInfoListDict, True)
	if fReportObjectTotals or isDebugLog(): # always report object totals when debug logging is enabled
		applog_i("Processed info for {:d} files/dirs [{:d} from {:s}, {:d} previous]".format(\
			createMtpObjectStatsStruct.countObjectsProcessed, createMtpObjectStatsStruct.countCacheHits,
			bulkMethodDesc if bulkMethodDesc else "object cache", createMtpObjectStatsStruct.countMtpObjectsAlreadyExisting))
	
	#
	# serialized object list to file to cache it for future sessions. if we're using
	# a camera transfer list (user-selected files) don't update the cache if all the
	# objects were satisified by the cache (otherwise we'd be overwriting the cache with
	# a smaller subset of the cache, throwing away all cached entries for objects not
	# on the transfer list) or if the number of objects in the transfer list is less
	# than half the number of cache entries, otherwise again we'd be ovewriting the
	# cache with a smaller subset
	#
	countObjectsInCache = len(cachedMtpObjectInfoListDict) if cachedMtpObjectInfoListDict else 0
	if g.fAllObjsAreFromCameraTransferList:
		if createMtpObjectStatsStruct.countCacheHits < createMtpObjectStatsStruct.countObjectsProcessed and createMtpObjectStatsStruct.countObjectsProcessed >= countObjectsInCache/2:
			saveMtpObjectsToDiskCache()
		else:
			applog_d("Not updating MPT cache for transferlist items")
		g.lastFullMtpHandleListProcessedByBuildMtpObjects = None
	else:
		saveMtpObjectsToDiskCache()
		g.lastFullMtpHandleListProcessedByBuildMtpObjects = fullObjHandlesList


#
# returns the file extension of an MTP-obtained filename
#
def extractMtpFileExtension(fileNameStr):
	fileExtensionPos = fileNameStr.rfind(".", 0)
	if fileExtensionPos == -1:
		return ""
	extensionStr = fileNameStr[fileExtensionPos+1:]
	return extensionStr	# may be empty string if there were no characters after final "." in filename	

	
#
# checks if the extension of an MTP filename is in a list of file extensions
#
def isMtpFilenameExtInList(mtpFilename, extList):
	extension = extractMtpFileExtension(mtpFilename).upper() # extList is uppercased during cmd-line processing
	if extension: # if filename has an extension
		if extension not in extList:
			return False
	else: # file has no extension
		if "<NOEXT>" not in extList:
			return False
	return True

	
#
# determines if an MTP object is a file object and if so, whether it passes
# the user-configured filter (ie, file should be processed)
#
def doesMtpObjectPassUserFileFilter(mtpObject, fPrintFilterAction=True):

	# first filter out objects that don't correspond to files
	if mtpObject.mtpObjectInfo.objectFormat == MTP_OBJFORMAT_Assocation or mtpObject.mtpObjectInfo.objectFormat == MTP_OBJFORMAT_NONE:
		if fPrintFilterAction:
			applog_d("Skipping {:s} - object is not file - {:s}".format(mtpObject.mtpObjectInfo.filename, getMtpObjFormatDesc(mtpObject.mtpObjectInfo.objectFormat)))
		return False

	if g.fAllObjsAreFromCameraTransferList == True:
		# all objects presently in list are from the camera transfer list, so all bypass user filters
		return True
		
	# filter against user-specified extensions
	if g.args['extlist'] and isMtpFilenameExtInList(mtpObject.mtpObjectInfo.filename, g.args['extlist']) == False:
			if fPrintFilterAction:
				applog_v("Skipping {:s} - filename extension not in user-specified list".format(mtpObject.mtpObjectInfo.filename))
			return False
		
	# filter against capture date range
	if g.objfilter_dateStartEpoch != None and mtpObject.captureDateEpoch < g.objfilter_dateStartEpoch:
		# user specified starting date filter and this object has a capture date earlier than specified filter
		if fPrintFilterAction:
			applog_v("Skipping {:s} - has capture date earlier than user-specified start date filter".format(mtpObject.mtpObjectInfo.filename))
		return False
	if g.objfilter_dateEndEpoch != None and mtpObject.captureDateEpoch > g.objfilter_dateEndEpoch:
		# user specified ending date filter and this object has a capture date later than specified filter
		if fPrintFilterAction:
			applog_v("Skipping {:s} - has capture date later than user-specified end date filter".format(mtpObject.mtpObjectInfo.filename))
		return False
		
	# filter against folders
	if g.args['onlyfolders']:
		cameraFolder = mtpObject.getImmediateDirectory()
		if (cameraFolder=="" and ("<ROOT>" not in g.args['onlyfolders'])) or cameraFolder not in g.args['onlyfolders']:
			# image is in root directory of camera and "<ROOT>" not in list, or image is in directory not in list
			if fPrintFilterAction:
				applog_v("Skipping {:s}\\{:s} - folder not in --onlyfolders".format(cameraFolder, mtpObject.mtpObjectInfo.filename))
			return False
	if g.args['excludefolders']:
		cameraFolder = mtpObject.getImmediateDirectory()
		if (cameraFolder=="" and "<ROOT>" in g.args['excludefolders']) or cameraFolder in g.args['excludefolders']:
			# image is in root directory of camera and "<root>" is in list, or image is in directory in list
			if fPrintFilterAction:
				applog_v("Skipping {:s}\\{:s} - folder in --excludefolders".format(cameraFolder, mtpObject.mtpObjectInfo.filename))
			return False

	# passes all user filters
	return True


#
# Returns the next MTP file object that passes the user-configured filters. This
# function is used in MTP file object enumeration loops. Call with -1 to start
# the enumeration. Returns None when there are no more file(s).
#	
def getNextUserFilteredMtpFileObject(prevObject, fileTransferOrder = FILE_TRANSFER_ORDER_USER_CONFIGURED):
	if prevObject == None:
		return None
	if fileTransferOrder == FILE_TRANSFER_ORDER_USER_CONFIGURED:
		fileTransferOrder = g.fileTransferOrder
	if prevObject == -1:
		mtpObject = MtpObject.getNewest() if fileTransferOrder==FILE_TRANSFER_ORDER_NEWEST_FIRST else MtpObject.getOldest()
	else:
		mtpObject = prevObject.getOlder() if fileTransferOrder==FILE_TRANSFER_ORDER_NEWEST_FIRST else prevObject.getNewer()	
	while mtpObject != None and not doesMtpObjectPassUserFileFilter(mtpObject):
		mtpObject = mtpObject.getOlder() if fileTransferOrder==FILE_TRANSFER_ORDER_NEWEST_FIRST else mtpObject.getNewer()	
	return mtpObject
