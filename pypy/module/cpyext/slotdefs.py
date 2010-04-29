import re

from pypy.rpython.lltypesystem import rffi, lltype
from pypy.module.cpyext.api import generic_cpy_call, cpython_api, \
        PyObject
from pypy.module.cpyext.typeobjectdefs import unaryfunc, wrapperfunc,\
        ternaryfunc, PyTypeObjectPtr, binaryfunc, getattrfunc, lenfunc,\
        ssizeargfunc, ssizessizeargfunc, ssizeobjargproc
from pypy.module.cpyext.pyobject import from_ref
from pypy.module.cpyext.state import State
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.rlib.unroll import unrolling_iterable

space = None


def check_num_args(space, ob, n):
    from pypy.module.cpyext.tupleobject import PyTuple_CheckExact, \
            PyTuple_GET_SIZE
    if not PyTuple_CheckExact(space, ob):
        raise OperationError(space.w_SystemError,
            space.wrap("PyArg_UnpackTuple() argument list is not a tuple"))
    if n == PyTuple_GET_SIZE(space, ob):
        return
    raise operationerrfmt(space.w_TypeError,
        "expected %d arguments, got %d", n, PyTuple_GET_SIZE(space, ob))

def wrap_unaryfunc(space, w_self, w_args, func):
    func_unary = rffi.cast(unaryfunc, func)
    check_num_args(space, w_args, 0)
    return generic_cpy_call(space, func_unary, w_self)

def wrap_binaryfunc(space, w_self, w_args, func):
    func_binary = rffi.cast(binaryfunc, func)
    check_num_args(space, w_args, 1)
    args_w = space.fixedview(w_args)
    return generic_cpy_call(space, func_binary, w_self, args_w[0])

def wrap_getattr(space, w_self, w_args, func):
    func_target = rffi.cast(getattrfunc, func)
    check_num_args(space, w_args, 1)
    args_w = space.fixedview(w_args)
    name_ptr = rffi.str2charp(space.str_w(args_w[0]))
    try:
        return generic_cpy_call(space, func_target, w_self, name_ptr)
    finally:
        rffi.free_charp(name_ptr)

def wrap_call(space, w_self, w_args, func, w_kwds):
    func_target = rffi.cast(ternaryfunc, func)
    return generic_cpy_call(space, func_target, w_self, w_args, w_kwds)

def wrap_lenfunc(space, w_self, w_args, func):
    func_len = rffi.cast(lenfunc, func)
    check_num_args(space, w_args, 0)
    return space.wrap(generic_cpy_call(space, func_len, w_self))

def wrap_sq_item(space, w_self, w_args, func):
    func_target = rffi.cast(ssizeargfunc, func)
    check_num_args(space, w_args, 1)
    args_w = space.fixedview(w_args)
    index = space.int_w(space.index(args_w[0]))
    return generic_cpy_call(space, func_target, w_self, index)

def wrap_sq_setitem(space, w_self, w_args, func):
    func_target = rffi.cast(ssizeobjargproc, func)
    check_num_args(space, w_args, 2)
    args_w = space.fixedview(w_args)
    index = space.int_w(space.index(args_w[0]))
    res = generic_cpy_call(space, func_target, w_self, index, args_w[1])
    if rffi.cast(lltype.Signed, res) == -1:
        space.fromcache(State).check_and_raise_exception(always=True)

def wrap_sq_delitem(space, w_self, w_args, func):
    func_target = rffi.cast(ssizeobjargproc, func)
    check_num_args(space, w_args, 1)
    args_w = space.fixedview(w_args)
    index = space.int_w(space.index(args_w[0]))
    null = lltype.nullptr(PyObject.TO)
    res = generic_cpy_call(space, func_target, w_self, index, null)
    if rffi.cast(lltype.Signed, res) == -1:
        space.fromcache(State).check_and_raise_exception(always=True)

def wrap_ssizessizeargfunc(space, w_self, w_args, func):
    func_target = rffi.cast(ssizessizeargfunc, func)
    check_num_args(space, w_args, 2)
    args_w = space.fixedview(w_args)
    start = space.int_w(args_w[0])
    end = space.int_w(args_w[1])
    return generic_cpy_call(space, func_target, w_self, start, end)

