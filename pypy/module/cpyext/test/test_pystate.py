from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.rpython.lltypesystem.lltype import nullptr
from pypy.module.cpyext.pystate import PyInterpreterState, PyThreadState

class AppTestThreads(AppTestCpythonExtensionBase):
    def test_allow_threads(self):
        module = self.import_extension('foo', [
            ("test", "METH_NOARGS",
             """
                Py_BEGIN_ALLOW_THREADS
                {
                    Py_BLOCK_THREADS
                    Py_UNBLOCK_THREADS
                }
                Py_END_ALLOW_THREADS
                Py_RETURN_NONE;
             """),
            ])
        # Should compile at least
        module.test()

class TestInterpreterState(BaseApiTest):
    def test_interpreter_head(self, space, api):
        state = api.PyInterpreterState_Head()
        assert state != nullptr(PyInterpreterState.TO)

    def test_interpreter_next(self, space, api):
        state = api.PyInterpreterState_Head()
        assert nullptr(PyInterpreterState.TO) == api.PyInterpreterState_Next(state)

def clear_threadstate(space):
    # XXX: this should collect the ThreadState memory
    del space.getexecutioncontext().cpyext_threadstate

class TestThreadState(BaseApiTest):
    def test_thread_state_get(self, space, api):
        ts = api.PyThreadState_Get()
        assert ts != nullptr(PyThreadState.TO)
        clear_threadstate(space)

    def test_thread_state_interp(self, space, api):
        ts = api.PyThreadState_Get()
        assert ts.c_interp == api.PyInterpreterState_Head()
        clear_threadstate(space)
