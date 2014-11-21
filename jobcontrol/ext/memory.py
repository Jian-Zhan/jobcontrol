"""
In-memory storage for JobControl state.

This is mostly a reference implementation, and to be used
for testing purposes.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from itertools import count
import copy
import traceback

from jobcontrol.interfaces import StorageBase
from jobcontrol.exceptions import NotFound


class MemoryStorage(StorageBase):
    def __init__(self):
        # Does nothing in default implementation, but in others
        # migth get arguments / do stuff.
        self._init_vars()

    @classmethod
    def from_url(cls, url):
        return cls()

    def _init_vars(self):
        self._jobs = {}
        self._builds = {}
        self._log_messages = defaultdict(list)  # build: messages
        self._jobs_seq = count()
        self._builds_seq = count()

    # ------------------------------------------------------------
    # Installation methods.
    # For resource initialization, if needed.
    # ------------------------------------------------------------

    def install(self):
        self._init_vars()

    def uninstall(self):
        self._init_vars()

    # ------------------------------------------------------------
    # Job CRUD methods
    # ------------------------------------------------------------

    def create_job(self, job_id, function=None, args=None, kwargs=None,
                   dependencies=None, title=None, notes=None, config=None):
        job_id = self._jobs_seq.next()
        job_config = self._make_config(
            job_id, function, args, kwargs, dependencies, title, notes,
            config=config)

        job = {
            'id': job_id,
            'config': job_config,
            'title': job_config['title'],
            'notes': job_config['notes'],
            'dependencies': job_config['dependencies'],
        }

        job['ctime'] = datetime.now()
        job['mtime'] = job['ctime']

        self._jobs[job_id] = job
        return job_id

    def update_job(self, job_id, function=None, args=None, kwargs=None,
                   dependencies=None, title=None, notes=None, config=None):

        if job_id not in self._jobs:
            raise NotFound('No such job: {0}'.format(job_id))

        if function is not None:
            self._jobs[job_id]['function'] = function

        if args is not None:
            self._jobs[job_id]['args'] = args

        if kwargs is not None:
            self._jobs[job_id]['kwargs'] = kwargs

        if dependencies is not None:
            self._jobs[job_id]['dependencies'] = dependencies

        if title is not None:
            self._jobs[job_id]['title'] = title

        if notes is not None:
            self._jobs[job_id]['notes'] = notes

        if config is not None:
            self._jobs[job_id].update(config)

        self._jobs[job_id]['mtime'] = datetime.now()

    def get_job(self, job_id):
        if job_id not in self._jobs:
            raise NotFound('No such job: {0}'.format(job_id))

        return copy.deepcopy(self._jobs[job_id])  # Prevent changes!

    def delete_job(self, job_id):
        for build in self.get_job_builds(job_id):
            self.delete_build(build['id'])

        self._jobs.pop(job_id, None)

    def list_jobs(self):
        return sorted(self._jobs.iterkeys())

    # def iter_jobs(self):
    #     for job_id, job in self._jobs.iteritems():
    #         yield copy.deepcopy(job)

    # def mget_jobs(self, job_ids):
    #     jobs = []
    #     for job_id in job_ids:
    #         if job_id in self._jobs:
    #             jobs.append(copy.deepcopy(self._jobs[job_id]))
    #     return jobs

    def get_job_deps(self, job_id):
        return self.mget_jobs(self.get_job(job_id)['dependencies'])

    def get_job_revdeps(self, job_id):
        deps = []
        for _job_id, job in sorted(self._jobs.iteritems()):
            if job_id in job['dependencies']:
                deps.append(_job_id)
        return self.mget_jobs(deps)

    def get_job_builds(self, job_id, started=None, finished=None,
                       success=None, skipped=None, order='asc', limit=100):

        filters = [lambda x: x['job_id'] == job_id]

        if started is not None:
            filters.append(lambda x: x['started'] is started)

        if finished is not None:
            filters.append(lambda x: x['finished'] is finished)

        if success is not None:
            filters.append(lambda x: x['success'] is success)

        if skipped is not None:
            filters.append(lambda x: x['skipped'] is skipped)

        if order == 'asc':
            order_func = lambda x: sorted(x, key=lambda y: y[1]['id'])

        elif order == 'desc':
            order_func = lambda x: reversed(
                sorted(x, key=lambda y: y[1]['id']))

        else:
            raise ValueError("Invalid order direction: {0}"
                             .format(order))

        for build_id, build in order_func(self._builds.iteritems()):
            if (limit is not None) and limit <= 0:
                return

            if all(f(build) for f in filters):
                yield copy.deepcopy(build)

                if limit is not None:
                    limit -= 1

    # ------------------------------------------------------------
    # Build CRUD methods
    # ------------------------------------------------------------

    def create_build(self, job_id, build_config=None):
        job = self.get_job(job_id)

        build_id = self._builds_seq.next()
        build = {
            'id': build_id,
            'job_id': job_id,
            'start_time': None,
            'end_time': None,

            'started': False,
            'finished': False,
            'success': False,
            'skipped': False,

            'job_config': job['config'],
            'build_config': build_config,

            'retval': None,
            'exception': None,
            'exception_tb': None,

            # Progress is stored in a dict; then we'll have to rebuild it
            # into a proper tree.
            'progress_info': {},
        }
        self._builds[build_id] = build
        return build_id

    def get_build(self, build_id):
        if build_id not in self._builds:
            raise NotFound('No such build: {0}'.format(build_id))

        return copy.deepcopy(self._builds[build_id])

    def delete_build(self, build_id):
        self._log_messages.pop(build_id)
        self._builds.pop(build_id)

    def start_build(self, build_id):
        if build_id not in self._builds:
            raise NotFound('No such build: {0}'.format(build_id))

        self._builds[build_id]['started'] = True
        self._builds[build_id]['start_time'] = datetime.now()

    def finish_build(self, build_id, success=True, skipped=False, retval=None,
                     exception=None, exc_info=None):
        if build_id not in self._builds:
            raise NotFound('No such build: {0}'.format(build_id))

        self._builds[build_id]['finished'] = True
        self._builds[build_id]['end_time'] = datetime.now()
        self._builds[build_id]['success'] = success
        self._builds[build_id]['skipped'] = skipped
        self._builds[build_id]['retval'] = retval
        self._builds[build_id]['exception'] = exception
        if exc_info is not None:
            self._builds[build_id]['exception_tb'] = \
                ''.join(traceback.format_exception(*exc_info))
        else:
            self._builds[build_id]['exception_tb'] = None

    def report_build_progress(self, build_id, current, total, group_name='',
                              status_line=''):

        try:
            build = self._builds[build_id]
        except KeyError:
            raise NotFound("Build {0} not found".format(build_id))

        build['progress_info'][group_name] = {
            'current': current,
            'total': total,
            'status_line': status_line,
        }

    # def update_build_progress(self, build_id, current, total):
    #     if build_id not in self._builds:
    #         raise NotFound('No such build: {0}'.format(build_id))
    #     self._builds[build_id]['progress_current'] = current
    #     self._builds[build_id]['progress_total'] = total

    def log_message(self, job_id, build_id, record):
        record.job_id = job_id
        record.build_id = build_id
        self._log_messages[build_id].append({
            'job_id': job_id, 'build_id': build_id, 'record': record,
            'created': datetime.utcfromtimestamp(record.created)})

    def prune_log_messages(self, job_id=None, build_id=None, max_age=None,
                           level=None):
        filters = []

        if job_id is not None:
            filters.append(lambda x: x['job_id'] == job_id)

        if build_id is not None:
            filters.append(lambda x: x['build_id'] == build_id)

        if max_age is not None:
            expire_date = datetime.now() - timedelta(seconds=max_age)
            filters.append(lambda x: x['created'] < expire_date)

        if level is not None:
            filters.append(lambda x: x['record'].levelno < level)

        self._log_messages[build_id] = [
            msg for msg in self._log_messages[build_id]
            if not (all(f(msg) for f in filters))
        ]

    def iter_log_messages(self, job_id=None, build_id=None, max_date=None,
                          min_date=None, min_level=None):
        filters = []

        if job_id is not None:
            filters.append(lambda x: x['job_id'] == job_id)

        if build_id is not None:
            filters.append(lambda x: x['build_id'] == build_id)

        if max_date is not None:
            filters.append(lambda x: x['created'] < max_date)

        if min_date is not None:
            filters.append(lambda x: x['created'] >= min_date)

        if min_level is not None:
            filters.append(lambda x: x['record'].levelno >= min_level)

        for msg in self._log_messages[build_id]:
            if all(f(msg) for f in filters):
                yield msg['record']
