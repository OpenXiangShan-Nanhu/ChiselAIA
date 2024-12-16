########################################################################################
# Copyright (c) 2024 Beijing Institute of Open Source Chip (BOSC)
#
# ChiselAIA is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.
########################################################################################

from cocotb.triggers import RisingEdge, FallingEdge

## delay about async fifo for imsic,EnableImsicAsyncBridge indicate the delay caused by imsic is async
EnableImsicAsyncBridge = 0
async def delay_fifo(dut):
    if EnableImsicAsyncBridge ==1 :
        for _ in range(5):
            await FallingEdge(dut.clock) ## delay caused by async fifo: source and sink, when EnableImsicAsyncBridge is true
    else:
        """EnableImsicAsyncbridge is 0."""
  
## delay about async fifo for imsic

op_put_full = 0
op_get = 4
op_access_ack = 0
op_access_ack_data = 1
async def a_op(dut, addr, data, op, mask, size) -> None:
  await FallingEdge(dut.clock)
  while not dut.toaia_0_a_ready:
    await FallingEdge(dut.clock)
  dut.toaia_0_a_valid.value = 1
  dut.toaia_0_a_bits_opcode.value = op
  dut.toaia_0_a_bits_address.value = addr
  dut.toaia_0_a_bits_mask.value = mask
  dut.toaia_0_a_bits_size.value = size
  dut.toaia_0_a_bits_data.value = data
  await FallingEdge(dut.clock)
  dut.toaia_0_a_valid.value = 0
async def a_op32(dut, addr, data, op) -> None:
  await a_op(
    dut, addr,
    data if addr%8==0 else data<<32,
    op,
    0x0f if addr%8==0 else 0xf0,
    2,
  )
async def a_put_full32(dut, addr, data) -> None:
  await a_op32(dut, addr, data, op_put_full)
  for _ in range(10):
    await RisingEdge(dut.clock)
    if dut.toaia_0_d_bits_opcode == op_access_ack and dut.toaia_0_d_valid == 1:
      break
  else:
    assert False, f"Timeout waiting for op_access_ack"
async def a_get32(dut, addr) -> int:
  await a_op32(dut, addr, 0, op_get)
  for _ in range(10):
    await RisingEdge(dut.clock)
    if dut.toaia_0_d_bits_opcode == op_access_ack_data and dut.toaia_0_d_valid == 1:
      break
  else:
    assert False, f"Timeout waiting for op_access_ack_data"
  odata = int(dut.toaia_0_d_bits_data)
  res = odata if addr%8==0 else odata>>32
  return res & 0xffffffff

async def interrupt(dut, i):
  intSrcs_x = getattr(dut, f"intSrcs_{i}")
  await FallingEdge(dut.clock)
  intSrcs_x.value = 0
  await FallingEdge(dut.clock)
  intSrcs_x.value = 1
  if EnableImsicAsyncBridge ==1 :
    for _ in range(15):
      await FallingEdge(dut.clock)
      if dut.toCSR0_topeis_0 == wrap_topei(i):
        break
    else:
      assert False, f"Timeout waiting for toCSR0_topeis_0 == wrap_topei({i})"
  else :
    for _ in range(10):
      await FallingEdge(dut.clock)
      if dut.toCSR0_topeis_0 == wrap_topei(i):
        break
    else:
      assert False, f"Timeout waiting for toCSR0_topeis_0 == wrap_topei({i})"

################################################################################
# IMSIC
################################################################################
imsic_m_base_addr   = 0x61000000
imsic_sg_base_addr  = 0x82900000
csr_addr_eidelivery = 0x70
csr_addr_eithreshold = 0x72
csr_addr_eip0 = 0x80
csr_addr_eip2 = 0x82
csr_addr_eie0 = 0xC0
# CSR operation codes
op_illegal = 0
op_csrrw = 1
op_csrrs = 2
op_csrrc = 3

async def m_int(dut, intnum, imsicID=1):
  """Issue an interrupt to the M-mode interrupt file."""
  await a_put_full32(dut, imsic_m_base_addr+0x1000*imsicID, intnum)
  await RisingEdge(dut.clock)

async def s_int(dut, intnum, imsicID=1):
  """Issue an interrupt to the S-mode interrupt file."""
  await a_put_full32(dut, imsic_sg_base_addr+0x8000*imsicID, intnum)
  await RisingEdge(dut.clock)

async def v_int_vgein(dut, intnum, imsicID=1, guestID=2):
  """Issue an interrupt to the VS-mode interrupt file with vgein2."""
  await a_put_full32(dut, imsic_sg_base_addr+0x8000*imsicID + 0x1000*(1+guestID), intnum)
  await RisingEdge(dut.clock)

async def claim(dut, imsicID=1):
  """Claim the highest pending interrupt."""
  fromCSRx_claims_0 = getattr(dut, f"fromCSR{imsicID}_claims_0")
  await FallingEdge(dut.clock)
  fromCSRx_claims_0.value = 1
  await FallingEdge(dut.clock)
  fromCSRx_claims_0.value = 0

