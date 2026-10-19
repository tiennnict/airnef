#!/usr/bin/env python

#
#############################################################################
#
# cmdline.py - Command-line argument processing
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
# Split out of airnefcmd.py; see airnefcmd.py for the overall program flow.
#
#############################################################################
#

import argparse
import time
import sys
import os
import errno
import mtpwifi
import rename
from applog import *
from mtpdef import *
from appstate import *

		
#
# transltes a date or date+time string from the user into an
# epoch time (ie, time in seconds).
#
def translateDateCmdLineArgToEpoch(cmdArgDesc, isInclusiveEndDate=False):
	userDateTimeStr = g.args[cmdArgDesc]
	if userDateTimeStr == None:
		# user did not specify arg
		return None
	if userDateTimeStr.find(":") != -1:
		# user specified date and time
		strptimeTranslationStr = "%m/%d/%y %H:%M:%S"
		bOnlyDateSpecified = False
	else:
		# user only specified time
		strptimeTranslationStr = "%m/%d/%y"
		bOnlyDateSpecified = True		
	try:
		strptimeResult = time.strptime(userDateTimeStr, strptimeTranslationStr)
	except ValueError as e:
		applog_e("Date specified for \"--{:s}\" is \"{:s}\", which is formatted incorrectly or has an invalid date/time. It must be formatted as mm/dd/yy or mm/dd/yy hh:mm:ss (including leading zeros) and be a valid date/time.".\
			format(cmdArgDesc, userDateTimeStr))
		sys.exit(ERRNO_BAD_CMD_LINE_ARG)
	timeEpoch = time.mktime(strptimeResult)
	if bOnlyDateSpecified and isInclusiveEndDate:
		timeEpoch += (23*60*60) + (59*60) + 59	# make end date inclusive by adding 23 hours, 59 minutes, 59 seconds to epoch time
	return timeEpoch


#
# verifies that a command line integer value is within a defined range
#
def verifyIntegerArgRange(argNameStr, minAllowedValue, maxAllowedValue) :
	if g.args[argNameStr] != None:
		if g.args[argNameStr] < minAllowedValue or g.args[argNameStr] > maxAllowedValue:
			applog_e("Invalid value for --{:s}: valid range is [{:d}-{:d}]".format(argNameStr, minAllowedValue, maxAllowedValue))
			exitAfterCmdLineError(ERRNO_BAD_CMD_LINE_ARG)
	
	
#
# verifies that a command line argument is either an allowable
# string constant or a valid integer value. If validation fails
# then sys.exit() is called with ERRNO_BAD_CMD_LINE_ARG
#
def verifyIntegerArgStrOptions(argNameStr, validStrArgValues=None):
	argValueStr = g.args[argNameStr]
	if validStrArgValues and argValueStr in validStrArgValues:
		# arg is one of the valid string values
		return
	try:
		int(argValueStr)
	except:
		if validStrArgValues == None:
			applog_e("Invalid integer value specified for --" + argNameStr)
		else:
			applog_e("Unknown value name or integer value specified for --" + argNameStr)
			applog_e("Valid values are: {:s}".format(str(validStrArgValues)))
		sys.exit(ERRNO_BAD_CMD_LINE_ARG)	


#
# converts the values of a multiple-value argument ('nargs=+') to uppercase set
#		
def convertMultipleArgToUppercaseSet(argNameStr):
	if g.args[argNameStr]:
		g.args[argNameStr] = set([ x.upper() for x in g.args[argNameStr] ])
	

#
# converts the values of a multiple-value argument ('nargs=+') to lowercase set
#		
def convertMultipleArgToLowercaseSet(argNameStr):
	if g.args[argNameStr]:
		g.args[argNameStr] = set([ x.lower() for x in g.args[argNameStr] ])
	

