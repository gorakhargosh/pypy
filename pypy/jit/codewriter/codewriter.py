from pypy.jit.codewriter import support, heaptracker
from pypy.jit.codewriter.regalloc import perform_register_allocation
from pypy.jit.codewriter.flatten import flatten_graph, KINDS
from pypy.jit.codewriter.assembler import Assembler, JitCode
from pypy.jit.codewriter.jtransform import transform_graph
from pypy.jit.codewriter.format import format_assembler
from pypy.jit.codewriter.liveness import compute_liveness
from pypy.jit.codewriter.call import CallControl
from pypy.jit.codewriter.policy import log
from pypy.objspace.flow.model import copygraph
from pypy.tool.udir import udir


class CodeWriter(object):
    callcontrol = None    # for tests

    def __init__(self, cpu=None, maingraph=None):
        self.cpu = cpu
        self.assembler = Assembler()
        self.portal_graph = maingraph
        self.callcontrol = CallControl(cpu, maingraph)

    def transform_func_to_jitcode(self, func, values, type_system='lltype'):
        """For testing."""
        rtyper = support.annotate(func, values, type_system=type_system)
        graph = rtyper.annotator.translator.graphs[0]
        jitcode = JitCode("test")
        self.transform_graph_to_jitcode(graph, jitcode, True, True)
        return jitcode

    def transform_graph_to_jitcode(self, graph, jitcode, portal, verbose):
        """Transform a graph into a JitCode containing the same bytecode
        in a different format.
        """
        graph = copygraph(graph, shallowvars=True)
        #
        # step 1: mangle the graph so that it contains the final instructions
        # that we want in the JitCode, but still as a control flow graph
        transform_graph(graph, self.cpu, self.callcontrol, portal)
        #
        # step 2: perform register allocation on it
        regallocs = {}
        for kind in KINDS:
            regallocs[kind] = perform_register_allocation(graph, kind)
        #
        # step 3: flatten the graph to produce human-readable "assembler",
        # which means mostly producing a linear list of operations and
        # inserting jumps or conditional jumps.  This is a list of tuples
        # of the shape ("opname", arg1, ..., argN) or (Label(...),).
        ssarepr = flatten_graph(graph, regallocs)
        #
        # step 3b: compute the liveness around certain operations
        compute_liveness(ssarepr)
        #
        # step 4: "assemble" it into a JitCode, which contains a sequence
        # of bytes and lists of constants.  It's during this step that
        # constants are cast to their normalized type (Signed, GCREF or
        # Float).
        self.assembler.assemble(ssarepr, jitcode)
        #
        # print the resulting assembler
        self.print_ssa_repr(ssarepr, portal, verbose)

    def make_jitcodes(self, verbose=False):
        log.info("making JitCodes...")
        maingraph = self.portal_graph
        self.mainjitcode = self.callcontrol.get_jitcode(maingraph)
        count = 0
        for graph, jitcode in self.callcontrol.enum_pending_graphs():
            self.transform_graph_to_jitcode(graph, jitcode,
                                            graph is maingraph, verbose)
            count += 1
            if not count % 500:
                log.info("Produced %d jitcodes" % count)
        heaptracker.finish_registering(self.cpu)
        log.info("there are %d JitCode instances." % count)

    def setup_vrefinfo(self, vrefinfo):
        self.callcontrol.virtualref_info = vrefinfo

    def setup_virtualizable_info(self, vinfo):
        self.callcontrol.virtualizable_info = vinfo

    def setup_portal_runner_ptr(self, portal_runner_ptr):
        self.callcontrol.portal_runner_ptr = portal_runner_ptr

    def find_all_graphs(self, policy):
        return self.callcontrol.find_all_graphs(policy)

    def print_ssa_repr(self, ssarepr, portal, verbose):
        if verbose:
            print '%s:' % (ssarepr.name,)
            print format_assembler(ssarepr)
        else:
            dir = udir.ensure("jitcodes", dir=1)
            if portal:
                name = "00_portal_runner"
            elif ssarepr.name and ssarepr.name != '?':
                name = ssarepr.name
            else:
                name = 'unnamed' % id(ssarepr)
            i = 1
            extra = ''
            while dir.join(name+extra).check(exists=1):
                i += 1
                extra = '.%d' % i
            dir.join(name+extra).write(format_assembler(ssarepr))
            log.dot()