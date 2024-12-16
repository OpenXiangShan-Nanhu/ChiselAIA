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

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
from common import *

# Main test
@cocotb.test()
async def imsic_1_test(dut):
  """Main test converted from main.lua."""
  # Start the clock
  cocotb.start_soon(Clock(dut.clock, 1, units="ns").start())

  # Apply reset
  dut.reset.value = 1
  for _ in range(10):
    await RisingEdge(dut.clock)
  dut.reset.value = 0

  # Initialize ready signals
  dut.toaia_0_d_ready.value = 1

  await FallingEdge(dut.clock)

  # Initialize IMSIC
  await init_imsic(dut)

  # Test steps
  await select_m_intfile(dut)
  dut.toCSR1_pendings_0.value = 0

  # mseteipnum began
  cocotb.log.info("mseteipnum began")
  await m_int(dut, 1996%256)
  topeis_0 = wrap_topei(1996%256)
  await FallingEdge(dut.clock) ## delay one cycle caused by RegGen.
  await delay_fifo(dut)
  assert dut.toCSR1_topeis_0.value == topeis_0
  dut.toCSR1_pendings_0.value = 1
  cocotb.log.info("mseteipnum passed")

  # mclaim began
  cocotb.log.info("mclaim began")
  await claim(dut)
  assert dut.toCSR1_topeis_0.value == wrap_topei(0)
  cocotb.log.info("mclaim passed")

  # 2_mseteipnum_1_bits_mclaim began
  cocotb.log.info("2_mseteipnum_1_bits_mclaim began")
  await m_int(dut, 12)
  await FallingEdge(dut.clock) ## delay one cycle caused by RegGen.
  await delay_fifo(dut)
  assert dut.toCSR1_topeis_0.value == wrap_topei(12)
  await m_int(dut, 8)
  await FallingEdge(dut.clock) ## delay one cycle caused by RegGen.
  await delay_fifo(dut)
  assert dut.toCSR1_topeis_0.value == wrap_topei(8)
  await claim(dut)
  assert dut.toCSR1_topeis_0.value == wrap_topei(12)
  cocotb.log.info("2_mseteipnum_1_bits_mclaim passed")

  # write_csr:op began
  cocotb.log.info("write_csr:op began")
  await write_csr_op(dut, csr_addr_eidelivery, 0xc0, op_csrrs)
  # cocotb not support vpiScope
  # https://github.com/cocotb/cocotb/issues/3663
  # https://github.com/cocotb/cocotb/issues/1884
  # https://github.com/cocotb/cocotb/issues/1432
  # Note: easy replacement from `vpiScope` into `vpiGenScope`, `vpiGenScopeArray` also not work
  # assert dut.imsic_1.imsic.intFile.eidelivery.value == 0xc1
  assert dut.toCSR1_illegal == 0
  await write_csr_op(dut, csr_addr_eidelivery, 0xc0, op_csrrc)
  # assert dut.imsic_1.imsic.intFile.eidelivery.value == 0x1
  cocotb.log.info("write_csr:op passed")

  # write_csr:eidelivery began
  cocotb.log.info("write_csr:eidelivery began")
  await write_csr(dut, csr_addr_eidelivery, 0)
  dut.toCSR1_pendings_0.value = 0
  await write_csr(dut, csr_addr_eidelivery, 1)
  cocotb.log.info("write_csr:eidelivery passed")

  # write_csr:meithreshold began
  cocotb.log.info("write_csr:meithreshold began")
  mtopei = dut.toCSR1_topeis_0.value
  await write_csr(dut, csr_addr_eithreshold, mtopei & 0x7ff)
  assert dut.toCSR1_topeis_0.value != wrap_topei(mtopei)
  await write_csr(dut, csr_addr_eithreshold, mtopei + 1)
  assert dut.toCSR1_topeis_0.value == mtopei
  await write_csr(dut, csr_addr_eithreshold, 0)
  cocotb.log.info("write_csr:meithreshold end")

  # write_csr:eip began
  cocotb.log.info("write_csr:eip began")
  await write_csr(dut, csr_addr_eip0, 0xc)
  assert dut.toCSR1_topeis_0.value == wrap_topei(2)
  cocotb.log.info("write_csr:eip end")

  # write_csr:eie began
  cocotb.log.info("write_csr:eie began")
  mtopei = dut.toCSR1_topeis_0.value
  mask = 1 << (mtopei & 0x7ff)
  await write_csr_op(dut, csr_addr_eie0, mask, op_csrrc)
  assert dut.toCSR1_topeis_0.value != mtopei
  await write_csr_op(dut, csr_addr_eie0, mask, op_csrrs)
  assert dut.toCSR1_topeis_0.value == mtopei
  cocotb.log.info("write_csr:eie passed")

  # read_csr:eie began
  cocotb.log.info("read_csr:eie began")
  await read_csr(dut, csr_addr_eie0)
  await FallingEdge(dut.clock)
  # toCSR1_rdata_bits = dut.toCSR1_rdata_bits.value
  # eies_0 = dut.imsic_1.imsic.intFile.eies_0.value
  # assert toCSR1_rdata_bits == eies_0
  cocotb.log.info("read_csr:eie passed")

  # Simple supervisor level test
  cocotb.log.info("simple_supervisor_level began")
  await select_s_intfile(dut)
  assert dut.toCSR1_topeis_1.value == wrap_topei(0)
  await s_int(dut, 1234%256)
  await FallingEdge(dut.clock) ## delay one cycle caused by RegGen.
  await delay_fifo(dut)
  assert dut.toCSR1_topeis_1.value == wrap_topei(1234%256)
  dut.toCSR1_pendings_1.value = 1
  await select_m_intfile(dut)
  cocotb.log.info("simple_supervisor_level end")

  # Virtualized supervisor level test (vgein=2)
  cocotb.log.info("simple_virtualized_supervisor_level:vgein2 began")
  await select_vs_intfile(dut, 2)
  assert dut.toCSR1_topeis_2.value == wrap_topei(0)
  await v_int_vgein(dut, 137)
  await FallingEdge(dut.clock)
  await delay_fifo(dut)
  assert dut.toCSR1_topeis_2.value == wrap_topei(137)
  dut.toCSR1_pendings_4.value = 1  # Assuming pendings_4 corresponds to vgein=2
  await select_m_intfile(dut)
  assert dut.toCSR1_topeis_2.value == wrap_topei(137)
  dut.toCSR1_pendings_4.value = 1
  cocotb.log.info("simple_virtualized_supervisor_level:vgein2 end")

  # Illegal iselect test
  cocotb.log.info("illegal:iselect began")
  await write_csr_op(dut, 0x71, 0xc0, op_csrrs)
  assert dut.toCSR1_illegal.value == 1
  cocotb.log.info("illegal:iselect passed")

  # Illegal vgein test
  cocotb.log.info("illegal:vgein began")
  await FallingEdge(dut.clock)
  await FallingEdge(dut.clock)
  dut.toCSR1_illegal.value = 0
  await select_vs_intfile(dut, 4)
  await write_csr(dut, csr_addr_eidelivery, 1)
  assert dut.toCSR1_illegal.value == 1
  await select_m_intfile(dut)
  cocotb.log.info("illegal:vgein end")

  # Illegal wdata_op test
  cocotb.log.info("illegal:iselect:wdata_op began")
  await FallingEdge(dut.clock)
  await FallingEdge(dut.clock)
  dut.toCSR1_illegal.value = 0
  await write_csr_op(dut, csr_addr_eidelivery, 0xc0, op_illegal)
  assert dut.toCSR1_illegal.value == 1
  cocotb.log.info("illegal:iselect:wdata_op passed")

  # Illegal privilege test
  cocotb.log.info("illegal:priv began")
  await FallingEdge(dut.clock)
  await FallingEdge(dut.clock)
  dut.toCSR1_illegal.value = 0
  dut.fromCSR1_priv.value = 3
  dut.fromCSR1_virt.value = 1
  await write_csr(dut, csr_addr_eidelivery, 0xfa)
  assert dut.toCSR1_illegal.value == 1
  await select_m_intfile(dut)
  cocotb.log.info("illegal:priv passed")

  # eip0[0] read-only test
  cocotb.log.info("eip0[0]_readonly_0:write_csr began")
  await write_csr(dut, csr_addr_eip0, 0x1)
  await read_csr(dut, csr_addr_eip0)
  for _ in range(10):
    await FallingEdge(dut.clock)
    if dut.toCSR1_rdata_valid.value == 1:
      break
  else:
    assert False, "Timeout waiting for rdata_valid == 1"
  assert dut.toCSR1_rdata_bits.value == 0
  cocotb.log.info("eip0[0]_readonly_0:write_csr passed")

  cocotb.log.info("eip0[0]_readonly_0:seteipnum began")
  await m_int(dut, 0)
  await read_csr(dut, csr_addr_eip0)
  for _ in range(10):
    await FallingEdge(dut.clock)
    if dut.toCSR1_rdata_valid.value == 1:
      break
  else:
    assert False, "Timeout waiting for rdata_valid == 1"
  assert dut.toCSR1_rdata_bits.value == 0
  cocotb.log.info("eip0[0]_readonly_0:seteipnum passed")

  cocotb.log.info("Cocotb tests passed!")
