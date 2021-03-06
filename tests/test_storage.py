# -*- coding: utf-8 -*-

"""
Tests for the jobcontrol state storages.
"""

from datetime import datetime, timedelta

import pytest

from jobcontrol.exceptions import NotFound


def test_build_crud(storage):
    assert list(storage.get_job_builds('foobar')) == []

    build_id = storage.create_build(
        job_id='foobar', config={'function': 'mymod:myfunction'})

    # Retrieve and check the created object

    build = storage.get_build(build_id)

    MANDATORY_ATTRS = set([
        'id', 'job_id', 'config',
        'exception',
        'exception_tb',
        'skipped',
        'success',
        'title',
        'started',
        'start_time',
        'finished',
        'retval',
        'notes',
        'end_time',
    ])

    # assert all(x in build for x in MANDATORY_ATTRS)

    for attr in MANDATORY_ATTRS:
        assert attr in build

    assert build['id'] == build_id
    assert build['job_id'] == 'foobar'

    assert isinstance(build['config'], dict)
    assert build['config']['function'] == 'mymod:myfunction'
    assert build['config'].get('args', ()) == ()
    assert build['config'].get('kwargs', {}) == {}
    assert build['config'].get('dependencies', []) == []

    assert build['start_time'] is None
    assert build['end_time'] is None

    assert build['started'] is False
    assert build['finished'] is False
    assert build['success'] is False
    assert build['skipped'] is False

    assert build['retval'] is None
    assert build['exception'] is None
    assert build['exception_tb'] is None

    assert build['title'] is None
    assert build['notes'] is None

    assert list(storage.get_job_builds('foobar')) == [build]

    storage.delete_build(build_id)

    assert list(storage.get_job_builds('foobar')) == []

    with pytest.raises(NotFound):
        storage.get_build(build_id)


def test_build_actions(storage):
    build_id = storage.create_build('job-build-actions', {})

    build = storage.get_build(build_id)
    assert build['start_time'] is None
    assert build['end_time'] is None
    assert build['started'] is False
    assert build['finished'] is False
    assert build['success'] is False
    assert build['skipped'] is False
    assert build['retval'] is None
    assert build['exception'] is None
    assert build['exception_tb'] is None

    storage.start_build(build_id)

    build = storage.get_build(build_id)
    assert build['start_time'] is not None
    assert build['end_time'] is None
    assert build['started'] is True
    assert build['finished'] is False
    assert build['success'] is False
    assert build['skipped'] is False
    assert build['retval'] is None
    assert build['exception'] is None
    assert build['exception_tb'] is None

    storage.finish_build(build_id, retval='foobar')

    build = storage.get_build(build_id)
    assert build['start_time'] is not None
    assert build['end_time'] is not None
    assert build['started'] is True
    assert build['finished'] is True
    assert build['success'] is True
    assert build['skipped'] is False
    assert build['retval'] == 'foobar'
    assert build['exception'] is None
    assert build['exception_tb'] is None

    storage.delete_build(build_id)


def test_build_finish_failure(storage):
    build_id = storage.create_build('job-build-actions', {})

    build = storage.get_build(build_id)
    storage.start_build(build_id)
    storage.finish_build(build_id, success=False, exception=ValueError('foo'))

    build = storage.get_build(build_id)
    assert build['start_time'] is not None
    assert build['end_time'] is not None
    assert build['started'] is True
    assert build['finished'] is True
    assert build['success'] is False
    assert build['skipped'] is False
    assert build['retval'] is None
    assert isinstance(build['exception'], ValueError)
    assert build['exception_tb'] is None

    storage.delete_build(build_id)


def test_build_iteration(storage):
    job_id = 'job-test-build-iteration'

    builds = [
        storage.create_build(job_id, {}),
        storage.create_build(job_id, {}),
        storage.create_build(job_id, {}),
        storage.create_build(job_id, {}),
    ]

    def _get_builds(**kw):
        retr_builds = list(storage.get_job_builds(job_id, **kw))
        return [x['id'] for x in retr_builds]

    assert _get_builds(started=False) == builds

    assert _get_builds(started=True) == []
    assert _get_builds(started=False) == builds
    assert _get_builds(finished=False) == builds

    # ------------------------------------------------------------

    storage.start_build(builds[0])

    assert _get_builds(started=True) == [builds[0]]
    assert _get_builds(started=False) == builds[1:]
    assert _get_builds(finished=False) == builds

    # ------------------------------------------------------------

    storage.finish_build(builds[0])
    storage.start_build(builds[1])

    assert _get_builds(started=True) == [builds[0], builds[1]]
    assert _get_builds(started=False) == [builds[2], builds[3]]
    assert _get_builds(started=True, finished=True) == [builds[0]]
    assert _get_builds(started=True, finished=False) == [builds[1]]

    assert storage.get_latest_successful_build(job_id)['id'] == builds[0]

    # ------------------------------------------------------------

    storage.finish_build(builds[1], success=False)

    assert _get_builds(started=True) == [builds[0], builds[1]]
    assert _get_builds(started=False) == [builds[2], builds[3]]
    assert _get_builds(started=True, finished=True) == [builds[0], builds[1]]
    assert _get_builds(started=True, finished=False) == []
    assert _get_builds(started=True, finished=True, success=True) == [builds[0]]  # noqa
    assert _get_builds(started=True, finished=True, success=False) == [builds[1]]  # noqa

    assert storage.get_latest_successful_build(job_id)['id'] == builds[0]

    # ------------------------------------------------------------

    storage.start_build(builds[2])
    storage.finish_build(builds[2], success=True)

    assert _get_builds(started=True) == [builds[0], builds[1], builds[2]]
    assert _get_builds(started=False) == [builds[3]]
    assert _get_builds(started=True, finished=True) \
        == [builds[0], builds[1], builds[2]]
    assert _get_builds(started=True, finished=False) == []
    assert _get_builds(started=True, finished=True, success=True) \
        == [builds[0], builds[2]]
    assert _get_builds(started=True, finished=True, success=False) \
        == [builds[1]]

    assert storage.get_latest_successful_build(job_id)['id'] == builds[2]

    # ------------------------------------------------------------

    # All builds, in reversed order
    assert _get_builds(order='desc') == list(reversed(builds))

    # First two, in normal order
    assert _get_builds(limit=2) == builds[:2]

    # Latest two, in reverse order
    assert _get_builds(order='desc', limit=2) == list(reversed(builds))[:2]


