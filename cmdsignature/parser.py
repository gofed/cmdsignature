import optparse
import yaml
import logging
import re
import sys

# TODO(jchaloup): generate class definition for each cmd instead
#                 of reading the yaml files every time a cmd is executed

class CmdSignatureParser(object):

	def __init__(self, definitions = [], program_name = "%prog"):
		self._definitions = definitions
		self._parser = None
		self._options = None
		self._args = None
		self._flags = {}
		self._program_name = program_name
		# positional arguments
		self._pos_args = []

		self._non_empty_flags = []
		self._non_empty_flag_groups = {}

	def generate(self, overrides = {}):

		def long2target(long):
			return re.sub(r'[-_]', '', long)

		self._flags = {}
		pos_arg_strs = []

		for definition in self._definitions:
			with open(definition, 'r') as f:
				# Don't catch yaml.YAMLError
				data = yaml.load(f)
				for flag in data["flags"]:
					if "target" not in flag:
						flag["target"] = long2target(flag["long"])

					if "default" not in flag:
						if flag["type"] == "boolean":
							flag["default"] = False
						elif flag["type"] == "integer":
							flag["default"] = 0
						else:
							flag["default"] = ""

					# if provided, override the default value
					if flag["long"] in overrides:
						flag["default"] = overrides[flag["long"]]

					self._flags[flag["target"]] = flag

				if "args" not in data:
					continue

				for pos_arg in data["args"]:
					pos_arg["value"] = ""
					self._pos_args.append(pos_arg)

					if "required" not in pos_arg or not pos_arg["required"]:
						pos_arg_strs.append("[%s]" % pos_arg["name"].lower())
					else:
						pos_arg_strs.append(pos_arg["name"].lower())

		self._parser = optparse.OptionParser("%s [OPTIONS] %s" % (self._program_name, (" ".join(pos_arg_strs) )))

		for pos_arg in self._pos_args:
			self._parser.add_option_group( optparse.OptionGroup(self._parser, pos_arg["name"], pos_arg["description"]) )

		for target in sorted(self._flags.keys()):
			option = self._flags[target]
			short = ""
			if "short" in option:
				short = "-%s" % option["short"]

			if option["type"] == "boolean":
				action = "store_true"
			else:
				action = "store"

			self._parser.add_option(
				"",
				short,
				"--%s" % option["long"],
				dest=option["target"],
				action=action,
				default = option["default"],
				help = option["description"]
			)

			if "non-empty-group" in option:
				try:
					self._non_empty_flag_groups[option["non-empty-group"]].append(option)
				except KeyError as e:
					self._non_empty_flag_groups[option["non-empty-group"]] = [option]

			if "non-empty" in option:
				self._non_empty_flags.append(option)

		return self

	def parse(self, args = sys.argv[1:]):
		self._options, pos_args = self._parser.parse_args(args)

		if len(pos_args) > len(self._pos_args):
			logging.error("Number of positional arguments is greater than number of defined positional arguments")
			exit(1)

		# process positional args
		for i, pos_arg in enumerate(pos_args):
			self._pos_args[i]["value"] = pos_arg

		return self

	def check(self):
		options = vars(self._options)

		options_on = []

		def is_option_set(options, flag):
			if flag["type"] == "boolean":
				if options[ flag["target"] ]:
					return True
			# the rest assumed to be string
			else:
				if options[ flag["target"] ] != "":
					return True

			return False

		def is_integer(number):
			try:
				number += 1
			except TypeError:
				return False
			return True

		# check required grouped flags first
		for group in self._non_empty_flag_groups:
			group_set = False
			for flag in self._non_empty_flag_groups[group]:
				if is_option_set(options, flag):
					group_set = True
					options_on.append( flag["target"] )
			if not group_set:
				group_options = ", ".join(map(lambda l: "--%s" % l["long"], self._non_empty_flag_groups[group]))
				logging.error("At least one of '%s' options must be set" % group_options)
				return False

		# check required single flags then
		for flag in self._non_empty_flags:
			if not is_option_set(options, flag):
				logging.error("Option '--%s' not set. Check command's help" % flag["long"])
				return False
			options_on.append( flag["target"] )

		# and make sure all required flags has their own required flags set
		count = len(options_on)
		index = 0
		while index < count:
			option = options_on[index]
			if "requires" in self._flags[option]:
				for item in self._flags[option]["requires"]:
					if not is_option_set(options, self._flags[item]):
						logging.error("Option '--%s' not set. Check command's help" % self._flags[item]["long"])
						return False

				options_on = options_on + self._flags[option]["requires"]
				count = count + len(self._flags[option]["requires"])

			index = index + 1

		# check if flags have valid values
		for key in self._flags:
			flag = self._flags[key]
			long = flag["long"]

			if "one-of" in flag:
				value = options[flag["target"]]
				one_of = flag["one-of"]
				if value not in one_of:
					logging.error("Option '%s': '%s' is not one of '%s'" % (long, value, "|".join(one_of)))
					return False

			if flag["type"] == "integer":
				try:
					value = int(options[flag["target"]])
				except TypeError:
					logging.error("Option '%s': '%s' is not integer" % (long, value))
					return False

				if "min" in flag:
					min = flag["min"]
					if not is_integer(min):
						logging.error("Option '%s': '%s' of min is not integer" % (long, min))
						return False

					if value < flag["min"]:
						logging.error("Options '%s': '%s' is less than min '%s'" % (long, value, min))
						return False

				if "max" in flag:
					max = flag["max"]
					if not is_integer(max):
						logging.error("Option '%s': '%s' of max is not integer" % (long, max))
						return False

					if value > flag["max"]:
						logging.error("Options '%s': '%s' is greater than max '%s'" % (long, value, max))
						return False

		return True

	def options(self):
		return self._options

	def full_args(self):
		return self._pos_args

	def args(self):
		return map(lambda l: l["value"], self._pos_args)

	def flags(self):
		return self._flags

	def isFSDir(self, flag):
		return flag["type"] in ["directory"]

	def isFSFile(self, flag):
		return flag["type"] in ["file"]

	def isFSResource(self, flag):
		return self.isFSDir(flag) or self.isFSFile(flag)

	def FSDirs(self):
		flags = {}
		for flag in self._flags:
			if self.isFSDir(self._flags[flag]):
				flags[flag] = self._flags[flag]

		return flags

