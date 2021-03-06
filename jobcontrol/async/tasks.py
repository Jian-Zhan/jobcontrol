from celery import Celery


app = Celery()
app.conf.JOBCONTROL = None
# app.conf.CELERY_ACCEPT_CONTENT = ['pickle', 'json', 'msgpack', 'yaml']
app.conf.CELERY_ACCEPT_CONTENT = ['json']
app.conf.CELERY_TASK_SERIALIZER = 'json'


@app.task
def build_job(job_id):
    jc = app.conf.JOBCONTROL
    return jc.build_job(job_id)


@app.task
def run_build(build_id):
    jc = app.conf.JOBCONTROL
    return jc.run_build(build_id)
