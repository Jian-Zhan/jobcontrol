def job_simple_echo(*args, **kwargs):
    return (args, kwargs)


def job_with_progress():
    from jobcontrol.globals import current_app
    job_run = current_app.get_current_job_run()
    for i in xrange(11):
        job_run.set_progress(i, 10)
    return "DONE"


def job_with_logging():
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.debug('This is a debug message')
    logger.info('This is a info message')
    logger.warning('This is a warning message')
    logger.error('This is a error message')
    logger.critical('This is a critical message')

    try:
        raise ValueError('Foobar')
    except:
        logger.exception('This is an exception message')


def job_failing_once():
    """
    This job will fail exactly once; retry will be successful
    """
    from jobcontrol.globals import current_job
    exec_count = len(list(current_job.iter_runs()))

    if exec_count <= 1:
        # This is the first run
        raise RuntimeError("Simulating failure")

    return exec_count


def job_dep_A():
    return 'A'


def job_dep_B():
    from jobcontrol.globals import current_job
    dependencies = current_job.dependencies

    if len(dependencies) != 1:
        raise RuntimeError("Expected 1 dependency, got {0}"
                           .format(len(dependencies)))

    latest_run = list(dependencies[0].iter_runs())[-1]
    res = latest_run.get_result()

    return res + 'B'


def job_dep_C():
    from jobcontrol.globals import current_job
    dependencies = current_job.dependencies

    if len(dependencies) != 1:
        raise RuntimeError("Expected 1 dependency, got {0}"
                           .format(len(dependencies)))

    latest_run = list(dependencies[0].iter_runs())[-1]
    res = latest_run.get_result()

    return res + 'C'
