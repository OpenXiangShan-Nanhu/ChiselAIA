from pydot import Dot, Edge, Node, Subgraph
from example_common import TLIMSIC, TLAPLIC

graph = Dot(label="Example", splines="ortho", bgcolor="transparent")
graph.set_node_defaults(shape="box")

toAIA = Node("toAIA", label="toAIA\nTLClientNode")
graph.add_node(toAIA)
toAIA_xbar = Node("toAIA_xbar", label="toAIA_xbar\nTLXbar", width=5)
graph.add_node(toAIA_xbar)
graph.add_edge(Edge(toAIA, toAIA_xbar))

imsics_fromMem_xbar = Node("imsics_fromMem_xbar", label="imsics_fromMem_xbar\nTLXbar", width=10)
graph.add_node(imsics_fromMem_xbar)
graph.add_edge(Edge(toAIA_xbar, imsics_fromMem_xbar))

imsics = [TLIMSIC(i,j) for i in range(2) for j in range(2)]
maps = [Node(f"map{i}{j}", label=f"[mAddr{i}{j},sgAddr{i}{j}]\nmap{j}{j}\nTLMap\n[0x0,0x10000]") for i in range(2) for j in range(2)]
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

aplic = TLAPLIC()
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

output = Node("output", label="", color="transparent", width=10, height=0)
graph.add_node(output)
for fromCSR,toCSR in zip(fromCSRs,toCSRs):
  graph.add_edge(Edge(toCSR, output))
  graph.add_edge(Edge(fromCSR, output, dir="back"))

graph.write(__file__.replace("_dot.py", "_py.dot"))
