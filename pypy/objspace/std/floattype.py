import math
import sys
from pypy.rlib.unroll import unrolling_iterable
from pypy.interpreter import gateway
from pypy.interpreter.baseobjspace import ObjSpace, W_Root
from pypy.interpreter.error import OperationError
from pypy.objspace.std.stdtypedef import StdTypeDef, SMM
from pypy.objspace.std.strutil import ParseStringError
from pypy.objspace.std.strutil import interp_string_to_float
from pypy.module.sys import system


float_as_integer_ratio = SMM("as_integer_ratio", 1)
float_hex = SMM("hex", 1)


def descr__new__(space, w_floattype, w_x=0.0):
    from pypy.objspace.std.floatobject import W_FloatObject
    w_value = w_x     # 'x' is the keyword argument name in CPython
    w_special = space.lookup(w_value, "__float__")
    if w_special is not None:
        w_obj = space.get_and_call_function(w_special, w_value)
        if not space.isinstance_w(w_obj, space.w_float):
            raise OperationError(space.w_TypeError,
                                 space.wrap("__float__ returned non-float"))
        if space.is_w(w_floattype, space.w_float):
            return w_obj
        value = space.float_w(w_obj)
    elif space.is_true(space.isinstance(w_value, space.w_str)):
        strvalue = space.str_w(w_value)
        try:
            value = interp_string_to_float(space, strvalue)
        except ParseStringError, e:
            raise OperationError(space.w_ValueError,
                                 space.wrap(e.msg))
    elif space.is_true(space.isinstance(w_value, space.w_unicode)):
        if space.config.objspace.std.withropeunicode:
            from pypy.objspace.std.ropeunicodeobject import unicode_to_decimal_w
        else:
            from unicodeobject import unicode_to_decimal_w
        strvalue = unicode_to_decimal_w(space, w_value)
        try:
            value = interp_string_to_float(space, strvalue)
        except ParseStringError, e:
            raise OperationError(space.w_ValueError,
                                 space.wrap(e.msg))
    else:
        value = space.float_w(w_x)
    w_obj = space.allocate_instance(W_FloatObject, w_floattype)
    W_FloatObject.__init__(w_obj, value)
    return w_obj


_float_format = float.__getformat__("float")
_double_format = float.__getformat__("double")
def descr___getformat__(space, w_cls, kind):
    if kind == "float":
        return space.wrap(_float_format)
    elif kind == "double":
        return space.wrap(_double_format)
    raise OperationError(space.w_ValueError,
                         space.wrap("only float and double are valid"))

_alpha = zip("abcdef", range(10, 16)) + zip("ABCDEF", range(10, 16))
_hex_to_int = zip("0123456789", range(10)) + _alpha
_hex_to_int_iterable = unrolling_iterable(_hex_to_int)
def _hex_from_char(c):
    for h, v in _hex_to_int_iterable:
        if h == c:
            return v
    return -1

def _hex_digit(s, j, co_end, float_digits):
    if j < float_digits:
        i = co_end - j
    else:
        i = co_end - 1 - j
    return _hex_from_char(s[i])

