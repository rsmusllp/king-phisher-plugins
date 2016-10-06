#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  patch_readme.py
#
#  Copyright 2016 Spencer McIntyre <zeroSteiner@gmail.com>
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are
#  met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following disclaimer
#    in the documentation and/or other materials provided with the
#    distribution.
#  * Neither the name of the  nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#  A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#  SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#  THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

import datetime
import glob
import importlib
import os
import sys
import textwrap

import jinja2

try:
	import tabulate
except ImportError:
	print('the tabulate module is required to run this')
	sys.exit(os.EX_UNAVAILABLE)

def load_plugins(plugin_type, plugins_dir):
	plugins = []
	for plugin in glob.glob(os.path.join(plugins_dir, plugin_type, '*.py')):
		plugin = os.path.basename(plugin)
		plugin = os.path.splitext(plugin)[0]
		print('loading ' + plugin_type + ' plugin: ' + plugin)
		plugin_module = importlib.import_module(plugin_type + '.' + plugin)
		plugins.append(plugin_module.Plugin)
	return plugins

def make_table(plugins):
	table = []
	for plugin in plugins:
		description = textwrap.dedent(plugin.description)
		description = description.replace('\n', ' ')
		description = description.strip()
		table.append((plugin.name, description))
	return tabulate.tabulate(table, ('Name', 'Description'), tablefmt='pipe')

def main():
	if sys.version_info < (3, 4):
		# python 3 is required to import without an __init__.py file
		print('this requires at least python version 3.4 to run')
		sys.exit(os.EX_SOFTWARE)

	plugins_dir = os.path.dirname(os.path.abspath(__file__))
	print('plugins directory: ' + plugins_dir)
	king_phisher_dir = os.path.normpath(os.path.join(plugins_dir, '..', 'king-phisher'))
	if not os.path.isdir(king_phisher_dir):
		print('could not find the king-phisher directory at: ' + king_phisher_dir)
		sys.exit(os.EX_UNAVAILABLE)

	sys.path.insert(0, king_phisher_dir)
	sys.path.insert(0, plugins_dir)

	client_plugins = load_plugins('client', plugins_dir)
	server_plugins = load_plugins('server', plugins_dir)

	jinja_env = jinja2.Environment(trim_blocks=True)
	jinja_env.filters['strftime'] = lambda dt, fmt: dt.strftime(fmt)
	with open(os.path.join(plugins_dir, 'README.jnj'), 'r') as file_h:
		readme_template = jinja_env.from_string(file_h.read())

	readme = readme_template.render(
		plugins={'client': client_plugins, 'server': server_plugins},
		timestamp=datetime.datetime.utcnow()
	)

	with open(os.path.join(plugins_dir, 'README.md'), 'w') as file_h:
		file_h.write(readme)
	return 0

if __name__ == '__main__':
	sys.exit(main())
