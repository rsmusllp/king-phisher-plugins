import threading
import time
import logging

logger = logging.getLogger('KingPhisher.Plugins.SFTPClient.tasks')

class TaskQueue(object):
	"""
	Task queue used for transfer tasks that handles thread and task management
	in a way to prevent errors.
	"""
	def __init__(self):
		self.mutex = threading.RLock()
		self.not_empty = threading.Condition(self.mutex)
		self.not_full = threading.Condition(self.mutex)
		self.queue = []
		self.unfinished_tasks = 0

	@property
	def queue_ready(self):
		for task in self.queue:
			if task.is_ready:
				yield task

	def _qsize(self, len=len):  # pylint: disable=redefined-builtin
		return len(list(self.queue))

	def _qsize_ready(self, len=len):  # pylint: disable=redefined-builtin
		return len(list(self.queue_ready))

	def get(self, block=True, timeout=None):
		self.not_empty.acquire()
		try:
			if not block:
				if not self._qsize_ready():
					return None
			elif timeout is None:
				while not self._qsize_ready():
					self.not_empty.wait()
			elif timeout < 0:
				raise ValueError('\'timeout\' must be a non-negative number')
			else:
				endtime = time() + timeout  # pylint: disable = not-callable
				while not self._qsize_ready():
					remaining = endtime - time()  # pylint: disable = not-callable
					if remaining <= 0.0:
						return None
					self.not_empty.wait(remaining)
			task = next(self.queue_ready)
			task.state = 'Active'
			self.not_full.notify()
			return task
		finally:
			self.not_empty.release()

	def put(self, task):
		"""
		Put a task in the queue.

		:param task: A task to be put in the queue.
		"""
		if not isinstance(task, Task):
			raise TypeError('argument 1 task must be Task instance')
		with self.not_full:
			task.register(self.not_empty)
			self.queue.append(task)
			self.unfinished_tasks += 1
			self.not_empty.notify()
		logger.debug('queued task: ' + str(task))

	def remove(self, task):
		"""
		Remove a task from the queue.

		:param task: A task to be removed from the queue.
		"""
		with self.mutex:
			self.queue.remove(task)
			self.unfinished_tasks += 1
			self.not_full.notify()

class Task(object):
	"""
	Generic task class that contains information about task state and readiness.
	"""
	_states = ('Active', 'Cancelled', 'Completed', 'Error', 'Paused', 'Pending')
	_ready_states = ('Pending',)
	__slots__ = ('_ready', '_state')
	def __init__(self, state=None):
		self._ready = None
		self._state = None
		self.state = (state or 'Pending')

	@property
	def is_done(self):
		return self._state in ('Cancelled', 'Completed', 'Error')

	@property
	def is_ready(self):
		return self._state in self._ready_states

	@property
	def state(self):
		return self._state

	@state.setter
	def state(self, value):
		if value not in self._states:
			raise ValueError('invalid state')
		self._state = value
		if self._state in self._ready_states and self._ready is not None:
			self._ready.notify()

	def register(self, ready_event):
		if self._ready is not None:
			raise RuntimeError('this task has already been registered')
		self._ready = ready_event

class ShutdownTask(Task):
	"""
	Dummy task used to signal the queue to shutdown.
	"""
	def __str__(self):
		return 'shutdown'

class TransferTask(Task):
	"""
	Task used to model transfers. Each task is put in the queue where it will be
	pass into the _transfer method of the FileManager class for the transfer to
	occur.
	"""
	_states = ('Active', 'Cancelled', 'Completed', 'Error', 'Paused', 'Pending', 'Transferring')
	__slots__ = ('_state', 'local_path', 'remote_path', 'size', 'transferred', 'treerowref', 'parent')
	def __init__(self, local_path, remote_path, parent=None, size=None, state=None):
		super(TransferTask, self).__init__(state=state)
		self.local_path = local_path
		"""A string representing the local filesystem path of the transfer."""
		self.remote_path = remote_path
		"""A string representing the remote filesystem path of the transfer."""
		self.transferred = 0
		"""
		If the task is a file transfer, an integer of the number of bytes transferred,
		if the task is a directory transfer, the number of children files transferred.
		"""
		self.size = size
		"""
		If the task is a file transfer, an integer of the total number of bytes,
		if the task is a directory transfer, the total number of children files.
		"""
		self.treerowref = None
		"""A TreeRowReference object representing the Tasks position in the treeview."""
		self.parent = parent

	def __repr__(self):
		return "<{0} local_path={1!r} remote_path={2!r} state={3!r}>".format(self.__class__.__name__, self.local_path, self.remote_path, self.state)

	@property
	def parents(self):
		parents = []
		node = self
		while node.parent is not None:
			parents.append(node.parent)
			node = node.parent
		return parents

	@property
	def progress(self):
		if self.size is None:
			percent = 0
		elif self.size == 0:
			percent = 1
		else:
			percent = (float(self.transferred) / float(self.size))
		return min(int(percent * 100), 100)

	@property
	def state(self):
		return Task.state.fget(self)

	@state.setter
	def state(self, value):
		if value == Task.state.fget(self):
			return
		Task.state.fset(self, value)
		if value in ('Cancelled', 'Completed'):
			for parent_task in self.parents:
				if value == 'Cancelled':
					parent_task.size -= 1
				else:
					parent_task.transferred += 1
				if parent_task.size == parent_task.transferred:
					parent_task.state = ('Completed' if parent_task.size else 'Cancelled')

class DownloadTask(TransferTask):
	"""
	Subclass of TransferTask that indicates
	the task is downloading files.
	"""
	transfer_direction = 'download'
	def __str__(self):
		return "download file {0} -> {1}".format(self.remote_path, self.local_path)

class UploadTask(TransferTask):
	"""
	Subclass of TransferTask that indicates
	the task is uploading files.
	"""
	transfer_direction = 'upload'
	def __str__(self):
		return "upload file {0} -> {1}".format(self.local_path, self.remote_path)

class TransferDirectoryTask(TransferTask):
	"""
	Task to model a folder transfer. Acts as a parent task
	to other TransferTasks and is passed into _transfer_dir.
	"""
	pass

class DownloadDirectoryTask(DownloadTask, TransferDirectoryTask):
	"""
	Subclass of DownloadTask and TransferDirectoryTask that indicates the task
	is downloading folders.
	"""
	def __str__(self):
		return "download directory {0} -> {1}".format(self.remote_path, self.local_path)
DownloadTask.dir_cls = DownloadDirectoryTask

class UploadDirectoryTask(UploadTask, TransferDirectoryTask):
	"""
	Subclass of UploadTask and TransferDirectoryTask that indicates the task is
	uploading folders.
	"""
	def __str__(self):
		return "upload directory {0} -> {1}".format(self.remote_path, self.local_path)
UploadTask.dir_cls = UploadDirectoryTask
