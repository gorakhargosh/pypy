from pypy.jit.metainterp.history import Box, BoxInt, LoopToken, BoxFloat,\
     ConstFloat
from pypy.jit.metainterp.history import Const, ConstInt, ConstPtr, ConstObj, REF
from pypy.jit.metainterp.resoperation import rop, ResOperation
from pypy.jit.metainterp import jitprof
from pypy.jit.metainterp.executor import execute_nonspec
from pypy.jit.metainterp.optimizeutil import _findall, sort_descrs
from pypy.jit.metainterp.optimizeutil import descrlist_dict
from pypy.jit.metainterp.optimizeutil import InvalidLoop, args_dict
from pypy.jit.metainterp import resume, compile
from pypy.jit.metainterp.typesystem import llhelper, oohelper
from pypy.rpython.lltypesystem import lltype
from pypy.jit.metainterp.history import AbstractDescr, make_hashable_int
from pypy.jit.metainterp.optimizeopt.intutils import IntBound, IntUnbounded
from pypy.tool.pairtype import extendabletype

LEVEL_UNKNOWN    = '\x00'
LEVEL_NONNULL    = '\x01'
LEVEL_KNOWNCLASS = '\x02'     # might also mean KNOWNARRAYDESCR, for arrays
LEVEL_CONSTANT   = '\x03'

import sys
MAXINT = sys.maxint
MININT = -sys.maxint - 1

class OptValue(object):
    __metaclass__ = extendabletype
    _attrs_ = ('box', 'known_class', 'last_guard_index', 'level', 'intbound')
    last_guard_index = -1

    level = LEVEL_UNKNOWN
    known_class = None
    intbound = None

    def __init__(self, box):
        self.box = box
        self.intbound = IntBound(MININT, MAXINT) #IntUnbounded()
        if isinstance(box, Const):
            self.make_constant(box)
        # invariant: box is a Const if and only if level == LEVEL_CONSTANT

    def force_box(self):
        return self.box

    def get_key_box(self):
        return self.box

    def get_args_for_fail(self, modifier):
        pass

    def make_virtual_info(self, modifier, fieldnums):
        raise NotImplementedError # should not be called on this level

    def is_constant(self):
        return self.level == LEVEL_CONSTANT

    def is_null(self):
        if self.is_constant():
            box = self.box
            assert isinstance(box, Const)
            return not box.nonnull()
        return False

    def make_constant(self, constbox):
        """Replace 'self.box' with a Const box."""
        assert isinstance(constbox, Const)
        self.box = constbox
        self.level = LEVEL_CONSTANT
        if isinstance(constbox, ConstInt):
            val = constbox.getint()
            self.intbound = IntBound(val, val)
        else:
            self.intbound = IntUnbounded()

    def get_constant_class(self, cpu):
        level = self.level
        if level == LEVEL_KNOWNCLASS:
            return self.known_class
        elif level == LEVEL_CONSTANT:
            return cpu.ts.cls_of_box(self.box)
        else:
            return None

    def make_constant_class(self, classbox, opindex):
        assert self.level < LEVEL_KNOWNCLASS
        self.known_class = classbox
        self.level = LEVEL_KNOWNCLASS
        self.last_guard_index = opindex

    def make_nonnull(self, opindex):
        assert self.level < LEVEL_NONNULL
        self.level = LEVEL_NONNULL
        self.last_guard_index = opindex

    def is_nonnull(self):
        level = self.level
        if level == LEVEL_NONNULL or level == LEVEL_KNOWNCLASS:
            return True
        elif level == LEVEL_CONSTANT:
            box = self.box
            assert isinstance(box, Const)
            return box.nonnull()
        else:
            return False

    def ensure_nonnull(self):
        if self.level < LEVEL_NONNULL:
            self.level = LEVEL_NONNULL

    def is_virtual(self):
        # Don't check this with 'isinstance(_, VirtualValue)'!
        # Even if it is a VirtualValue, the 'box' can be non-None,
        # meaning it has been forced.
        return self.box is None

    def getfield(self, ofs, default):
        raise NotImplementedError

    def setfield(self, ofs, value):
        raise NotImplementedError

    def getitem(self, index):
        raise NotImplementedError

    def getlength(self):
        raise NotImplementedError

    def setitem(self, index, value):
        raise NotImplementedError


class ConstantValue(OptValue):
    def __init__(self, box):
        self.make_constant(box)

CONST_0      = ConstInt(0)
CONST_1      = ConstInt(1)
CVAL_ZERO    = ConstantValue(CONST_0)
CVAL_ZERO_FLOAT = ConstantValue(ConstFloat(0.0))
CVAL_UNINITIALIZED_ZERO = ConstantValue(CONST_0)
llhelper.CVAL_NULLREF = ConstantValue(llhelper.CONST_NULL)
oohelper.CVAL_NULLREF = ConstantValue(oohelper.CONST_NULL)

