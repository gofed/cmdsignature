#!/bin/python

from .parser import CmdSignatureParser
import os
import logging
import uuid

class SignatureException(Exception):
	pass

class CmdSignatureInterpreter(object):

	def __init__(self, signature_files, command, task, image, binary, keep_default_flags=False):
		self._cmd_signature_parser = CmdSignatureParser(signature_files, program_name=command)
		self._short_eval = False
		self._task = task
		self._image = image
		self._binary = binary
		self._command = command
		self._keep_default_flags = keep_default_flags
		self._overrides = {}

	def interpret(self, args, overrides = {}):
		if "-h" in args or "--help" in args:
			self._short_eval = True
			return self

		self._cmd_signature_parser.generate(overrides).parse(args)
		if not self._cmd_signature_parser.check():
			exit(1)

		self._overrides = overrides
		return self

	def printHelp(self):
		self._cmd_signature_parser.generate().parse(["-h"])
		return self

	def setDefaultPaths(self, empty_path_flags, active_pos_args):
		options = {}
		non_default_flags = []

		# any default actions for flags?
		flags = self._cmd_signature_parser.flags()
		for flag in empty_path_flags:
			if "default-action" not in flags[flag]:
				continue

			if flags[flag]["default-action"] == "set-cwd":
				options[flag] = os.getcwd()
				non_default_flags.append(flag)
				continue

		# any default actions for args?
		for pos_arg in active_pos_args:
			if "default-action" not in pos_arg:
				continue

			if pos_arg["default-action"] == "set-cwd":
				pos_arg["value"] = os.getcwd()
				continue

		# check there is no blank argument followed by non-empty one
		blank = False
		for i, pos_arg in enumerate(active_pos_args):
			if pos_arg["value"] == "":
				blank = True
				continue

			if blank:
				logging.error("Empty positional argument is followed by non-empty argument %s" %  pos_arg["name"])
				exit(1)

		return options, non_default_flags, active_pos_args

	def kubeSignature(self, config = {}):
		if self._short_eval:
			raise SignatureException("kubernetes signature: help not supported")

		flags = self._cmd_signature_parser.flags()
		options = vars(self._cmd_signature_parser.options())

		non_default_flags = []
		for flag in flags:
			if options[flags[flag]["target"]] != flags[flag]["default"]:
				non_default_flags.append(flag)

		# are there any unspecified flags with default paths?
		empty_path_flags = (set(self._cmd_signature_parser.FSDirs().keys()) - set(non_default_flags))

		# set command specific flags
		u_options, u_non_default_flags, active_pos_args = self.setDefaultPaths(empty_path_flags, self._cmd_signature_parser.full_args())

		for flag in u_non_default_flags:
			non_default_flags.append(flag)
			options[flag] = u_options[flag]

		# override flags
		for flag in flags:
			lflag = flags[flag]["long"]
			target = flags[flag]["target"]
			if lflag in self._overrides:
				options[target] = self._overrides[lflag]
				if self._cmd_signature_parser.isFSResource(flags[flag]):
					options[target] = os.path.abspath(options[target])
				if flag not in non_default_flags:
					non_default_flags.append(flag)

		cmd_flags = []
		out_flags = []
		for flag in non_default_flags:
			if not self._cmd_signature_parser.isFSDir(flags[flag]):
				type = flags[flag]["type"]
				if type == "boolean":
					cmd_flags.append("--%s" % flags[flag]["long"])
				else:
					value = options[flags[flag]["target"]]
					# tranform all relative paths into absolute
					if self._cmd_signature_parser.isFSResource(flags[flag]):
						value = os.path.abspath(value)
					cmd_flags.append("--%s %s" % (flags[flag]["long"], repr(value)))

				continue

			# All host path arguments must have direction field
			if "direction" not in flags[flag]:
				raise SignatureException("Missing direction for '%s' flag" % flag)

			# All out arguments are mapped 1:1
			if flags[flag]["direction"] == "out":
				# change target directory to non-existent one inside a container
				# generate temporary directory in postStart
				cmd_flags.append("--%s /tmp/var/run/ichiba/%s" % (flags[flag]["long"], flag))
				out_flags.append(flag)
			else:
				raise SignatureException("Host path flags with in direction are not supported")

		# TODO(jchaloup): host paths arguments are not currently fully supported
		# - input host paths are not supported currently (later, Ichiba client (or other client) must archive and upload any input to publicly available place)
		# - only input host files are, each such file must be archive (tar.gz only for start)
		# - content of each output host path is archived and uploaded to a publicly available place (if set, tar.gz if set)
		# - archiving and uploading is part of the job as well (postStop lifecycle specification)
		# - thus, all host paths arguments carry information about their direction

		# are there any unspecified flags with default paths?
		#empty_path_flags = (set(self._cmd_signature_parser.FSDirs().keys()) - set(non_default_flags))

		task_name = "job-%s-%s-%s" % (self._task, self._command, uuid.uuid4().hex)

		job_spec = {
			"apiVersion": "batch/v1",
			"kind": "Job",
			"metadata": {
				"name": task_name
			},
			"spec": {
				"template": {
					"metadata": {
						"name": task_name
					},
					"spec": {
						"containers": [{
							"name": task_name,
							"image": self._image,
							"command": [
								"/bin/sh",
								"-ec",
								self._binary
							],
							"volumeMounts": [{
								"name": "storage-pk",
								"mountPath": "/etc/storage-pk",
								"readOnly": True
							}]
						}],
						# OnFailure
						"restartPolicy": "Never",
						"volumes": [{
						# create volume from secret with storage PK
							"name": "storage-pk",
							"secret": {
								"secretName": "storage-pk"
							}
						}]
					}
				}
			}
		}


		# No matter if the command itself ends with non-zero exit code
		# Each container must terminated so a job gets completed.
		# At the same time, logs of a pod/container needs to be uploaded with generated resources as well.

		# Add command
		main_cmd = "/bin/sh -c \"%s %s %s\" 2>&1 | tee build.log" % (self._binary, self._command, " ".join(cmd_flags))

		pre_stop_cmds = []
		# pk nees 0600 permissions, /etc is read-only
		pre_stop_cmds.append("cp /etc/storage-pk/* /tmp/storage-pk")
		pre_stop_cmds.append("chmod 0600 /tmp/storage-pk")

		hostname="ichiba"
		servername="storage"
		target="/var/www/html/pub/ichiba"
		if "hostname" in config:
			hostname = config["hostname"]
		if "servername" in config:
			servername = config["servername"]
		if "target" in config:
			target = config["target"]

		# Upload build.log
		pre_stop_cmds.append("ssh -o StrictHostKeyChecking=no -i /tmp/storage-pk %s@%s 'mkdir -p %s/%s'" % (hostname, servername, target, task_name))
		pre_stop_cmds.append("scp -o StrictHostKeyChecking=no -i /tmp/storage-pk build.log %s@%s:%s/%s/." % (hostname, servername, target, task_name))

		post_start_cmds = []

		# Add hooks
		if out_flags != []:
			# add postStart script to generate anonymous paths for output host paths
			# no matter what is inside a given directory (one or more files),
			# entire directory gets archived at the end
			for flag in out_flags:
				# archive all out host paths
				post_start_cmds.append("mkdir -p /tmp/var/run/ichiba/%s" % flag)

			# add preStop script to upload generated resources
			for flag in out_flags:
				# archive all out host paths
				filename = flags[flag]["target"]
				# TODO(jchaloup): how to generate unique filenames for generated resources?
				pre_stop_cmds.append("tar -czf %s.tar.gz /tmp/var/run/ichiba/%s" % (filename, flag))
				# TODO(jchaloup): support other storage resources
				pre_stop_cmds.append("scp -o StrictHostKeyChecking=no -i /tmp/storage-pk %s.tar.gz %s@%s:%s/%s/." % (filename, hostname, servername, target, task_name))

		cmd = ["/bin/sh", "-ec", " && ".join(post_start_cmds + [main_cmd] + pre_stop_cmds) ]
		job_spec["spec"]["template"]["spec"]["containers"][0]["command"] = cmd

		# One must assume the generated specification is publicly available.
		# Location of the private PK is known in advance.
		# For that reason, all the jobs are meant to be used privately.
		# At the same time, all jobs are uploaded to kubernetes without any authentication or authorization.
		# TODO(jchaloup): generate the job specifications inside running container in kubernetes cluster.
		# For that reason, the container will have to clone entire ichiba repository to get a list of all supported tasks.
		# Ichiba client will then just send the command signature.
		# Ichiba server running inside a container will generate the specification so it can not be foisted.
		return job_spec

	def jenkinsSignature(self):
		pass

	def vagrantSignature(self):
		pass

	def dockerSignature(self):
		if self._short_eval:
			return "docker run -t %s %s %s -h" % (self._image, self._binary, self._command)

		flags = self._cmd_signature_parser.flags()
		options = vars(self._cmd_signature_parser.options())

		non_default_flags = []
		for flag in flags:
			if options[flags[flag]["target"]] != flags[flag]["default"]:
				non_default_flags.append(flag)

		# are there any unspecified flags with default paths?
		empty_path_flags = (set(self._cmd_signature_parser.FSDirs().keys()) - set(non_default_flags))

		# set command specific flags
		u_options, u_non_default_flags, active_pos_args = self.setDefaultPaths(empty_path_flags, self._cmd_signature_parser.full_args())

		for flag in u_non_default_flags:
			non_default_flags.append(flag)
			options[flag] = u_options[flag]

		# override flags
		for flag in flags:
			lflag = flags[flag]["long"]
			target = flags[flag]["target"]
			if lflag in self._overrides:
				options[target] = self._overrides[lflag]
				if self._cmd_signature_parser.isFSResource(flags[flag]):
					options[target] = os.path.abspath(options[target])
				if flag not in non_default_flags:
					non_default_flags.append(flag)

		# remap paths
		# each path is to be mapped to itself inside a container
		host_paths = []
		for flag in flags:
			if self._cmd_signature_parser.isFSDir(flags[flag]):
				path = options[flags[flag]["target"]]
				if path != "":
					host_paths.append(path)
			if self._cmd_signature_parser.isFSFile(flags[flag]):
				path = options[flags[flag]["target"]]
				if path != "":
					path = os.path.abspath(path)
					host_paths.append(os.path.dirname(path))

		for arg in active_pos_args:
			if self._cmd_signature_parser.isFSDir(arg):
				host_paths.append(arg["value"])

		host_paths = list(set(host_paths))

		mounts = []
		for host_path in host_paths:
			mounts.append({
				"host": host_path,
				"container": host_path
			})

		mounts_str = " ".join(map(lambda l: "-v %s:%s" % (l["host"], l["container"]), mounts))

		cmd_flags = []
		for flag in non_default_flags:
			type = flags[flag]["type"]
			if type == "boolean":
				cmd_flags.append("--%s" % flags[flag]["long"])
			else:
				value = options[flags[flag]["target"]]
				# tranform all relative paths into absolute
				if self._cmd_signature_parser.isFSResource(flags[flag]):
					value = os.path.abspath(value)
				cmd_flags.append("--%s %s" % (flags[flag]["long"], repr(value)))

		cmd_flags_str = " ".join(cmd_flags)

		active_pos_args_str = " ".join(map(lambda l: l["value"], active_pos_args))

		return "docker run %s -t %s %s %s %s %s" % (mounts_str, self._image, self._binary, self._command, cmd_flags_str, active_pos_args_str)

	def hostSignature(self):
		if self._short_eval:
			return "%s %s -h" % (self._binary, self._command)

		flags = self._cmd_signature_parser.flags()
		options = vars(self._cmd_signature_parser.options())

		non_default_flags = []
		for flag in flags:
			if options[flags[flag]["target"]] != flags[flag]["default"]:
				non_default_flags.append(flag)

		# are there any unspecified flags with default paths?
		empty_path_flags = (set(self._cmd_signature_parser.FSDirs().keys()) - set(non_default_flags))

		# set command specific flags
		u_options, u_non_default_flags, active_pos_args = self.setDefaultPaths(empty_path_flags, self._cmd_signature_parser.full_args())

		for flag in u_non_default_flags:
			non_default_flags.append(flag)
			options[flag] = u_options[flag]

		# override flags
		for flag in flags:
			lflag = flags[flag]["long"]
			target = flags[flag]["target"]
			if lflag in self._overrides:
				options[target] = self._overrides[lflag]
				if self._cmd_signature_parser.isFSResource(flags[flag]):
					options[target] = os.path.abspath(options[target])
				if flag not in non_default_flags:
					non_default_flags.append(flag)

		cmd_flags = []
		for flag in non_default_flags:
			type = flags[flag]["type"]
			if type == "boolean":
				cmd_flags.append("--%s" % flags[flag]["long"])
			else:
				value = options[flags[flag]["target"]]
				# tranform all relative paths into absolute
				if self._cmd_signature_parser.isFSResource(flags[flag]):
					value = os.path.abspath(value)
				cmd_flags.append("--%s %s" % (flags[flag]["long"], repr(value)))

		cmd_flags_str = " ".join(cmd_flags)

		active_pos_args_str = " ".join(map(lambda l: l["value"], active_pos_args))

		return "%s %s %s %s" % (self._binary, self._command, cmd_flags_str, active_pos_args_str)