@cpython_api([PyTypeObjectPtr, PyObject, PyObject], PyObject, external=True)
def slot_tp_new(space, type, w_args, w_kwds):
    from pypy.module.cpyext.tupleobject import PyTuple_Check
    pyo = rffi.cast(PyObject, type)
    w_type = from_ref(space, pyo)
    w_func = space.getattr(w_type, space.wrap("__new__"))
    assert PyTuple_Check(space, w_args)
    args_w = [w_type] + space.fixedview(w_args)
    w_args_new = space.newtuple(args_w)
    return space.call(w_func, w_args_new, w_kwds)

PyWrapperFlag_KEYWORDS = 1

# adopted from typeobject.c
def FLSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC, FLAGS):
    wrapper = globals().get(WRAPPER, Ellipsis)
    if WRAPPER is None:
        wrapper = None
    if NAME == "__getattr__":
        wrapper = wrap_getattr
    function = globals().get(FUNCTION, None)
    slotname = ("c_" + SLOT).split(".")
    assert FLAGS == 0 or FLAGS == PyWrapperFlag_KEYWORDS
    if FLAGS:
        if wrapper is Ellipsis:
            def wrapper(space, w_self, w_args, func, w_kwds):
                raise NotImplementedError("Wrapper for slot " + NAME)
        wrapper1 = None
        wrapper2 = wrapper
    else:
        if wrapper is Ellipsis:
            def wrapper(space, w_self, w_args, func):
                raise NotImplementedError("Wrapper for slot " + NAME)
        wrapper1 = wrapper
        wrapper2 = None
    return (NAME, slotname, function, wrapper1, wrapper2, DOC)

def TPSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC):
    return FLSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC, 0)

ETSLOT = TPSLOT

def SQSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC):
    return ETSLOT(NAME, "tp_as_sequence.c_" + SLOT, FUNCTION, WRAPPER, DOC)
def MPSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC):
    return ETSLOT(NAME, "tp_as_mapping.c_" + SLOT, FUNCTION, WRAPPER, DOC)
def NBSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, WRAPPER, DOC)
def UNSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, WRAPPER,
            "x." + NAME + "() <==> " + DOC)
def IBSLOT(NAME, SLOT, FUNCTION, WRAPPER, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, WRAPPER,
            "x." + NAME + "(y) <==> x" + DOC + "y")
def BINSLOT(NAME, SLOT, FUNCTION, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, "wrap_binaryfunc_l", \
            "x." + NAME + "(y) <==> x" + DOC + "y")
def RBINSLOT(NAME, SLOT, FUNCTION, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, "wrap_binaryfunc_r", \
            "x." + NAME + "(y) <==> y" + DOC + "x")
def BINSLOTNOTINFIX(NAME, SLOT, FUNCTION, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, "wrap_binaryfunc_l", \
            "x." + NAME + "(y) <==> " + DOC)
def RBINSLOTNOTINFIX(NAME, SLOT, FUNCTION, DOC):
    return ETSLOT(NAME, "tp_as_number.c_" + SLOT, FUNCTION, "wrap_binaryfunc_r", \
            "x." + NAME + "(y) <==> " + DOC)

slotdef_replacements = (
    ("\s+", " "),
    ("static [^{]*{", "("),
    ("};", ")"),
    (r"(?P<start> +..SLOT\([^,]*, )(?P<fname>[^,]*), (?P<slotcname>[^,]*), (?P<wname>[^,]*)", r"\g<start>'\g<fname>', '\g<slotcname>', '\g<wname>'"),
    (r"(?P<start> *R?[^ ]{3}SLOT(NOTINFIX)?\([^,]*, )(?P<fname>[^,]*), (?P<slotcname>[^,]*)", r"\g<start>'\g<fname>', '\g<slotcname>'"),
    ("'NULL'", "None"),
    ("{NULL}", ""),
    ("\(wrapperfunc\)", ""),
    ("\),", "),\n"),
)