class Optimization(object):
    def propagate_forward(self, op):
        raise NotImplementedError

    def emit_operation(self, op):
        self.next_optimization.propagate_forward(op)

    # FIXME: Move some of these here?
    def getvalue(self, box):
        return self.optimizer.getvalue(box)

    def make_constant(self, box, constbox):
        return self.optimizer.make_constant(box, constbox)

    def make_constant_int(self, box, intconst):
        return self.optimizer.make_constant_int(box, intconst)

    def make_equal_to(self, box, value):
        return self.optimizer.make_equal_to(box, value)

    def get_constant_box(self, box):
        return self.optimizer.get_constant_box(box)

    def new_box(self, fieldofs):
        return self.optimizer.new_box(fieldofs)

    def new_const(self, fieldofs):
        return self.optimizer.new_const(fieldofs)

    def new_box_item(self, arraydescr):
        return self.optimizer.new_box_item(arraydescr)

    def new_const_item(self, arraydescr):
        return self.optimizer.new_const_item(arraydescr)

    def pure(self, opnum, args, result):
        op = ResOperation(opnum, args, result)
        self.optimizer.pure_operations[self.optimizer.make_args_key(op)] = op

    def nextop(self):
        return self.optimizer.loop.operations[self.optimizer.i + 1]

    def skip_nextop(self):
        self.optimizer.i += 1

    def setup(self, virtuals):
        pass

