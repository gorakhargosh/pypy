from pypy.jit.metainterp import resume
from pypy.jit.metainterp.optimizeopt import virtualize
from pypy.jit.metainterp.optimizeopt.optimizer import LEVEL_CONSTANT, \
                                                      LEVEL_KNOWNCLASS, \
                                                      MININT, MAXINT
from pypy.jit.metainterp.optimizeutil import InvalidLoop
from pypy.jit.metainterp.optimizeopt.intutils import IntBound
from pypy.jit.metainterp.resoperation import rop, ResOperation

class AbstractVirtualStateInfo(resume.AbstractVirtualInfo):
    def generalization_of(self, other):
        raise NotImplementedError

    def generate_guards(self, other, box, cpu, extra_guards):
        if self.generalization_of(other):
            return
        self._generate_guards(other, box, cpu, extra_guards)

    def _generate_guards(self, other, box, cpu, extra_guards):
        raise InvalidLoop

    def enum_forced_boxes(self, boxes, already_seen, value):
        raise NotImplementedError
    
class AbstractVirtualStructStateInfo(AbstractVirtualStateInfo):
    def __init__(self, fielddescrs):
        self.fielddescrs = fielddescrs

    def generalization_of(self, other):
        if not self._generalization_of(other):
            return False
        assert len(self.fielddescrs) == len(self.fieldstate)
        assert len(other.fielddescrs) == len(other.fieldstate)
        if len(self.fielddescrs) != len(other.fielddescrs):
            return False
        
        for i in range(len(self.fielddescrs)):
            if other.fielddescrs[i] is not self.fielddescrs[i]:
                return False
            if not self.fieldstate[i].generalization_of(other.fieldstate[i]):
                return False

        return True

    def _generalization_of(self, other):
        raise NotImplementedError

    def enum_forced_boxes(self, boxes, already_seen, value):
        assert isinstance(value, virtualize.AbstractVirtualStructValue)
        key = value.get_key_box()
        if key in already_seen:
            return
        already_seen[key] = None
        if value.box is None:
            for i in range(len(self.fielddescrs)):
                v = value._fields[self.fielddescrs[i]]
                self.fieldstate[i].enum_forced_boxes(boxes, already_seen, v)
        else:
            boxes.append(value.box)
        
class VirtualStateInfo(AbstractVirtualStructStateInfo):
    def __init__(self, known_class, fielddescrs):
        AbstractVirtualStructStateInfo.__init__(self, fielddescrs)
        self.known_class = known_class

    def _generalization_of(self, other):        
        if not isinstance(other, VirtualStateInfo):
            return False
        if not self.known_class.same_constant(other.known_class):
            return False
        return True
        
class VStructStateInfo(AbstractVirtualStructStateInfo):
    def __init__(self, typedescr, fielddescrs):
        AbstractVirtualStructStateInfo.__init__(self, fielddescrs)
        self.typedescr = typedescr

    def _generalization_of(self, other):        
        if not isinstance(other, VStructStateInfo):
            return False
        if self.typedescr is not other.typedescr:
            return False
        return True
        
class VArrayStateInfo(AbstractVirtualStateInfo):
    def __init__(self, arraydescr):
        self.arraydescr = arraydescr

    def generalization_of(self, other):
        if self.arraydescr is not other.arraydescr:
            return False
        if len(self.fieldstate) != len(other.fieldstate):
            return False
        for i in range(len(self.fieldstate)):
            if not self.fieldstate[i].generalization_of(other.fieldstate[i]):
                return False
        return True

    def enum_forced_boxes(self, boxes, already_seen, value):
        assert isinstance(value, virtualize.VArrayValue)
        key = value.get_key_box()
        if key in already_seen:
            return
        already_seen[key] = None
        if value.box is None:
            for i in range(len(self.fieldstate)):
                v = value._items[i]
                self.fieldstate[i].enum_forced_boxes(boxes, already_seen, v)
        else:
            boxes.append(value.box)