def descr_fromhex(space, w_cls, s):
    length = len(s)
    i = 0
    while i < length and s[i].isspace():
        i += 1
    if i == length:
        raise OperationError(space.w_ValueError,
                             space.wrap("invalid hex string"))
    sign = 1
    if s[i] == "-":
        sign = -1
        i += 1
    elif s[i] == "+":
        i += 1
    if length == i:
        raise OperationError(space.w_ValueError,
                             space.wrap("invalid hex string"))
    if s[i] == "i" or s[i] == "I":
        i += 1
        if length - i >= 2 and s[i:i + 2].lower() == "nf":
            i += 2
            value = float("inf")
            if length - i >= 5 and s[i:i + 5].lower() == "inity":
                i += 5
    elif s[i] == "n" or s[i] == "N":
        i += 1
        if length - i >= 2 and s[i:i + 2].lower() == "an":
            i += 2
            value = float("nan")
    else:
        if (s[i] == "0" and length - i > 1 and
            (s[i + 1] == "x" or s[i + 1] == "X")):
            i += 2
        co_start = i
        while i < length and _hex_from_char(s[i]) >= 0:
            i += 1
        whole_end = i
        if i < length and s[i] == ".":
            i += 1
            while i < length and _hex_from_char(s[i]) >= 0:
                i += 1
            co_end = i - 1
        else:
            co_end = i
        total_digits = co_end - co_start
        float_digits = co_end - whole_end
        if not total_digits:
            raise OperationError(space.w_ValueError,
                                 space.wrap("invalid hex string"))
        const_one = system.DBL_MIN_EXP - system.DBL_MANT_DIG + sys.maxint // 2
        const_two = sys.maxint // 2 + 1 - system.DBL_MAX_EXP
        if total_digits > min(const_one, const_two) // 4:
            raise OperationError(space.w_ValueError, space.wrap("way too long"))
        if i < length and (s[i] == "p" or s[i] == "P"):
            if i == length:
                raise OperationError(space.w_ValueError,
                                     space.wrap("invalid hex string"))
            i += 1
            exp_start = i
            if s[i] == "-" or s[i] == "+":
                i += 1
                if i == length:
                    raise OperationError(space.w_ValueError,
                                         space.wrap("invalid hex string"))
            if not s[i].isdigit():
                raise OperationError(space.w_ValueError,
                                     space.wrap("invalid hex string"))
            i += 1
            while i < length and s[i].isdigit():
                i += 1
            exp = int(s[exp_start:i])
        else:
            exp = 0
        while (total_digits and
               _hex_digit(s, total_digits - 1, co_end, float_digits) == 0):
            total_digits -= 1
        if not total_digits or exp < -sys.maxint / 2:
            value = 0.0
        elif exp > sys.maxint // 2:
            raise OperationError(space.w_OverflowError, space.wrap("too large"))
        else:
            exp -=  4 * float_digits
            top_exp = exp + 4 * (total_digits - 1)
            digit = _hex_digit(s, total_digits - 1, co_end, float_digits)
            while digit:
                top_exp += 1
                digit //= 2
            if top_exp < system.DBL_MIN_EXP - system.DBL_MANT_DIG:
                value = 0.0
            elif top_exp > system.DBL_MAX_EXP:
                raise OperationError(space.w_OverflowError,
                                     space.wrap("too large"))
            else:
                lsb = max(top_exp, system.DBL_MIN_EXP) - system.DBL_MANT_DIG
                value = 0
                if exp >= lsb:
                    for j in range(total_digits - 1, -1, -1):
                        value = 16.0 * value + _hex_digit(s, j, co_end,
                                                          float_digits)
                    value = math.ldexp(value, exp)
                else:
                    half_eps = 1 << ((lsb - exp - 1) % 4)
                    key_digit = (lsb - exp - 1) // 4
                    for j in range(total_digits - 1, key_digit, -1):
                        value = 16.0 * value + _hex_digit(s, j, co_end,
                                                          float_digits)
                    digit = _hex_digit(s, key_digit, co_end, float_digits)
                    value = 16.0 * value + (digit & (16 - 2*half_eps))
                    if digit & half_eps:
                        round_up = False
                        if (digit & (3 * half_eps - 1) or
                            (half_eps == 8 and
                             _hex_digit(s, key_digit + 1, co_end, float_digits) & 1)):
                            round_up = True
                        else:
                            for j in range(key_digit - 1, -1, -1):
                                if _hex_digit(s, j, co_end, float_digits):
                                    round_up = True
                                    break
                        if round_up:
                            value += 2 * half_eps
                            mant_dig = system.DBL_MANT_DIG
                            if (top_exp == system.DBL_MAX_EXP and
                                value == math.ldexp(2 * half_eps, mant_dig)):
                                raise OperationError(space.w_OverflowError,
                                                     space.wrap("too large"))
                    value = math.ldexp(value, (exp + 4*key_digit))
    while i < length and s[i].isspace():
        i += 1
    if i != length:
        raise OperationError(space.w_ValueError,
                             space.wrap("invalid hex string"))
    w_float = space.wrap(sign * value)
    return space.call_function(w_cls, w_float)


# ____________________________________________________________

float_typedef = StdTypeDef("float",
    __doc__ = '''float(x) -> floating point number

Convert a string or number to a floating point number, if possible.''',
    __new__ = gateway.interp2app(descr__new__),
    __getformat__ = gateway.interp2app(descr___getformat__,
                                       unwrap_spec=[ObjSpace, W_Root, str],
                                       as_classmethod=True),
    fromhex = gateway.interp2app(descr_fromhex,
                                 unwrap_spec=[ObjSpace, W_Root, str],
                                 as_classmethod=True),
    )
float_typedef.registermethods(globals())
