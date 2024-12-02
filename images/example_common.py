from pydot import Dot, Edge, Node, Subgraph

class TLIMSIC(Subgraph):
  def __init__(self, i, j):
    Subgraph.__init__(self, f"imsic{i}{j}", label=f"imsic{i}{j}\nTLIMSIC", cluster=True, style='filled', bgcolor="#F8CECC", pencolor="#B85450")
    self.fromMem = Node(f"imsic{i}{j}_fromMem", label="fromMem\nTLXbar")
    self.add_node(self.fromMem)
    self.fromCSR = Node(f"imsic{i}{j}_fromCSR", label="fromCSR\nBundle")
    self.add_node(self.fromCSR)
    self.toCSR = Node(f"imsic{i}{j}_toCSR", label="toCSR\nBundle")
    self.add_node(self.toCSR)
    self.add_edge(Edge(self.fromMem, self.fromCSR, color="transparent"))
    self.add_edge(Edge(self.fromMem, self.toCSR, color="transparent"))

class TLAPLIC(Subgraph):
  def __init__(self):
    Subgraph.__init__(self, "aplic", label="aplic\nTLAPLIC", cluster=True, style='filled', bgcolor="#F8CECC", pencolor="#B85450")
    self.fromCPU = Node("aplic_fromCPU", label="fromCPU\nTLXbar")
    self.add_node(self.fromCPU)
    self.toIMSIC = Node("aplic_toIMSIC", label="toIMSIC\nTLXbar")
    self.add_node(self.toIMSIC)
    self.intSrcs = Node("aplic_intSrcs", label="module.intSrcs\nBundle")
    self.add_node(self.intSrcs)
    self.add_edge(Edge(self.fromCPU, self.toIMSIC, color="transparent"))
    self.add_edge(Edge(self.intSrcs, self.toIMSIC, color="transparent"))