class NotVirtualStateInfo(AbstractVirtualStateInfo):
    def __init__(self, value):
        self.known_class = value.known_class
        self.level = value.level
        if value.intbound is None:
            self.intbound = IntBound(MININT, MAXINT)
        else:
            self.intbound = value.intbound.clone()
        if value.is_constant():
            self.constbox = value.box
        else:
            self.constbox = None

    def generalization_of(self, other):
        # XXX This will always retrace instead of forcing anything which
        # might be what we want sometimes?
        if not isinstance(other, NotVirtualStateInfo):
            return False
        if other.level < self.level:
            return False
        if self.level == LEVEL_CONSTANT:
            if not self.constbox.same_constant(other.constbox):
                return False
        elif self.level == LEVEL_KNOWNCLASS:
            if self.known_class != other.known_class: # FIXME: use issubclass?
                return False
        return self.intbound.contains_bound(other.intbound)

    def _generate_guards(self, other, box, cpu, extra_guards):
        if not isinstance(other, NotVirtualStateInfo):
            raise InvalidLoop
        if self.level == LEVEL_KNOWNCLASS and \
           box.nonnull() and \
           self.known_class.same_constant(cpu.ts.cls_of_box(box)):
            # Note: This is only a hint on what the class of box was
            # during the trace. There are actually no guarentees that this
            # box realy comes from a trace. The hint is used here to choose
            # between either eimtting a guard_class and jumping to an
            # excisting compiled loop or retracing the loop. Both
            # alternatives will always generate correct behaviour, but
            # performace will differ.
            op = ResOperation(rop.GUARD_CLASS, [box, self.known_class], None)
            extra_guards.append(op)
            return
        # Remaining cases are probably not interesting
        raise InvalidLoop
        if self.level == LEVEL_CONSTANT:
            import pdb; pdb.set_trace()
            raise NotImplementedError

    def enum_forced_boxes(self, boxes, already_seen, value):
        if self.level == LEVEL_CONSTANT:
            return
        key = value.get_key_box()
        if key not in already_seen:
            boxes.append(value.force_box())
            already_seen[value.get_key_box()] = None
        

class VirtualState(object):
    def __init__(self, state):
        self.state = state

    def generalization_of(self, other):
        assert len(self.state) == len(other.state)
        for i in range(len(self.state)):
            if not self.state[i].generalization_of(other.state[i]):
                return False
        return True

    def generate_guards(self, other, args, cpu, extra_guards):        
        assert len(self.state) == len(other.state) == len(args)
        for i in range(len(self.state)):
            self.state[i].generate_guards(other.state[i], args[i],
                                          cpu, extra_guards)

    def make_inputargs(self, values):
        assert len(values) == len(self.state)
        inputargs = []
        seen_inputargs = {}
        for i in range(len(values)):
            self.state[i].enum_forced_boxes(inputargs, seen_inputargs,
                                            values[i])
        return inputargs
        

class VirtualStateAdder(resume.ResumeDataVirtualAdder):
    def __init__(self, optimizer):
        self.fieldboxes = {}
        self.optimizer = optimizer
        self.info = {}

    def register_virtual_fields(self, keybox, fieldboxes):
        self.fieldboxes[keybox] = fieldboxes
        
    def already_seen_virtual(self, keybox):
        return keybox in self.fieldboxes

    def getvalue(self, box):
        return self.optimizer.getvalue(box)

    def state(self, box):
        value = self.getvalue(box)
        box = value.get_key_box()
        try:
            info = self.info[box]
        except KeyError:
            if value.is_virtual():
                self.info[box] = info = value.make_virtual_info(self, None)
                flds = self.fieldboxes[box]
                info.fieldstate = [self.state(b) for b in flds]
            else:
                self.info[box] = info = self.make_not_virtual(value)
        return info

    def get_virtual_state(self, jump_args):
        for box in jump_args:
            value = self.getvalue(box)
            value.get_args_for_fail(self)
        return VirtualState([self.state(box) for box in jump_args])


    def make_not_virtual(self, value):
        return NotVirtualStateInfo(value)

    def make_virtual(self, known_class, fielddescrs):
        return VirtualStateInfo(known_class, fielddescrs)

    def make_vstruct(self, typedescr, fielddescrs):
        return VStructStateInfo(typedescr, fielddescrs)

    def make_varray(self, arraydescr):
        return VArrayStateInfo(arraydescr)

