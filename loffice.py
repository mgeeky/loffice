#!/bin/env python

"""
Loffice - Lazy Office Analyzer

Requirements:
- Microsoft Office (32-bit)
- WinDbg (x86) - https://msdn.microsoft.com/en-us/windows/hardware/hh852365
- WinAppDbg - http://winappdbg.sourceforge.net/

Author: @tehsyntx
"""

from winappdbg import Debug, EventHandler
import sys
import os
import optparse
import logging

logging.basicConfig(format='%(levelname)s%(message)s')
logging.addLevelName( logging.INFO, '')
logging.addLevelName( logging.DEBUG, '[%s] ' % logging.getLevelName(logging.DEBUG))
logging.addLevelName( logging.ERROR, '[%s] ' % logging.getLevelName(logging.ERROR))
logger = logging.getLogger()

# Root path to Microsoft Office
DEFAULT_OFFICE_PATH = 'C:\\Program Files\\Microsoft Office\\Office15'


def cb_crackurl(event):
	
	proc = event.get_process()
	thread  = event.get_thread()

	lpszUrl = thread.read_stack_dwords(2)[1]

	logger.info('FOUND URL:\n\t%s\n' % proc.peek_string(lpszUrl, fUnicode=True))

	if exit_on == 'url':
		logger.info('Exiting on first URL, bye!')
		sys.exit()

		
def cb_createfilew(event):

	proc = event.get_process()
	thread = event.get_thread()
	
	lpFileName, dwDesiredAccess = thread.read_stack_dwords(3)[1:]

	if dwDesiredAccess == 0x80000100:
		logger.info('OPEN FILE HANDLE\n\t%s\n' % (proc.peek_string(lpFileName, fUnicode=True)))

		
def cb_createprocessw(event):

	proc = event.get_process()
	thread  = event.get_thread()

	lpApplicationName, lpCommandLine = thread.read_stack_dwords(3)[1:]
	application = proc.peek_string(lpApplicationName, fUnicode=True)
	cmdline = proc.peek_string(lpCommandLine, fUnicode=True)

	logger.info('CREATE PROCESS\n\tApp: "%s"\n\tCmd-line: "%s"\n' % (application, cmdline))
	
	if exit_on == 'url' and 'splwow64' not in application:
		logger.info('Process created before URL was found, exiting for safety')
		sys.exit()
		
	if exit_on == 'proc' and 'splwow64' not in application:
		logger.info('Exiting on process creation, bye!')
		sys.exit()

def cb_stubclient20(event):

	proc = event.get_process()
	thread  = event.get_thread()

	logger.info('DETECTED WMI QUERY')

	strQueryLanguage, strQuery = thread.read_stack_dwords(4)[2:]

	language = proc.peek_string(strQueryLanguage, fUnicode=True)
	query = proc.peek_string(strQuery, fUnicode=True)

	logger.info('\tLanguage: %s' % language)
	logger.info('\tQuery: %s' % query)

	if 'win32_product' in query.lower() or 'win32_process' in query.lower():

		if '=' in query or 'like' in query.lower():
			decoy = "SELECT Name FROM Win32_Fan WHERE Name='1'"
		else:
			decoy = "SELECT Name FROM Win32_Fan"

		i = len(decoy)

		for c in decoy:
			proc.write_char(strQuery + (i - len(decoy)), ord(c))
			i += 2

		proc.write_char(strQuery + (len(decoy) * 2), 0x00)
		proc.write_char(strQuery + (len(decoy) * 2) + 1, 0x00) # Ensure UNICODE string termination

		patched_query = proc.peek_string(strQuery, fUnicode=True)

		logger.info('\tPatched with: %s' % patched_query)


class EventHandler(EventHandler):

	def load_dll(self, event):

		module = event.get_module()
		pid = event.get_pid()

		def setup_breakpoint(modulename, function, callback):
			if module.match_name(modulename + '.dll'):
				address = module.resolve(function)
				try:
					event.debug.break_at(pid, address, callback)
				except:
					logger.error('Could not break at: %s!%s' % (modulename, function))

		setup_breakpoint('kernel32', 'CreateProcessW', cb_createprocessw)
		setup_breakpoint('kernel32', 'CreateFileW', cb_createfilew)
		setup_breakpoint('wininet', 'InternetCrackUrlW', cb_crackurl)
		setup_breakpoint('winhttp', 'WinHttpCrackUrl', cb_crackurl)
		setup_breakpoint('ole32', 'ObjectStublessClient20', cb_stubclient20)