def wrap_topei(in_):
  extract = in_ & 0x7ff
  out = extract | (extract << 16)
  return out

async def write_csr_op(dut, miselect, data, op, imsicID=1):
  fromCSRx_addr_valid      = getattr(dut, f"fromCSR{imsicID}_addr_valid"     )
  fromCSRx_addr_bits       = getattr(dut, f"fromCSR{imsicID}_addr_bits"      )
  fromCSRx_wdata_valid     = getattr(dut, f"fromCSR{imsicID}_wdata_valid"    )
  fromCSRx_wdata_bits_op   = getattr(dut, f"fromCSR{imsicID}_wdata_bits_op"  )
  fromCSRx_wdata_bits_data = getattr(dut, f"fromCSR{imsicID}_wdata_bits_data")
  await FallingEdge(dut.clock)
  fromCSRx_addr_valid.value = 1
  fromCSRx_addr_bits.value = miselect
  fromCSRx_wdata_valid.value = 1
  fromCSRx_wdata_bits_op.value = op
  fromCSRx_wdata_bits_data.value = data
  await FallingEdge(dut.clock)
  fromCSRx_addr_valid.value = 0
  fromCSRx_wdata_valid.value = 0

async def write_csr(dut, miselect, data, imsicID=1):
  await write_csr_op(dut, miselect, data, op_csrrw, imsicID)

async def read_csr(dut, miselect, imsicID=1):
  fromCSRx_addr_valid = getattr(dut, f"fromCSR{imsicID}_addr_valid")
  fromCSRx_addr_bits  = getattr(dut, f"fromCSR{imsicID}_addr_bits" )
  await FallingEdge(dut.clock)
  fromCSRx_addr_valid.value = 1
  fromCSRx_addr_bits.value = miselect
  await FallingEdge(dut.clock)
  fromCSRx_addr_valid.value = 0

async def select_m_intfile(dut, imsicID=1):
  fromCSRx_priv = getattr(dut, f"fromCSR{imsicID}_priv")
  fromCSRx_virt = getattr(dut, f"fromCSR{imsicID}_virt")
  await FallingEdge(dut.clock)
  fromCSRx_priv.value = 3
  fromCSRx_virt.value = 0

async def select_s_intfile(dut, imsicID=1):
  fromCSRx_priv = getattr(dut, f"fromCSR{imsicID}_priv")
  fromCSRx_virt = getattr(dut, f"fromCSR{imsicID}_virt")
  await FallingEdge(dut.clock)
  fromCSRx_priv.value = 1
  fromCSRx_virt.value = 0

async def select_vs_intfile(dut, vgein, imsicID=1):
  fromCSRx_priv = getattr(dut, f"fromCSR{imsicID}_priv")
  fromCSRx_vgein = getattr(dut, f"fromCSR{imsicID}_vgein")
  fromCSRx_virt = getattr(dut, f"fromCSR{imsicID}_virt")
  await FallingEdge(dut.clock)
  fromCSRx_priv.value = 1
  fromCSRx_vgein.value = vgein
  fromCSRx_virt.value = 1

async def init_imsic(dut, imsicID=1):
  await select_m_intfile(dut, imsicID)
  await write_csr(dut, csr_addr_eidelivery, 1, imsicID)
  for e in range(0,32):
    await write_csr(dut, csr_addr_eie0 + 2*e, -1, imsicID)
  await select_s_intfile(dut, imsicID)
  await write_csr(dut, csr_addr_eidelivery, 1, imsicID)
  for e in range(0,32):
    await write_csr(dut, csr_addr_eie0 + 2*e, -1, imsicID)
  for i in range(0,4):
    await select_vs_intfile(dut, i, imsicID)
    await write_csr(dut, csr_addr_eidelivery, 1, imsicID)
    for e in range(0,32):
      await write_csr(dut, csr_addr_eie0 + 2*e, -1, imsicID)


################################################################################
# APLIC
################################################################################
aplic_m_base_addr   = 0x19960000
aplic_sg_base_addr  = aplic_m_base_addr + 0x4000
offset_domaincfg    = 0
offset_sourcecfg    = 0x0004
offset_readonly0    = 0x1000
offset_mmsiaddrcfg  = 0x1BC0
offset_mmsiaddrcfgh = 0x1BC4
offset_smsiaddrcfg  = 0x1BC8
offset_smsiaddrcfgh = 0x1BCC
offset_setips       = 0x1C00
offset_setipnum     = 0x1CDC
offset_in_clrips    = 0x1D00
offset_clripnum     = 0x1DDC
offset_seties       = 0x1E00
offset_setienum     = 0x1EDC
offset_clries       = 0x1F00
offset_clrienum     = 0x1FDC
offset_setipnum_le  = 0x2000
offset_setipnum_be  = 0x2004
offset_genmsi       = 0x3000
offset_targets      = 0x3004
sourcecfg_sm_inactive = 0
sourcecfg_sm_detached = 1
sourcecfg_sm_edge1    = 4
sourcecfg_sm_edge0    = 5
sourcecfg_sm_level1   = 6
sourcecfg_sm_level0   = 7
