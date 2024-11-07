from pydot import Dot, Edge, Node, Subgraph
from example_common import TLIMSIC, TLAPLIC

graph = Dot(label="Example", splines="ortho", bgcolor="transparent")
graph.set_node_defaults(shape="box")

toAIA = Node("toAIA", label="toAIA\nAXI4MasterNode")
graph.add_node(toAIA)
toAIA_xbar = Node("toAIA_xbar", label="toAIA_xbar\nAXI4Xbar", width=5)
graph.add_node(toAIA_xbar)
graph.add_edge(Edge(toAIA, toAIA_xbar))

imsics_fromMem_xbar = Node("imsics_fromMem_xbar", label="imsics_fromMem_xbar\nAXI4Xbar", width=10)
graph.add_node(imsics_fromMem_xbar)
graph.add_edge(Edge(toAIA_xbar, imsics_fromMem_xbar))

class Convertor(Node):
  def __init__(self, *argsl, **argsd):
    Node.__init__(self, *argsl, **argsd, style='filled', fillcolor="#DAE8FC", color="#6C8EBF")

class AXI4IMSIC(Subgraph):
  def __init__(self, i, j):
    Subgraph.__init__(self, f"axi4imsic{i}{j}", label=f"imsic{i}{j}\nAXI4IMSIC", cluster=True)
    self.tlimsic = TLIMSIC(i, j)
    self.add_subgraph(self.tlimsic)

    self.fromMem = Node(f"axi4imsic{i}{j}_fromMem", label="fromMem\nAXI4IdentityNode")
    self.add_node(self.fromMem)
    self.axi4totl = Convertor(f"axi4imsic{i}{j}_axi4totl", label="AXI4ToTL")
    self.add_node(self.axi4totl)
    self.add_edge(Edge(self.fromMem, self.axi4totl))
    self.add_edge(Edge(self.axi4totl, self.tlimsic.fromMem))

    self.toCSR = Node(f"axi4imsic{i}{j}_toCSR", label="toCSR\nBundle")
    self.add_node(self.toCSR)
    self.add_edge(Edge(self.tlimsic.toCSR, self.toCSR))

    self.fromCSR = Node(f"axi4imsic{i}{j}_fromCSR", label="fromCSR\nBundle")
    self.add_node(self.fromCSR)
    self.add_edge(Edge(self.tlimsic.fromCSR, self.fromCSR, dir="back"))

imsics = [AXI4IMSIC(i,j) for i in range(2) for j in range(2)]
maps = [Node(f"map{i}{j}", label=f"[mAddr{i}{j},sgAddr{i}{j}]\nmap{j}{j}\nAXI4Map\n[0x0,0x10000]") for i in range(2) for j in range(2)]
for imsic,map in zip(imsics,maps):
  graph.add_subgraph(imsic)
  graph.add_node(map)
  graph.add_edge(Edge(imsics_fromMem_xbar, map))
  graph.add_edge(Edge(map, imsic.fromMem))

fromCSRs = [Node(f"fromCSR{i}", label=f"fromCSR{i}\nBundle") for i in range(len(imsics))]
toCSRs =   [Node(f"toCSR{i}",   label=f"toCSR{i}\nBundle")   for i in range(len(imsics))]
for fromCSR,toCSR,imsic in zip(fromCSRs, toCSRs, imsics):
  graph.add_node(toCSR)
  graph.add_edge(Edge(imsic.toCSR, toCSR))
  graph.add_node(fromCSR)
  graph.add_edge(Edge(imsic.fromCSR, fromCSR, dir="back"))

class AXI4APLIC(Subgraph):
  def __init__(self):
    Subgraph.__init__(self, "axi4aplic", label="aplic\nAXI4APLIC", cluster=True)
    self.tlaplic = TLAPLIC()
    self.add_subgraph(self.tlaplic)

    self.fromCPU = Node("axi4aplic_fromCPU", label="fromCPU\nAXI4IdentityNode")
    self.add_node(self.fromCPU)
    self.axi4totl = Convertor("axi4aplic_axi4totl", label="AXI4ToTL")
    self.add_node(self.axi4totl)
    self.add_edge(Edge(self.fromCPU, self.axi4totl))
    self.add_edge(Edge(self.axi4totl, self.tlaplic.fromCPU))

    self.toIMSIC = Node("axi4aplic_toIMSIC", label="toIMSIC\nAXI4IdentityNode")
    self.add_node(self.toIMSIC)
    self.tltoaxi4 = Convertor("axi4aplic_tltoaxi4", label="TLToAXI4")
    self.add_node(self.tltoaxi4)
    self.add_edge(Edge(self.tlaplic.toIMSIC, self.tltoaxi4))
    self.add_edge(Edge(self.tltoaxi4, self.toIMSIC))

    self.intSrcs = Node("axi4aplic_intSrcs", label="intSrcs\nBundle")
    self.add_node(self.intSrcs)
    self.add_edge(Edge(self.intSrcs, self.tlaplic.intSrcs))

aplic = AXI4APLIC()
graph.add_subgraph(aplic)
graph.add_edge(Edge(toAIA_xbar, aplic.fromCPU))
graph.add_edge(Edge(aplic.toIMSIC, imsics_fromMem_xbar))

intSrcs = Node("intSrcs", label="intSrcs\nBundle")
graph.add_node(intSrcs)
graph.add_edge(Edge(intSrcs, aplic.intSrcs))

input = Node("input", label="", color="transparent", width=5, height=0)
graph.add_node(input)
graph.add_edge(Edge(input, intSrcs))
graph.add_edge(Edge(input, toAIA))

output = Node("output", label="", color="transparent", width=11, height=0)
graph.add_node(output)
for fromCSR,toCSR in zip(fromCSRs,toCSRs):
  graph.add_edge(Edge(toCSR, output))
  graph.add_edge(Edge(fromCSR, output, dir="back"))

graph.write(__file__.replace("_dot.py", "_py.dot"))
