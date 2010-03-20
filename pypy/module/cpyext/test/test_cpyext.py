import sys

import py

from pypy.conftest import gettestobjspace
from pypy.interpreter.error import OperationError
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.translator.tool.cbuild import ExternalCompilationInfo
from pypy.translator import platform
from pypy.module.cpyext import api
from pypy.translator.goal import autopath


@api.cpython_api([], api.PyObject)
def PyPy_Crash1(space):
    1/0

@api.cpython_api([], lltype.Signed)
def PyPy_Crash2(space):
    1/0

class TestApi():
    def test_signature(self):
        assert 'Py_InitModule' in api.FUNCTIONS
        assert api.FUNCTIONS['Py_InitModule'].argtypes == [
            rffi.CCHARP, lltype.Ptr(api.TYPES['PyMethodDef'])]
        assert api.FUNCTIONS['Py_InitModule'].restype == lltype.Void

def compile_module(modname, code, **kwds):
    eci = ExternalCompilationInfo(
        separate_module_sources=[code],
        export_symbols=['init%s' % (modname,)],
        include_dirs=api.include_dirs,
        **kwds
        )
    eci = eci.convert_sources_to_files()
    soname = platform.platform.compile(
        [], eci,
        standalone=False)
    return str(soname)

class AppTestCpythonExtensionBase:
    def setup_class(cls):
        cls.api_library = api.build_bridge(cls.space, rename=True)

    def import_module(self, name, init, body=''):
        code = """
        #include <pypy_rename.h>
        #include <Python.h>
        %(body)s

        void init%(name)s(void) {
        %(init)s
        }
        """ % dict(name=name, init=init, body=body)
        if sys.platform == 'win32':
            libraries = [self.api_library]
            mod = compile_module(name, code, libraries=libraries)
        else:
            libraries = [str(self.api_library+'.so')]
            mod = compile_module(name, code, link_files=libraries)
        import ctypes
        initfunc = ctypes.CDLL(mod)['init%s' % (name,)]
        initfunc()
        return self.space.getitem(
            self.space.sys.get('modules'),
            self.space.wrap(name))

    def setup_method(self, func):
        self.w_import_module = self.space.wrap(self.import_module)

    def teardown_method(self, func):
        try:
            self.space.delitem(self.space.sys.get('modules'),
                               self.space.wrap('foo'))
        except OperationError:
            pass

class AppTestCpythonExtension(AppTestCpythonExtensionBase):
    def test_createmodule(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", NULL);
        """
        self.import_module(name='foo', init=init)
        assert 'foo' in sys.modules

    def test_export_function(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        PyObject* foo_pi(PyObject* self, PyObject *args)
        {
            return PyFloat_FromDouble(3.14);
        }
        static PyMethodDef methods[] = {
            { "return_pi", foo_pi, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert 'foo' in sys.modules
        assert 'return_pi' in dir(module)
        assert module.return_pi is not None
        assert module.return_pi() == 3.14

    def test_export_function2(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        static PyObject* my_objects[1];
        static PyObject* foo_cached_pi(PyObject* self, PyObject *args)
        {
            if (my_objects[0] == NULL) {
                my_objects[0] = PyFloat_FromDouble(3.14);
                Py_INCREF(my_objects[0]);
            }
            return my_objects[0];
        }
        static PyObject* foo_drop_pi(PyObject* self, PyObject *args)
        {
            if (my_objects[0] != NULL) {
                Py_DECREF(my_objects[0]);
                my_objects[0] = NULL;
            }
            Py_INCREF(Py_None);
            return Py_None;
        }
        static PyObject* foo_retinvalid(PyObject* self, PyObject *args)
        {
            return (PyObject*)0xAFFEBABE;
        }
        static PyMethodDef methods[] = {
            { "return_pi", foo_cached_pi, METH_NOARGS },
            { "drop_pi",   foo_drop_pi, METH_NOARGS },
            { "return_invalid_pointer", foo_retinvalid, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        assert module.return_pi() == 3.14
        module.drop_pi()
        module.drop_pi()
        assert module.return_pi() == 3.14
        assert module.return_pi() == 3.14
        skip("Hmm, how to check for the exception?")
        raises(api.InvalidPointerException, module.return_invalid_pointer)

    def test_exception(self):
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        static PyObject* foo_pi(PyObject* self, PyObject *args)
        {
            PyErr_SetString(PyExc_Exception, "moo!");
            return NULL;
        }
        static PyMethodDef methods[] = {
            { "raise_exception", foo_pi, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        exc = raises(Exception, module.raise_exception)
        if type(exc.value) is not Exception:
            raise exc.value

        assert exc.value.message == "moo!"

    def test_internal_exceptions(self):
        skip("Useful to see how programming errors look like")
        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", methods);
        """
        body = """
        static PyObject* foo_crash1(PyObject* self, PyObject *args)
        {
            return PyPy_Crash1();
        }
        static PyObject* foo_crash2(PyObject* self, PyObject *args)
        {
            int a = PyPy_Crash2();
            if (a == -1)
                return NULL;
            return PyFloat_FromDouble(a);
        }
        static PyMethodDef methods[] = {
            { "crash1", foo_crash1, METH_NOARGS },
            { "crash2", foo_crash2, METH_NOARGS },
            { NULL }
        };
        """
        module = self.import_module(name='foo', init=init, body=body)
        module.crash1()
        module.crash2()

