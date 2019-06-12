import collections
import re
import os
import time
import threading

import king_phisher.server.database.manager as db_manager
import king_phisher.server.database.models as db_models
import king_phisher.server.fs_utilities as fs_utilities
import king_phisher.plugins as plugin_opts
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals
import king_phisher.utilities as utilities

EXAMPLE_CONFIG = """\
  log_file_location: /var/log/mail.log
"""

class LogInformation(object):
    __slots__ = ('message_id', 'statuses', 'message_details')

    def __init__(self, message_id):
        self.message_id = message_id
        self.statuses = collections.deque()
        self.message_details = None

    @property
    def message_status(self):
        if not self.statuses:
            return None
        return self.statuses[-1]

class Plugin(plugins.ServerPlugin):
    authors = ['Skyler Knecht']
    classifiers = ['Plugin :: Server']
    title = 'Postfix Message Information'
    description = """
    A plugin that analyzes message information to provide clients 
    message status and details.
    """
    homepage = 'https://github.com/securestate/king-phisher-plugins'
    version = '1.0'
    req_min_version = '1.14.0b1'
    options = [
        plugin_opts.OptionString(
            name='log_file_location',
            description='Location of the log file to parse through for information.',
            default='/var/log/mail.log'
        )
    ]

    def initialize(self):
        if not fs_utilities.access(self.config['log_file_location'], mode=os.R_OK,
                                   user=self.root_config.get('server.setuid_username')):
            self.logger.error('permissions error, invalid access to {}'.format(self.config['log_file_location']))
            return False

        signals.server_initialized.connect(self.on_server_initialized)
        self.logger.info('{} has been initialized.'.format(self.title))
        return True

    def on_server_initialized(self, server):
        self._worker_thread = utilities.Thread(target=self.check_file_change, args=(self.config['log_file_location'],))
        self._worker_thread.start()

    def finalize(self):
        self._worker_thread.stop()
        self._worker_thread.join()

    def check_file_change(self, file):
        old_modified_time = self.get_modified_time(file)
        old_file_contents = self.get_file_contents(file)
        while self._worker_thread.stop_flag.is_clear():
            new_modified_time = self.get_modified_time(file)
            if old_modified_time < new_modified_time:
                new_file_contents = self.get_file_contents(file)
                self.post_to_database(self.parse_logs(new_file_contents))
                old_modified_time = new_modified_time
            time.sleep(5)

    @staticmethod
    def get_modified_time(file):
        return os.stat(file).st_mtime

    @staticmethod
    def get_file_contents(file):
        with open(file, 'r') as log_file:
            return log_file.readlines()

    def parse_logs(self, log_lines):
        results = {}
        for line_number, line in enumerate(log_lines, 1):
            log_id = re.search(r'postfix/[a-z]+\[\d+\]:\s+(?P<log_id>[0-9A-Z]{7,12}):\s+', line)
            if not log_id:
                self.logger.warning('failed to parse postfix log line: ' + str(line_number))
                continue
            log_id = log_id.group('log_id')
            message_id = re.search(r'message-id=<(?P<mid>[0-9A-Za-z]{12,20})@', line)
            status = re.search(r'status=(?P<status>[a-z]+)\s', line)
            details = re.search(r'status=[a-z]+\s\((?P<details>.+)\)', line)
            if log_id not in results and message_id:
                results[log_id] = LogInformation(message_id=message_id.group('mid'))
            if log_id in results and status:
                results[log_id].statuses.append(status.group('status'))
            if log_id in results and details:
                results[log_id].message_details = details.group('details')
        return results

    @staticmethod
    def post_to_database(results):
        session = db_manager.Session
        for log_info in results.values():
            message = session.query(db_models.Message).filter_by(id=log_info.message_id).first()
            if message:
                if log_info.message_status:
                    message.delivery_status = log_info.message_status
                    message.delivery_details = log_info.message_details
                    session.add(message)
        session.commit()
