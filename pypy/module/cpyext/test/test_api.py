from pypy.conftest import gettestobjspace
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.interpreter.baseobjspace import W_Root
from pypy.module.cpyext.state import State
from pypy.module.cpyext import api
from pypy.module.cpyext.test.test_cpyext import freeze_refcnts, check_and_print_leaks
PyObject = api.PyObject
from pypy.interpreter.error import OperationError
from pypy.module.cpyext.state import State

@api.cpython_api([PyObject], lltype.Void)
def PyPy_GetWrapped(space, w_arg):
    assert isinstance(w_arg, W_Root)
@api.cpython_api([PyObject], lltype.Void)
def PyPy_GetReference(space, arg):
    assert lltype.typeOf(arg) ==  PyObject

class BaseApiTest:
    def setup_class(cls):
        cls.space = gettestobjspace(usemodules=['cpyext', 'thread'])
        cls.space.getbuiltinmodule("cpyext")
        class CAPI:
            def __getattr__(self, name):
                return getattr(cls.space, name)
        cls.api = CAPI()
        CAPI.__dict__.update(api.INTERPLEVEL_API)

    def raises(self, space, api, expected_exc, f, *args):
        if not callable(f):
            raise Exception("%s is not callable" % (f,))
        f(*args)
        state = space.fromcache(State)
        tp = state.exc_type
        if not tp:
            raise Exception("DID NOT RAISE")
        if getattr(space, 'w_' + expected_exc.__name__) is not tp:
            raise Exception("Wrong exception")
        state.clear_exception()

    def setup_method(self, func):
        freeze_refcnts(self)

    def teardown_method(self, func):
        state = self.space.fromcache(State)
        try:
            state.check_and_raise_exception()
        except OperationError, e:
            print e.errorstr(self.space)
            raise
        if check_and_print_leaks(self):
            assert False, "Test leaks or loses object(s)."

class TestConversion(BaseApiTest):
    def test_conversions(self, space, api):
        api.PyPy_GetWrapped(space.w_None)
        api.PyPy_GetReference(space.w_None)
