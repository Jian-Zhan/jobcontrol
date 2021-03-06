from functools import partial

from jobcontrol.utils.local import LocalStack, LocalProxy


_out_ctx_error = """\
Tried to access execution context outside a job execution. \
"""


def _get_current_ctx():
    top = _execution_ctx_stack.top
    if top is None:
        raise RuntimeError(_out_ctx_error)
    return top


def _get_ctx_object(name):
    top = _execution_ctx_stack.top
    if top is None:
        raise RuntimeError(_out_ctx_error)
    return getattr(top, name)


_execution_ctx_stack = LocalStack()
execution_context = LocalProxy(_get_current_ctx)
current_app = LocalProxy(partial(_get_ctx_object, 'app'))
current_job = LocalProxy(partial(_get_ctx_object, 'current_job'))
current_build = LocalProxy(partial(_get_ctx_object, 'current_build'))
