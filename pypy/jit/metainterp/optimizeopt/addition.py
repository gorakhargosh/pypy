from pypy.jit.metainterp.optimizeopt.optimizer import *
from pypy.jit.metainterp.resoperation import opboolinvers, opboolreflex
from pypy.jit.metainterp.history import ConstInt
from pypy.jit.metainterp.optimizeutil import _findall
from pypy.jit.metainterp.resoperation import rop, ResOperation
from pypy.jit.codewriter.effectinfo import EffectInfo
from pypy.jit.metainterp.optimizeopt.intutils import IntBound
from pypy.rlib.rarithmetic import highest_bit

class OptAddition(Optimization):
    def __init__(self):
        self.args = {}

    def reconstruct_for_next_iteration(self, optimizer, valuemap):
        return OptAddition()

    def propagate_forward(self, op):
        opnum = op.getopnum()
        for value, func in optimize_ops:
            if opnum == value:
                func(self, op)
                break
        else:
            self.emit_operation(op)

    def _int_operation(self, variable, constant, result):
        if constant < 0:
            constant = ConstInt(-constant)
            return ResOperation(rop.INT_SUB, [variable, constant], result)
        else:
            constant = ConstInt(constant)
            return ResOperation(rop.INT_ADD, [variable, constant], result)

    def _process_add(self, variable, constant, result):
        try:
            root, stored_constant = self.args[variable]
            constant = constant + stored_constant
        except KeyError:
            root = variable

        self.args[result] = root, constant

        new_op = self._int_operation(root, constant, result)
        self.emit_operation(new_op)

    def optimize_INT_ADD(self, op):
        lv = self.getvalue(op.getarg(0))
        rv = self.getvalue(op.getarg(1))
        result = op.result
        if lv.is_constant() and rv.is_constant():
            self.emit_operation(op) # XXX: there's support for optimizing this elsewhere, right?
        elif lv.is_constant():
            constant = lv.box.getint()
            self._process_add(op.getarg(1), constant, result)
        elif rv.is_constant():
            constant = rv.box.getint()
            self._process_add(op.getarg(0), constant, result)
        else:
            self.emit_operation(op)

    def optimize_INT_SUB(self, op):
        lv = self.getvalue(op.getarg(0))
        rv = self.getvalue(op.getarg(1))
        result = op.result
        if lv.is_constant() and rv.is_constant():
            self.emit_operation(op) # XXX: there's support for optimizing this elsewhere, right?
        elif lv.is_constant():
            # TODO: implement?
            self.emit_operation(op)
        elif rv.is_constant():
            constant = rv.box.getint()
            self._process_add(op.getarg(0), -constant, result)
        else:
            self.emit_operation(op)

optimize_ops = _findall(OptAddition, 'optimize_')