#
# processCmdLine - Processes command line arguments
#
class ArgumentParserError(Exception): pass # from http://stackoverflow.com/questions/14728376/i-want-python-argparse-to-throw-an-exception-rather-than-usage
class ArgumentParserWithException(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentParserError(message)


#
# called when a command-line error is detected. shuts down the applog module
# and then invokves sys.exit() with specified error code
#
def exitAfterCmdLineError(errno):
	shutdownApplog()
	sys.exit(errno)

	
#
# used for a parser.add_argument "type=conver_int_auto_radix" instead of
# of "type=int". this version converts using a radix determined from the string rather
# than  assumed base-10 for "type=int". this allows hex entries
#	
def conver_int_auto_radix(argStr):
	return int(argStr, 0)
	
	
def processCmdLine():

	#
	# note: if you add additional filter options/logic, go to realTimeCapture() to see if those options
	# need to be overriden when we enter the realtime capture phase
	#
	parser = ArgumentParserWithException(fromfile_prefix_chars='!',\
		formatter_class=argparse.RawDescriptionHelpFormatter,
		description='Wifi image transfer utility for Nikon cameras (airnef@hotmail.com)',\
		epilog="Options can also be specified from a file. Use !<filename>. Each word in the\nfile must be on its own line.\n\nYou "\
			"can abbreviate any argument name provided you use enough characters to\nuniquely distinguish it from other argument names.\n"\
			"\n\n"\
			"Command-Line Examples:\n"\
			"  %(prog)s --extlist NEF MOV (download only raw images and MOV files)\n"\
			"  %(prog)s --downloadhistory ignore (dont skip files previously downloaded)")
	parser.add_argument('--ipaddress', type=str.lower, help='IP address of camera. Default is "%(default)s"', default='192.168.1.1', metavar="addr", required=False)			
	parser.add_argument('--action', type=str.lower, choices=['getfiles', 'getsmallthumbs', 'getlargethumbs', 'listfiles'], help='Program action. Default is "%(default)s"', default='getfiles', required=False)
	parser.add_argument('--realtimedownload', type=str.lower, choices=['disabled', 'afternormal', 'only'], help='Download images from camera in realtime as they\'re taken. \'afternormal\' means realtime capture starts after regular image download. \'only\' skips normal download and only captures realtime images. Default is "%(default)s"', default='disabled', required=False)	
	parser.add_argument('--extlist', help='Type of image/file(s) to download. Ex: \"--extlist NEF\". Multiple extensions can be specified. Use \"<NOEXT>\" to include files that don\'t have extensions. Default is to download all file types', default=None, nargs='+', metavar='extension', required=False)
	parser.add_argument('--startdate', help='Only include image/file(s) captured on or later than date. Date-only Ex: --startdate 12/05/14. Date+Time Example: --startdate \"12/05/14 15:30:00\"', metavar="date", required=False)
	parser.add_argument('--enddate', help='Only include image/file(s) captured on or earlier than date or date+time. Date without a specified time is inclusive, so for example --enddate 06/12/14 is interpreted as 06/12/14 23:59:59', metavar="date", required=False)
	parser.add_argument('--outputdir', type=str, help='Directory to store image/file(s) to.  Default is current directory. No ending backslash is necessary. If path contains any spaces enclose it in double quotes. Example: --outputdir \"c:\\My Documents\"', default=None, metavar="path", required=False)
	parser.add_argument('--ifexists', type=str.lower, choices=['uniquename', 'skip', 'overwrite', 'prompt', 'exit'], help='Action to take if file with same name already exists. Default is "%(default)s"', default='uniquename', required=False)
	parser.add_argument('--downloadhistory', type=str.lower, choices=['skipfiles', 'ignore', 'clear' ], help='\'skipfiles\' means that files in history (ie, previously downloaded) will be skipped and not downloaded. Default is "%(default)s"', default='skipfiles', required=False)
	parser.add_argument('--onlyfolders', help='Only include image/file(s) existing in specified camera folders.. Ex: \"--onlyfolders 100D7200 101D7200\". Default is to include all folders', default=None, nargs='+', metavar="camera_folder", required=False)
	parser.add_argument('--excludefolders', help='Exclude image/file(s) existing in specified camera folders.. Ex: \"--excludefolders 103D7200\". Default is no exclusions.', default=None, nargs='+', metavar="camera_folder", required=False)			
	parser.add_argument('--filenamespec', type=str, help='Optionally rename files using dynamic renaming engine. See online help for documentation on \'spec\'', default=None, metavar="spec", required=False)	
	parser.add_argument('--dirnamespec', type=str, help='Optionally name directories using dynamic renaming engine. See online help for documentation on \'spec\'', default=None, metavar="spec", required=False)		
	parser.add_argument('--transferorder', type=str.lower, choices=['oldestfirst', 'newestfirst'], help='Transfer oldest or newest files first. Default is "%(default)s"', default='oldestfirst', required=False)
	parser.add_argument('--slot', type=str.lower, help='Card slot on camera to read from. Default is "%(default)s", which means first populated slot', choices=['firstfound', 'first', 'second', 'both'], default='firstfound', required=False)
	parser.add_argument('--cameratransferlist', type=str.lower, choices=['useifavail', 'exitifnotavail', 'ignore'], help='Decide how to handle images selected on camera. Default is "%(default)s"', default='useifavail', required=False)
	parser.add_argument('--downloadexec', help='Launch application for each file downloaded', default=None, nargs='+', metavar=('executable', 'arguments'), required=False)
	parser.add_argument('--downloadexec_extlist', help='Type of files(s) by extension on wich to perform --downloadexec on. Default is all file types', default=None, nargs='+', metavar='extension', required=False)
	parser.add_argument('--downloadexec_options', help='Options for launcing application. For example \'wait\' waits for launched app to exit before proceeding to next download. See online help for more options', default=[], nargs='+', metavar='option', required=False)	
	parser.add_argument('--realtimepollsecs', type=int, help='How often camera is polled for new images in realtime mode, in seconds. Default is every %(default)s seconds', default=3, metavar="seconds", required=False)
	parser.add_argument('--logginglevel', type=str.lower, choices=['normal', 'verbose', 'debug' ], help='Sets how much information is saved to the result log. Default is "%(default)s"', default='normal', required=False)
	# hidden args (because they wont be used often and will complicate users learning the command line - they are documented online)
	parser.add_argument('--port', help=argparse.SUPPRESS, type=int, default=mtpwifi.MTP_TCPIP_PORT_DEFAULT, required=False)
	parser.add_argument('--connecttimeout', help=argparse.SUPPRESS, type=int, default=10, required=False)
	parser.add_argument('--socketreadwritetimeout', help=argparse.SUPPRESS, type=int, default=5, required=False)
	parser.add_argument('--retrycount', help=argparse.SUPPRESS, type=int, default=sys.maxsize, required=False)
	parser.add_argument('--retrydelaysecs', help=argparse.SUPPRESS, type=int, default=5, required=False)
	parser.add_argument('--printstackframes', help=argparse.SUPPRESS, type=str.lower, choices=['no', 'yes'], default='no', required=False)
	parser.add_argument('--objinfomethod', type=str.lower, choices=['auto', 'proplist', 'manifest', 'perobject'], help=argparse.SUPPRESS, default='auto', required=False)
	parser.add_argument('--mtpobjcache', type=str.lower, choices=['enabled', 'writeonly', 'readonly', 'verify', 'disabled'], help=argparse.SUPPRESS, default='enabled', required=False)	
	parser.add_argument('--mtpobjcache_maxagemins', help=argparse.SUPPRESS, type=int, default=0, required=False) # default is 0=indefinite (never invalidate based on age)
	parser.add_argument('--maxgetobjtransfersizekb', help=argparse.SUPPRESS, type=int, default=DEFAULT_MAX_KB_PER_GET_OBJECT_REQUEST, required=False)	
	parser.add_argument('--maxgetobjbuffersizekb', help=argparse.SUPPRESS, type=int, default=DEFAULT_MAX_KB_TO_BUFFER_FOR_GET_OBJECT_REQUESTS, required=False)
	parser.add_argument('--initcmdreq_guid', help=argparse.SUPPRESS, type=str.lower, default='0x7766554433221100-0x0000000000009988', required=False) # GUID order in string is high-low
	parser.add_argument('--initcmdreq_hostname', help=argparse.SUPPRESS, type=str, default='airnef', required=False)
	parser.add_argument('--initcmdreq_hostver', help=argparse.SUPPRESS, type=conver_int_auto_radix, default=0x00010000, required=False)
	parser.add_argument('--opensessionid', help=argparse.SUPPRESS, type=conver_int_auto_radix, default=None, required=False)
	parser.add_argument('--maxclockdeltabeforesync', help=argparse.SUPPRESS, type=str.lower, default='5', required=False)
	parser.add_argument('--camerasleepwhendone', help=argparse.SUPPRESS, type=str.lower, choices=['no', 'yes'], default='yes', required=False)
	parser.add_argument('--sonyuniquecmdsenable', help=argparse.SUPPRESS, type=conver_int_auto_radix, default=SONY_UNQIUECMD_ENABLE_SENDING_MSG, required=False)
	parser.add_argument('--suppressdupconnecterrmsgs', help=argparse.SUPPRESS, type=str.lower, choices=['no', 'yes'], default='yes', required=False)
	parser.add_argument('--rtd_pollingmethod', help=argparse.SUPPRESS, type=int, default=None, required=False)
	parser.add_argument('--rtd_mtppollingmethod_newobjdetection', help=argparse.SUPPRESS, type=str.lower, choices=['objlist', 'numobjs'], default='objlist', required=False)
	parser.add_argument('--rtd_maxsecsbeforeforceinitialobjlistget', help=argparse.SUPPRESS, type=int, default=5, required=False)
	parser.add_argument('--ssdp_discoveryattempts', help=argparse.SUPPRESS, type=int, default=3, required=False)
	parser.add_argument('--ssdp_discoverytimeoutsecsperattempt', help=argparse.SUPPRESS, type=int, default=2, required=False)	
	parser.add_argument('--ssdp_discoveryflags', help=argparse.SUPPRESS, type=conver_int_auto_radix, default=None, required=False)
	parser.add_argument('--ssdp_addservice', help=argparse.SUPPRESS, nargs='+', required=False, default=None)
	parser.add_argument('--ssdp_addmulticastif', help=argparse.SUPPRESS, nargs='+', required=False, default=None)
	
	
	#
	# if there is a default arguments file present, add it to the argument list so that parse_args() will process it
	#
	defaultArgFilename = os.path.join(g.appDir, "airnefcmd-defaultopts")
	if os.path.exists(defaultArgFilename):
		sys.argv.insert(1, "!" + defaultArgFilename) # insert as first arg (past script name), so that the options in the file can still be overriden by user-entered cmd line options
			
	# perform the argparse
	try:
		args = vars(parser.parse_args())
	except ArgumentParserError as e:
		applog_e("Command line error: " + str(e))
		exitAfterCmdLineError(ERRNO_BAD_CMD_LINE_ARG)	
	
	# set our global var to the processed argument list	and log them
	g.args = args

	#
	# process any args that need verification/translation/conversion
	#
	
	# convert all arguments that have multiple values to uppercase/lowercase sets
	convertMultipleArgToUppercaseSet('extlist')
	convertMultipleArgToUppercaseSet('onlyfolders')
	convertMultipleArgToUppercaseSet('excludefolders')
	convertMultipleArgToLowercaseSet('downloadexec_options')
	convertMultipleArgToUppercaseSet('downloadexec_extlist')
	
	if not g.args['outputdir']:
		if not g.args['dirnamespec']:
			# neither 'outputdir' nor 'dirnamespec' specified - use current directory
			g.args['outputdir'] = '.\\' if g.isWin32 else './'
		else:
			# 'dirnamespec' specified - use empty string for base output dir
			g.args['outputdir'] = ""
	
	
	# verify syntax of --filenamespec and --dirnamespec
	if g.args['filenamespec']:
		try:
			rename.verifyRenameFormatStringSyntax(g.args['filenamespec'])
		except rename.GenerateReplacementNameException as e:
			applog_e("Error parsing filenamespec: " + str(e))
			exitAfterCmdLineError(ERRNO_RENAME_ENGINE_PARSING_ERROR)
	if g.args['dirnamespec']:
		try:
			rename.verifyRenameFormatStringSyntax(g.args['dirnamespec'])
		except rename.GenerateReplacementNameException as e:
			applog_e("Error parsing dirnamespec: " + str(e))
			exitAfterCmdLineError(ERRNO_RENAME_ENGINE_PARSING_ERROR)
			
	# verify syntax of --downloadexec
	if g.args['downloadexec']:
		try:
			for argNumber, arg in enumerate(g.args['downloadexec']):
				rename.verifyRenameFormatStringSyntax(arg)
		except rename.GenerateReplacementNameException as e:
			applog_e("Error parsing downloadexec arg #{:d} \"{:s}\": {:s}".format(argNumber+1, arg, str(e)))
			exitAfterCmdLineError(ERRNO_RENAME_ENGINE_PARSING_ERROR)
	
	# verify --downloadexec_options
	validDownloadExecOptions = [ 'ignorelauncherror', 'wait', 'exitonfailcode', 'delay', 'notildereplacement' ]
	for arg in g.args['downloadexec_options']:
		if arg not in validDownloadExecOptions:
			applog_e("Unrecognized option \"{:s}\" for --downloadexec_options".format(arg))
			exitAfterCmdLineError(ERRNO_BAD_CMD_LINE_ARG)
	
	if g.args['action'] not in CmdLineActionToMtpTransferOpDict:
		#
		# action is not a download operation. change/disable other command
		# line arguments that aren't valid for non-download actions
		#
		g.args['realtimedownload'] = 'disabled'

	if g.args['realtimedownload'] != 'only':
		# regular image download enabled. process any start/end date filters that user specified
		g.objfilter_dateStartEpoch = translateDateCmdLineArgToEpoch('startdate')
		g.objfilter_dateEndEpoch = translateDateCmdLineArgToEpoch('enddate', isInclusiveEndDate=True)
	# else we'll set the capture date filters later for realtime operation
		
	g.fileTransferOrder = FILE_TRANSFER_ORDER_OLDEST_FIRST if g.args['transferorder']=='oldestfirst' else FILE_TRANSFER_ORDER_NEWEST_FIRST	
	g.maxGetObjTransferSize = g.args['maxgetobjtransfersizekb'] * 1024
	g.maxGetObjBufferSize = g.args['maxgetobjbuffersizekb'] * 1024		
	verifyIntegerArgStrOptions('maxclockdeltabeforesync', ['disablesync', 'alwayssync'])	
	verifyIntegerArgRange('rtd_pollingmethod', 0, REALTIME_DOWNLOAD_METHOD_MAX)
	
	# process any args that require action now
	if g.args['logginglevel'] == 'normal':
		# we've already set to this default
		pass
	elif g.args['logginglevel'] == 'verbose':
		applog_set_loggingFlags(APPLOGF_LEVEL_INFORMATIONAL | APPLOGF_LEVEL_ERROR | APPLOGF_LEVEL_WARNING | APPLOGF_LEVEL_VERBOSE)
	elif g.args['logginglevel'] == 'debug':
		applog_set_loggingFlags(APPLOGF_LEVEL_INFORMATIONAL | APPLOGF_LEVEL_ERROR | APPLOGF_LEVEL_WARNING | APPLOGF_LEVEL_VERBOSE | APPLOGF_LEVEL_DEBUG)

	# log the cmd line arguments
	applog_d("Orig cmd line: {:s}".format(str(sys.argv)))
	applog_d("Processed cmd line: {:s}".format(str(g.args)))
