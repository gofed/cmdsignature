#!/bin/python

# 1. read main.yml with program/task specification
# 1. generate a list of commands to run (help is handled separately)
# 1. check a command exists, if so, print command to run
#

import yaml
import logging
import sys

class ProgramSignatureError(Exception):
	pass

class ProgramSignatureParser(object):

	def __init__(self, program, cmd_root = ""):
		self._commands = {}
		self._description = ""
		self._program = program
		self._cmd_root = cmd_root
		self._argv = []

	def help(self):
		cmd_max_len = 4
		for cmd in self._commands:
			cmd_max_len = max(cmd_max_len, len(cmd))
	
		print "Synopsis: %s COMMAND [OPTIONS]" % self._program
		print ""
		if self._description != "":
			print " %s" % self._description
			print ""
		print "\thelp%sPrints this help" % ((cmd_max_len-1)*" ")

		# sort help by key
		for cmd in sorted(self._commands.keys()):
			space = (cmd_max_len - len(cmd) + 3)*" "
			print "\t%s%s%s" % (cmd, space, self._commands[cmd]["description"])

		exit(0)

	def parse(self, signatures, argv):
		self._commands = {}

		for signature in signatures:
			with open(signature, "r") as f:
				# Don't catch yaml.YAMLError
				data = yaml.load(f)

			for field in ["commands", "description"]:
				if field not in data:
					raise ProgramSignatureError("Missing '%s' field in program signature" % field)

			self._description = data["description"]
	
			for command in data["commands"]:
				for field in ["name", "entry-point", "description"]:
					if field not in command:
						raise ProgramSignatureError("Missing '%s' field of a command in 'commands' field" % field)
	
				self._commands[command["name"]] = command

		# help?
		if len(argv) == 0 or argv[0] in ["-h", "--help", "help"]:
			self.help()

		self._argv = argv

		return self

	def signature(self):
		if len(self._argv) == 0:
			return "%s help" % self._program

		command = self._argv[0]
		args = []
		if len(self._argv) > 0:
			args = self._argv[1:]

		if command == "help":
			return "%s help" % self._program

		if command not in self._commands:
			logging.error("Command '%s' not recognized" % command)
			exit(1)

		# entry point
		entry_point = self._commands[command]["entry-point"]
		if self._cmd_root != "":
			entry_point = "%s/%s" % (self._cmd_root, entry_point)

		# extension
		interpret = ""
		if entry_point.endswith(".py"):
			interpret = "python"
		elif entry_point.endswith(".sh"):
			interpret = "bash"

		# construct signature, print back args repr and do not interpret
		return "%s %s %s" % (interpret, entry_point, " ".join(map(lambda l: repr(l), args)))