"""
    /* Heap types defining __add__/__mul__ have sq_concat/sq_repeat == NULL.
       The logic in abstract.c always falls back to nb_add/nb_multiply in
       this case.  Defining both the nb_* and the sq_* slots to call the
       user-defined methods has unexpected side-effects, as shown by
       test_descr.notimplemented() */
"""
# Instructions for update:
# Copy new slotdefs from typeobject.c
# Remove comments and tabs
# Done.
slotdefs_str = """
static slotdef slotdefs[] = {
        SQSLOT("__len__", sq_length, slot_sq_length, wrap_lenfunc,
               "x.__len__() <==> len(x)"),
        SQSLOT("__add__", sq_concat, NULL, wrap_binaryfunc,
          "x.__add__(y) <==> x+y"),
        SQSLOT("__mul__", sq_repeat, NULL, wrap_indexargfunc,
          "x.__mul__(n) <==> x*n"),
        SQSLOT("__rmul__", sq_repeat, NULL, wrap_indexargfunc,
          "x.__rmul__(n) <==> n*x"),
        SQSLOT("__getitem__", sq_item, slot_sq_item, wrap_sq_item,
               "x.__getitem__(y) <==> x[y]"),
        SQSLOT("__getslice__", sq_slice, slot_sq_slice, wrap_ssizessizeargfunc,
               "x.__getslice__(i, j) <==> x[i:j]\n\
               \n\
               Use of negative indices is not supported."),
        SQSLOT("__setitem__", sq_ass_item, slot_sq_ass_item, wrap_sq_setitem,
               "x.__setitem__(i, y) <==> x[i]=y"),
        SQSLOT("__delitem__", sq_ass_item, slot_sq_ass_item, wrap_sq_delitem,
               "x.__delitem__(y) <==> del x[y]"),
        SQSLOT("__setslice__", sq_ass_slice, slot_sq_ass_slice,
               wrap_ssizessizeobjargproc,
               "x.__setslice__(i, j, y) <==> x[i:j]=y\n\
               \n\
               Use  of negative indices is not supported."),
        SQSLOT("__delslice__", sq_ass_slice, slot_sq_ass_slice, wrap_delslice,
               "x.__delslice__(i, j) <==> del x[i:j]\n\
               \n\
               Use of negative indices is not supported."),
        SQSLOT("__contains__", sq_contains, slot_sq_contains, wrap_objobjproc,
               "x.__contains__(y) <==> y in x"),
        SQSLOT("__iadd__", sq_inplace_concat, NULL,
          wrap_binaryfunc, "x.__iadd__(y) <==> x+=y"),
        SQSLOT("__imul__", sq_inplace_repeat, NULL,
          wrap_indexargfunc, "x.__imul__(y) <==> x*=y"),

        MPSLOT("__len__", mp_length, slot_mp_length, wrap_lenfunc,
               "x.__len__() <==> len(x)"),
        MPSLOT("__getitem__", mp_subscript, slot_mp_subscript,
               wrap_binaryfunc,
               "x.__getitem__(y) <==> x[y]"),
        MPSLOT("__setitem__", mp_ass_subscript, slot_mp_ass_subscript,
               wrap_objobjargproc,
               "x.__setitem__(i, y) <==> x[i]=y"),
        MPSLOT("__delitem__", mp_ass_subscript, slot_mp_ass_subscript,
               wrap_delitem,
               "x.__delitem__(y) <==> del x[y]"),

        BINSLOT("__add__", nb_add, slot_nb_add,
                "+"),
        RBINSLOT("__radd__", nb_add, slot_nb_add,
                 "+"),
        BINSLOT("__sub__", nb_subtract, slot_nb_subtract,
                "-"),
        RBINSLOT("__rsub__", nb_subtract, slot_nb_subtract,
                 "-"),
        BINSLOT("__mul__", nb_multiply, slot_nb_multiply,
                "*"),
        RBINSLOT("__rmul__", nb_multiply, slot_nb_multiply,
                 "*"),
        BINSLOT("__div__", nb_divide, slot_nb_divide,
                "/"),
        RBINSLOT("__rdiv__", nb_divide, slot_nb_divide,
                 "/"),
        BINSLOT("__mod__", nb_remainder, slot_nb_remainder,
                "%"),
        RBINSLOT("__rmod__", nb_remainder, slot_nb_remainder,
                 "%"),
        BINSLOTNOTINFIX("__divmod__", nb_divmod, slot_nb_divmod,
                "divmod(x, y)"),
        RBINSLOTNOTINFIX("__rdivmod__", nb_divmod, slot_nb_divmod,
                 "divmod(y, x)"),
        NBSLOT("__pow__", nb_power, slot_nb_power, wrap_ternaryfunc,
               "x.__pow__(y[, z]) <==> pow(x, y[, z])"),
        NBSLOT("__rpow__", nb_power, slot_nb_power, wrap_ternaryfunc_r,
               "y.__rpow__(x[, z]) <==> pow(x, y[, z])"),
        UNSLOT("__neg__", nb_negative, slot_nb_negative, wrap_unaryfunc, "-x"),
        UNSLOT("__pos__", nb_positive, slot_nb_positive, wrap_unaryfunc, "+x"),
        UNSLOT("__abs__", nb_absolute, slot_nb_absolute, wrap_unaryfunc,
               "abs(x)"),
        UNSLOT("__nonzero__", nb_nonzero, slot_nb_nonzero, wrap_inquirypred,
               "x != 0"),
        UNSLOT("__invert__", nb_invert, slot_nb_invert, wrap_unaryfunc, "~x"),
        BINSLOT("__lshift__", nb_lshift, slot_nb_lshift, "<<"),
        RBINSLOT("__rlshift__", nb_lshift, slot_nb_lshift, "<<"),
        BINSLOT("__rshift__", nb_rshift, slot_nb_rshift, ">>"),
        RBINSLOT("__rrshift__", nb_rshift, slot_nb_rshift, ">>"),
        BINSLOT("__and__", nb_and, slot_nb_and, "&"),
        RBINSLOT("__rand__", nb_and, slot_nb_and, "&"),
        BINSLOT("__xor__", nb_xor, slot_nb_xor, "^"),
        RBINSLOT("__rxor__", nb_xor, slot_nb_xor, "^"),
        BINSLOT("__or__", nb_or, slot_nb_or, "|"),
        RBINSLOT("__ror__", nb_or, slot_nb_or, "|"),
        NBSLOT("__coerce__", nb_coerce, slot_nb_coerce, wrap_coercefunc,
               "x.__coerce__(y) <==> coerce(x, y)"),
        UNSLOT("__int__", nb_int, slot_nb_int, wrap_unaryfunc,
               "int(x)"),
        UNSLOT("__long__", nb_long, slot_nb_long, wrap_unaryfunc,
               "long(x)"),
        UNSLOT("__float__", nb_float, slot_nb_float, wrap_unaryfunc,
               "float(x)"),
        UNSLOT("__oct__", nb_oct, slot_nb_oct, wrap_unaryfunc,
               "oct(x)"),
        UNSLOT("__hex__", nb_hex, slot_nb_hex, wrap_unaryfunc,
               "hex(x)"),
        NBSLOT("__index__", nb_index, slot_nb_index, wrap_unaryfunc, 
               "x[y:z] <==> x[y.__index__():z.__index__()]"),
        IBSLOT("__iadd__", nb_inplace_add, slot_nb_inplace_add,
               wrap_binaryfunc, "+"),
        IBSLOT("__isub__", nb_inplace_subtract, slot_nb_inplace_subtract,
               wrap_binaryfunc, "-"),
        IBSLOT("__imul__", nb_inplace_multiply, slot_nb_inplace_multiply,
               wrap_binaryfunc, "*"),
        IBSLOT("__idiv__", nb_inplace_divide, slot_nb_inplace_divide,
               wrap_binaryfunc, "/"),
        IBSLOT("__imod__", nb_inplace_remainder, slot_nb_inplace_remainder,
               wrap_binaryfunc, "%"),
        IBSLOT("__ipow__", nb_inplace_power, slot_nb_inplace_power,
               wrap_binaryfunc, "**"),
        IBSLOT("__ilshift__", nb_inplace_lshift, slot_nb_inplace_lshift,
               wrap_binaryfunc, "<<"),
        IBSLOT("__irshift__", nb_inplace_rshift, slot_nb_inplace_rshift,
               wrap_binaryfunc, ">>"),
        IBSLOT("__iand__", nb_inplace_and, slot_nb_inplace_and,
               wrap_binaryfunc, "&"),
        IBSLOT("__ixor__", nb_inplace_xor, slot_nb_inplace_xor,
               wrap_binaryfunc, "^"),
        IBSLOT("__ior__", nb_inplace_or, slot_nb_inplace_or,
               wrap_binaryfunc, "|"),
        BINSLOT("__floordiv__", nb_floor_divide, slot_nb_floor_divide, "//"),
        RBINSLOT("__rfloordiv__", nb_floor_divide, slot_nb_floor_divide, "//"),
        BINSLOT("__truediv__", nb_true_divide, slot_nb_true_divide, "/"),
        RBINSLOT("__rtruediv__", nb_true_divide, slot_nb_true_divide, "/"),
        IBSLOT("__ifloordiv__", nb_inplace_floor_divide,
               slot_nb_inplace_floor_divide, wrap_binaryfunc, "//"),
        IBSLOT("__itruediv__", nb_inplace_true_divide,
               slot_nb_inplace_true_divide, wrap_binaryfunc, "/"),

        TPSLOT("__str__", tp_str, slot_tp_str, wrap_unaryfunc,
               "x.__str__() <==> str(x)"),
        TPSLOT("__str__", tp_print, NULL, NULL, ""),
        TPSLOT("__repr__", tp_repr, slot_tp_repr, wrap_unaryfunc,
               "x.__repr__() <==> repr(x)"),
        TPSLOT("__repr__", tp_print, NULL, NULL, ""),
        TPSLOT("__cmp__", tp_compare, _PyObject_SlotCompare, wrap_cmpfunc,
               "x.__cmp__(y) <==> cmp(x,y)"),
        TPSLOT("__hash__", tp_hash, slot_tp_hash, wrap_hashfunc,
               "x.__hash__() <==> hash(x)"),
        FLSLOT("__call__", tp_call, slot_tp_call, (wrapperfunc)wrap_call,
               "x.__call__(...) <==> x(...)", PyWrapperFlag_KEYWORDS),
        TPSLOT("__getattribute__", tp_getattro, slot_tp_getattr_hook,
               wrap_binaryfunc, "x.__getattribute__('name') <==> x.name"),
        TPSLOT("__getattribute__", tp_getattr, NULL, NULL, ""),
        TPSLOT("__getattr__", tp_getattro, slot_tp_getattr_hook, NULL, ""),
        TPSLOT("__getattr__", tp_getattr, NULL, NULL, ""),
        TPSLOT("__setattr__", tp_setattro, slot_tp_setattro, wrap_setattr,
               "x.__setattr__('name', value) <==> x.name = value"),
        TPSLOT("__setattr__", tp_setattr, NULL, NULL, ""),
        TPSLOT("__delattr__", tp_setattro, slot_tp_setattro, wrap_delattr,
               "x.__delattr__('name') <==> del x.name"),
        TPSLOT("__delattr__", tp_setattr, NULL, NULL, ""),
        TPSLOT("__lt__", tp_richcompare, slot_tp_richcompare, richcmp_lt,
               "x.__lt__(y) <==> x<y"),
        TPSLOT("__le__", tp_richcompare, slot_tp_richcompare, richcmp_le,
               "x.__le__(y) <==> x<=y"),
        TPSLOT("__eq__", tp_richcompare, slot_tp_richcompare, richcmp_eq,
               "x.__eq__(y) <==> x==y"),
        TPSLOT("__ne__", tp_richcompare, slot_tp_richcompare, richcmp_ne,
               "x.__ne__(y) <==> x!=y"),
        TPSLOT("__gt__", tp_richcompare, slot_tp_richcompare, richcmp_gt,
               "x.__gt__(y) <==> x>y"),
        TPSLOT("__ge__", tp_richcompare, slot_tp_richcompare, richcmp_ge,
               "x.__ge__(y) <==> x>=y"),
        TPSLOT("__iter__", tp_iter, slot_tp_iter, wrap_unaryfunc,
               "x.__iter__() <==> iter(x)"),
        TPSLOT("next", tp_iternext, slot_tp_iternext, wrap_next,
               "x.next() -> the next value, or raise StopIteration"),
        TPSLOT("__get__", tp_descr_get, slot_tp_descr_get, wrap_descr_get,
               "descr.__get__(obj[, type]) -> value"),
        TPSLOT("__set__", tp_descr_set, slot_tp_descr_set, wrap_descr_set,
               "descr.__set__(obj, value)"),
        TPSLOT("__delete__", tp_descr_set, slot_tp_descr_set,
               wrap_descr_delete, "descr.__delete__(obj)"),
        FLSLOT("__init__", tp_init, slot_tp_init, (wrapperfunc)wrap_init,
               "x.__init__(...) initializes x; "
               "see x.__class__.__doc__ for signature",
               PyWrapperFlag_KEYWORDS),
        TPSLOT("__new__", tp_new, slot_tp_new, NULL, ""),
        TPSLOT("__del__", tp_del, slot_tp_del, NULL, ""),
        {NULL}
};
"""
for regex, repl in slotdef_replacements:
    slotdefs_str = re.sub(regex, repl, slotdefs_str)

slotdefs = unrolling_iterable(eval(slotdefs_str))

if __name__ == "__main__":
    print slotdefs_str