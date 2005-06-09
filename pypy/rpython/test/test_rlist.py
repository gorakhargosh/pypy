from pypy.translator.translator import Translator
from pypy.rpython.lltype import *
from pypy.rpython.rtyper import RPythonTyper
from pypy.rpython.rlist import *
from pypy.rpython.rslice import ll_newslice
from pypy.rpython.rint import signed_repr


def sample_list():
    rlist = ListRepr(signed_repr)
    rlist.setup()
    l = ll_newlist(rlist.lowleveltype, 3)
    ll_setitem(l, 0, 42)
    ll_setitem(l, -2, 43)
    ll_setitem_nonneg(l, 2, 44)
    ll_append(l, 45)
    return l

def check_list(l1, expected):
    assert ll_len(l1) == len(expected)
    for i, x in zip(range(len(expected)), expected):
        assert ll_getitem_nonneg(l1, i) == x

def test_rlist_basic():
    l = sample_list()
    assert ll_getitem(l, -4) == 42
    assert ll_getitem_nonneg(l, 1) == 43
    assert ll_getitem(l, 2) == 44
    assert ll_getitem(l, 3) == 45
    assert ll_len(l) == 4
    check_list(l, [42, 43, 44, 45])

def test_rlist_extend_concat():
    l = sample_list()
    ll_extend(l, l)
    check_list(l, [42, 43, 44, 45] * 2)
    l1 = ll_concat(l, l)
    assert l1 != l
    check_list(l1, [42, 43, 44, 45] * 4)

def test_rlist_slice():
    l = sample_list()
    check_list(ll_listslice_startonly(l, 0), [42, 43, 44, 45])
    check_list(ll_listslice_startonly(l, 1), [43, 44, 45])
    check_list(ll_listslice_startonly(l, 2), [44, 45])
    check_list(ll_listslice_startonly(l, 3), [45])
    check_list(ll_listslice_startonly(l, 4), [])
    for start in range(5):
        for stop in range(start, 5):
            s = ll_newslice(start, stop)
            check_list(ll_listslice(l, s), [42, 43, 44, 45][start:stop])

# ____________________________________________________________

def rtype(fn, argtypes=[]):
    t = Translator(fn)
    t.annotate(argtypes)
    typer = RPythonTyper(t.annotator)
    typer.specialize()
    #t.view()
    t.checkgraphs()
    return t


def test_simple():
    def dummyfn():
        l = [10,20,30]
        return l[2]
    rtype(dummyfn)

def test_append():
    def dummyfn():
        l = []
        l.append(5)
        l.append(6)
        return l[0]
    rtype(dummyfn)

def test_len():
    def dummyfn():
        l = [5,10]
        return len(l)
    rtype(dummyfn)

def test_iterate():
    def dummyfn():
        total = 0
        for x in [1,3,5,7,9]:
            total += x
        return total
    rtype(dummyfn)

def test_recursive():
    def dummyfn(N):
        l = []
        while N > 0:
            l = [l]
            N -= 1
        return len(l)
    rtype(dummyfn, [int]) #.view()

def test_add():
    def dummyfn():
        l = [5]
        l += [6,7]
        return l + [8]
    rtype(dummyfn)

def test_slice():
    def dummyfn():
        l = [5, 6, 7, 8, 9]
        return l[:2], l[1:4], l[3:]
    rtype(dummyfn).view()