def options():

	valid_types = ['auto', 'word', 'excel', 'power', 'script']
	valid_exit_ons = ['url', 'proc', 'none']

	usage = '''
	%prog [options] <type> <exit-on> <filename>
	
Type:
	auto   - Automatically detect program to launch
	word   - Word document
	excel  - Excel spreadsheet
	power  - Powerpoint document
	script - VBscript & Javascript

Exit-on:
	url  - After first URL extraction (no remote fetching)
	proc - Before process creation (allow remote fetching)
	none - Allow uniterupted execution (dangerous)
'''
	parser = optparse.OptionParser(usage=usage)
	parser.add_option('-v', '--verbose', dest='verbose', help='Verbose mode.', action='store_true')
	parser.add_option('-p', '--path', dest='path', help='Path to the Microsoft Office suite.', default=DEFAULT_OFFICE_PATH)

	opts, args = parser.parse_args()

	if len(args) < 3:
		parser.print_help()
		sys.exit(0)

	if not os.path.exists(opts.path):
		logger.error('Specified Office path does not exists: "%s"' % opts.path)
		sys.exit(1)

	if args[0] not in valid_types:
		logger.error('Specified <type> is not recognized: "%s".' % args[0])
		sys.exit(1)

	if args[1] not in valid_exit_ons:
		logger.error('Specified <exit-on> is not recognized: "%s".' % args[1])
		sys.exit(1)

	if not os.path.isfile(args[2]):
		logger.error('Specified file to analyse does not exists: "%s"' % args[2])
		sys.exit(1)

	if opts.verbose:
		logger.setLevel(logging.DEBUG)
	else:
		logger.setLevel(logging.INFO)

	return (opts, args)


def setup_office_path(opts, args):

	prog = args[0]

	def auto_ext(exts, type_):
		for ext in exts:
			if args[2].endswith(ext):
				return type_
		return False

	if prog == 'auto':
		docs = ['doc', 'docx', 'docm']
		excel = ['xls', 'xlsx', 'xlsm']
		ppt = ['ppt', 'pptx', 'pptm']
		script = ['js', 'vbs']

		p = auto_ext(docs, 'WINWORD')
		if not p:
			p = auto_ext(excel, 'EXCEL')
			if not p:
				p = auto_ext(ppt, 'POWERPNT')
				if not p:
					p = auto_ext(script, 'system32\\wscript')
					if not p:
						logger.error('Unrecognized file!')
						sys.exit(1)
		logger.debug('Auto-detected program to launch: "%s.exe"' % p)
		return '%s\\%s.exe' % (opts.path, p)
	
	if args[0] == 'script':
		return '%s\\system32\\wscript.exe' % os.environ['WINDIR']
	elif args[0] == 'word':
		return '%s\\WINWORD.EXE' % opts.path
	elif args[0] == 'excel':
		return '%s\\EXCEL.EXE' % opts.path
	elif args[0] == 'power':
		return '%s\\POWERPNT.EXE' % opts.path

if __name__ == "__main__":

	(opts, args) = options()

	logger.info('\n\tLazy Office Analyzer - Analyze documents with WinDbg\n')

	office_invoke = []
	office_invoke.append(setup_office_path(opts, args))

	logger.debug('Using office path:')
	logger.debug('\t"%s"' % office_invoke[0])
		
	global exit_on
	exit_on = args[1]
		
	office_invoke.append(args[2]) # Document to analyze

	logger.debug('Invocation command:')
	logger.debug('\t"%s"' % ' '.join(office_invoke))

	with Debug(EventHandler(), bKillOnExit = True) as debug:
		debug.execv(office_invoke)
		try:
			logger.debug('Launching...')
			debug.loop()
		except KeyboardInterrupt:
			logger.info('Exiting, bye!')
			pass
