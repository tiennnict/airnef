#!/usr/bin/env python

#
#############################################################################
#
# mtpbulk.py - Parsers for bulk object enumeration datasets
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Enumerating a card with one GetObjectInfo per object costs a full request/response
# round trip for every file, which is very slow over WiFi. Two operations return the
# information for every object in a single transaction:
#
#   GetObjectPropList (MTP 0x9805)         - list of (handle, property, value) elements
#   GetFilesystemManifest (PTP 1.1 0x1023) - array of ObjectFilesystemInfo datasets
#                                            (ISO 15740:2013 5.5.6 / 10.5.35)
#
# The parsers here turn either reply into the same MtpObjectInfoTuple produced by
# GetObjectInfo so the rest of airnef doesn't care which method was used. Fields the
# bulk datasets don't carry (thumbnail/image dimensions etc.) are reported as 0.
#
#############################################################################
#

import struct
from .mtpdef import *


class BulkDatasetError(Exception):
	pass


#
# parses a PTP string (UINT8 character count including the NULL, then UTF-16LE).
# returns (string, bytes consumed)
#
def parsePtpString(data, offset):
	if offset >= len(data):
		raise BulkDatasetError("string runs past end of dataset")
	countChars = data[offset]
	if countChars == 0:
		return "", 1
	end = offset + 1 + countChars*2
	if end > len(data):
		raise BulkDatasetError("string runs past end of dataset")
	text = data[offset+1:end].decode('utf-16-le', errors='replace').rstrip('\x00')
	return text, 1 + countChars*2


#
# parses one value of the given PTP datatype. returns (value, bytes consumed). array values
# are returned as lists
#
def parsePtpValue(data, offset, datatype):
	if datatype == PTP_DATATYPE_STRING:
		return parsePtpString(data, offset)
	if datatype & PTP_DATATYPE_ARRAY_FLAG:
		elementType = datatype & ~PTP_DATATYPE_ARRAY_FLAG
		if elementType not in PtpScalarDatatypeSizes or offset + 4 > len(data):
			raise BulkDatasetError("unsupported array datatype 0x{:04x}".format(datatype))
		(count,) = struct.unpack('<I', data[offset:offset+4])
		consumed = 4
		values = []
		for i in range(count):
			(value, n) = parsePtpValue(data, offset + consumed, elementType)
			values.append(value)
			consumed += n
		return values, consumed
	size = PtpScalarDatatypeSizes.get(datatype)
	if size is None:
		raise BulkDatasetError("unsupported datatype 0x{:04x}".format(datatype))
	if offset + size > len(data):
		raise BulkDatasetError("value runs past end of dataset")
	value = int.from_bytes(data[offset:offset+size], 'little', signed=(datatype in PtpScalarDatatypeSigned))
	return value, size


#
# parses a GetObjectPropList reply into { handle : { propCode : value } }
#
def parseObjectPropList(data):
	if len(data) < 4:
		raise BulkDatasetError("object property list too short")
	(countElements,) = struct.unpack('<I', data[0:4])
	offset = 4
	objects = {}
	for i in range(countElements):
		if offset + 8 > len(data):
			raise BulkDatasetError("object property list truncated")
		(handle, propCode, datatype) = struct.unpack('<IHH', data[offset:offset+8])
		offset += 8
		(value, consumed) = parsePtpValue(data, offset, datatype)
		offset += consumed
		objects.setdefault(handle, {})[propCode] = value
	return objects


#
# builds an MtpObjectInfoTuple from the properties of one object. returns None if the
# properties needed to describe a file are missing
#
def objectInfoFromProps(props, defaultStorageId):
	if MTP_OBJPROP_ObjectFileName not in props or MTP_OBJPROP_ObjectFormat not in props:
		return None
	dateCreated = props.get(MTP_OBJPROP_DateCreated) or props.get(MTP_OBJPROP_DateModified) or ''
	dateModified = props.get(MTP_OBJPROP_DateModified) or dateCreated
	return MtpObjectInfoTuple(
		props.get(MTP_OBJPROP_StorageID, defaultStorageId), props[MTP_OBJPROP_ObjectFormat],
		props.get(MTP_OBJPROP_ProtectionStatus, 0), props.get(MTP_OBJPROP_ObjectSize, 0),
		0, 0, 0, 0, 0, 0, 0,
		props.get(MTP_OBJPROP_ParentObject, 0), props.get(MTP_OBJPROP_AssociationType, 0),
		props.get(MTP_OBJPROP_AssociationDesc, 0), 0,
		props[MTP_OBJPROP_ObjectFileName], dateCreated[:15], dateModified[:15])


#
# parses a GetObjectPropList reply into { handle : MtpObjectInfoTuple }
#
def objectInfosFromPropList(data, defaultStorageId):
	result = {}
	for (handle, props) in parseObjectPropList(data).items():
		objectInfo = objectInfoFromProps(props, defaultStorageId)
		if objectInfo:
			result[handle] = objectInfo
	return result


#
# parses a GetFilesystemManifest reply (array of ObjectFilesystemInfo datasets, ISO 15740:2013
# table 16/25) into { handle : MtpObjectInfoTuple }. the manifest has no capture date, so the
# modification date (which cameras set when the image is written) is used for both
#
def objectInfosFromFilesystemManifest(data):
	if len(data) < 8:
		raise BulkDatasetError("filesystem manifest too short")
	(countElements,) = struct.unpack('<Q', data[0:8])
	offset = 8
	result = {}
	for i in range(countElements):
		if offset + 34 > len(data):
			raise BulkDatasetError("filesystem manifest truncated")
		(handle, storageId, objectFormat, protectionStatus, size, parent, assocType, assocDesc, sequenceNumber) = \
			struct.unpack('<IIHHQIHII', data[offset:offset+34])
		offset += 34
		(filename, consumed) = parsePtpString(data, offset)
		offset += consumed
		(modificationDate, consumed) = parsePtpString(data, offset)
		offset += consumed
		result[handle] = MtpObjectInfoTuple(storageId, objectFormat, protectionStatus, size,
			0, 0, 0, 0, 0, 0, 0, parent, assocType, assocDesc, sequenceNumber,
			filename, modificationDate[:15], modificationDate[:15])
	return result