def test_logrecord_objects():
    import logging

    record = logging.LogRecord(**{
        'name': 'mylogger', 'level': logging.DEBUG,
        'pathname': '/tmp/foo.py', 'lineno': 1,
        'msg': 'A debug message', 'args': (),
        'exc_info': None, 'func': 'myfunction',
    })

    assert record.levelno == logging.DEBUG


def test_storage_logging_internals(storage):
    import logging
    import sys

    job_id = 'job-test-storage-logging'
    build_id = storage.create_build(job_id, {})

    storage.log_message(build_id, logging.LogRecord(**{
        'name': 'mylogger', 'level': logging.DEBUG,
        'pathname': '/tmp/foo.py', 'lineno': 1,
        'msg': 'A debug message', 'args': (),
        'exc_info': None, 'func': 'myfunction',
    }))

    storage.log_message(build_id, logging.LogRecord(**{
        'name': 'mylogger', 'level': logging.INFO,
        'pathname': '/tmp/foo.py', 'lineno': 1,
        'msg': 'An info message', 'args': (),
        'exc_info': None, 'func': 'myfunction',
    }))

    storage.log_message(build_id, logging.LogRecord(**{
        'name': 'mylogger', 'level': logging.WARNING,
        'pathname': '/tmp/foo.py', 'lineno': 1,
        'msg': 'A warning message', 'args': (),
        'exc_info': None, 'func': 'myfunction',
    }))

    storage.log_message(build_id, logging.LogRecord(**{
        'name': 'mylogger', 'level': logging.ERROR,
        'pathname': '/tmp/foo.py', 'lineno': 1,
        'msg': 'An error message', 'args': (),
        'exc_info': None, 'func': 'myfunction',
    }))

    try:
        raise ValueError("This is an exception")

    except:
        storage.log_message(build_id, logging.LogRecord(**{
            'name': 'mylogger', 'level': logging.ERROR,
            'pathname': '/tmp/foo.py', 'lineno': 1,
            'msg': 'An error message', 'args': (),
            'exc_info': sys.exc_info(),
            'func': 'myfunction',
        }))

    # ------------------------------------------------------------

    assert len(list(storage.iter_log_messages(build_id))) == 5
    assert len(list(storage.iter_log_messages(
        build_id, min_level=logging.DEBUG))) == 5
    assert len(list(storage.iter_log_messages(
        build_id, min_level=logging.INFO))) == 4
    assert len(list(storage.iter_log_messages(
        build_id, min_level=logging.WARNING))) == 3
    assert len(list(storage.iter_log_messages(
        build_id, min_level=logging.ERROR))) == 2
    assert len(list(storage.iter_log_messages(
        build_id, min_level=logging.CRITICAL))) == 0


def test_logging_with_context(storage):
    import logging
    from jobcontrol.core import JobExecutionContext, JobControl
    from jobcontrol.config import JobControlConfig

    logger = logging.getLogger('foo_logger')

    build_id = storage.create_build('foo')
    jc = JobControl(storage=storage, config=JobControlConfig())

    jc._install_log_handler()

    logger.debug('This will be ignored')
    logger.info('This will be ignored')
    logger.error('This will be ignored')

    with JobExecutionContext(app=jc, job_id='foo', build_id=build_id):
        logger.debug('This is a log message [D]')
        logger.info('This is a log message [I]')
        logger.warning('This is a log message [W]')
        logger.error('This is a log message [E]')
        try:
            raise ValueError('foobar')
        except:
            logger.exception('Shit happens')

    logger.info('This will get ignored as well')

    # ------------------------------------------------------------

    assert len(list(storage.iter_log_messages(build_id))) == 5