class Optimizer(Optimization):

    def __init__(self, metainterp_sd, loop, optimizations=None, virtuals=True):
        self.metainterp_sd = metainterp_sd
        self.cpu = metainterp_sd.cpu
        self.loop = loop
        self.values = {}
        self.interned_refs = self.cpu.ts.new_ref_dict()
        self.resumedata_memo = resume.ResumeDataLoopMemo(metainterp_sd)
        self.bool_boxes = {}
        self.loop_invariant_results = {}
        self.pure_operations = args_dict()
        self.producer = {}
        self.pendingfields = []

        if optimizations:
            self.first_optimization = optimizations[0]
            for i in range(1, len(optimizations)):
                optimizations[i - 1].next_optimization = optimizations[i]
            optimizations[-1].next_optimization = self
            for o in optimizations:
                o.optimizer = self
                o.setup(virtuals)
        else:
            self.first_optimization = self

    def forget_numberings(self, virtualbox):
        self.metainterp_sd.profiler.count(jitprof.OPT_FORCINGS)
        self.resumedata_memo.forget_numberings(virtualbox)

    def getinterned(self, box):
        constbox = self.get_constant_box(box)
        if constbox is None:
            return box
        if constbox.type == REF:
            value = constbox.getref_base()
            if not value:
                return box
            return self.interned_refs.setdefault(value, box)
        else:
            return box

    def getvalue(self, box):
        box = self.getinterned(box)
        try:
            value = self.values[box]
        except KeyError:
            value = self.values[box] = OptValue(box)
        return value

    def get_constant_box(self, box):
        if isinstance(box, Const):
            return box
        try:
            value = self.values[box]
        except KeyError:
            return None
        if value.is_constant():
            constbox = value.box
            assert isinstance(constbox, Const)
            return constbox
        return None

    def make_equal_to(self, box, value):
        assert isinstance(value, OptValue)
        assert box not in self.values
        self.values[box] = value

    def make_constant(self, box, constbox):
        self.make_equal_to(box, ConstantValue(constbox))

    def make_constant_int(self, box, intvalue):
        self.make_constant(box, ConstInt(intvalue))

    def new_ptr_box(self):
        return self.cpu.ts.BoxRef()

    def new_box(self, fieldofs):
        if fieldofs.is_pointer_field():
            return self.new_ptr_box()
        elif fieldofs.is_float_field():
            return BoxFloat()
        else:
            return BoxInt()

    def new_const(self, fieldofs):
        if fieldofs.is_pointer_field():
            return self.cpu.ts.CVAL_NULLREF
        elif fieldofs.is_float_field():
            return CVAL_ZERO_FLOAT
        else:
            return CVAL_ZERO

    def new_box_item(self, arraydescr):
        if arraydescr.is_array_of_pointers():
            return self.new_ptr_box()
        elif arraydescr.is_array_of_floats():
            return BoxFloat()
        else:
            return BoxInt()

    def new_const_item(self, arraydescr):
        if arraydescr.is_array_of_pointers():
            return self.cpu.ts.CVAL_NULLREF
        elif arraydescr.is_array_of_floats():
            return CVAL_ZERO_FLOAT
        else:
            return CVAL_ZERO

    def propagate_all_forward(self):
        self.exception_might_have_happened = True
        # ^^^ at least at the start of bridges.  For loops, we could set
        # it to False, but we probably don't care
        self.newoperations = []
        self.i = 0
        while self.i < len(self.loop.operations):
            op = self.loop.operations[self.i]
            #print "OP: %s" % op
            self.first_optimization.propagate_forward(op)
            self.i += 1
        self.loop.operations = self.newoperations
        # accumulate counters
        self.resumedata_memo.update_counters(self.metainterp_sd.profiler)

    def send_extra_operation(self, op):
        self.first_optimization.propagate_forward(op)

    def propagate_forward(self, op):
        self.producer[op.result] = op
        opnum = op.getopnum()
        for value, func in optimize_ops:
            if opnum == value:
                func(self, op)
                break
        else:
            self.optimize_default(op)
        #print '\n'.join([str(o) for o in self.newoperations]) + '\n---\n'


    def emit_operation(self, op):
        ###self.heap_op_optimizer.emitting_operation(op)
        self._emit_operation(op)

    def _emit_operation(self, op):
        for i in range(op.numargs()):
            arg = op.getarg(i)
            if arg in self.values:
                box = self.values[arg].force_box()
                op.setarg(i, box)
        self.metainterp_sd.profiler.count(jitprof.OPT_OPS)
        if op.is_guard():
            self.metainterp_sd.profiler.count(jitprof.OPT_GUARDS)
            op = self.store_final_boxes_in_guard(op)
        elif op.can_raise():
            self.exception_might_have_happened = True
        elif op.returns_bool_result():
            self.bool_boxes[self.getvalue(op.result)] = None
        self.newoperations.append(op)

    def store_final_boxes_in_guard(self, op):
        ###pendingfields = self.heap_op_optimizer.force_lazy_setfields_for_guard()
        descr = op.getdescr()
        assert isinstance(descr, compile.ResumeGuardDescr)
        modifier = resume.ResumeDataVirtualAdder(descr, self.resumedata_memo)
        newboxes = modifier.finish(self.values, self.pendingfields)
        if len(newboxes) > self.metainterp_sd.options.failargs_limit: # XXX be careful here
            compile.giveup()
        descr.store_final_boxes(op, newboxes)
        #
        if op.getopnum() == rop.GUARD_VALUE:
            if self.getvalue(op.getarg(0)) in self.bool_boxes:
                # Hack: turn guard_value(bool) into guard_true/guard_false.
                # This is done after the operation is emitted to let
                # store_final_boxes_in_guard set the guard_opnum field of the
                # descr to the original rop.GUARD_VALUE.
                constvalue = op.getarg(1).getint()
                if constvalue == 0:
                    opnum = rop.GUARD_FALSE
                elif constvalue == 1:
                    opnum = rop.GUARD_TRUE
                else:
                    raise AssertionError("uh?")
                newop = ResOperation(opnum, [op.getarg(0)], op.result, descr)
                newop.setfailargs(op.getfailargs())
                return newop
            else:
                # a real GUARD_VALUE.  Make it use one counter per value.
                descr.make_a_counter_per_value(op)
        return op

    def make_args_key(self, op):
        args = []
        for i in range(op.numargs()):
            arg = op.getarg(i)
            if arg in self.values:
                args.append(self.values[arg].get_key_box())
            else:
                args.append(arg)
        args.append(ConstInt(op.getopnum()))
        return args

    def optimize_default(self, op):
        canfold = op.is_always_pure()
        is_ovf = op.is_ovf()
        if is_ovf:
            nextop = self.loop.operations[self.i + 1]
            canfold = nextop.getopnum() == rop.GUARD_NO_OVERFLOW
        if canfold:
            for i in range(op.numargs()):
                if self.get_constant_box(op.getarg(i)) is None:
                    break
            else:
                # all constant arguments: constant-fold away
                argboxes = [self.get_constant_box(op.getarg(i))
                            for i in range(op.numargs())]
                resbox = execute_nonspec(self.cpu, None,
                                         op.getopnum(), argboxes, op.getdescr())
                self.make_constant(op.result, resbox.constbox())
                if is_ovf:
                    self.i += 1 # skip next operation, it is the unneeded guard
                return

            # did we do the exact same operation already?
            args = self.make_args_key(op)
            oldop = self.pure_operations.get(args, None)
            if oldop is not None and oldop.getdescr() is op.getdescr():
                assert oldop.getopnum() == op.getopnum()
                self.make_equal_to(op.result, self.getvalue(oldop.result))
                if is_ovf:
                    self.i += 1 # skip next operation, it is the unneeded guard
                return
            else:
                self.pure_operations[args] = op

        # otherwise, the operation remains
        self.emit_operation(op)

    def optimize_GUARD_NO_OVERFLOW(self, op):
        # otherwise the default optimizer will clear fields, which is unwanted
        # in this case
        self.emit_operation(op)

    def optimize_DEBUG_MERGE_POINT(self, op):
        self.emit_operation(op)

optimize_ops = _findall(Optimizer, 'optimize_')



