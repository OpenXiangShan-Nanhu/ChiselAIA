//MC{hide}
/***************************************************************************************
* Copyright (c) 2024 Beijing Institute of Open Source Chip (BOSC)
*
* ChiselAIA is licensed under Mulan PSL v2.
* You can use this software according to the terms and conditions of the Mulan PSL v2.
* You may obtain a copy of Mulan PSL v2 at:
*          http://license.coscl.org.cn/MulanPSL2
*
* THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
* EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
* MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
*
* See the Mulan PSL v2 for more details.
***************************************************************************************/

package aia

import chisel3.{IO, _} 
import chisel3.util._
import freechips.rocketchip.diplomacy._
import org.chipsalliance.cde.config.Parameters
import freechips.rocketchip.tilelink._
import freechips.rocketchip.amba.axi4._
import freechips.rocketchip.devices.tilelink._
import freechips.rocketchip.regmapper._
import freechips.rocketchip.prci.{ClockSinkDomain}
import freechips.rocketchip.util._
import xs.utils._

// RegMap that supports Default and Valid
object RegMapDV {
  def Unwritable = null
  def apply(addr: Int, reg: UInt, wfn: UInt => UInt = (x => x)) = (addr, (reg, wfn))
  def generate(default: UInt, mapping: Map[Int, (UInt, UInt => UInt)], raddr: UInt, rdata: UInt, rvalid: Bool,
    waddr: UInt, wen: Bool, wdata: UInt, wmask: UInt):Unit = {
    val chiselMapping = mapping.map { case (a, (r, w)) => (a.U, r, w) }
    val rdata_valid = WireDefault(0.U((rdata.getWidth+1).W))
    rdata_valid := LookupTreeDefault(raddr, Cat(default,false.B), chiselMapping.map { case (a, r, w) => (a, Cat(r,true.B)) })
    rdata := rdata_valid(rdata.getWidth, 1)
    rvalid := rdata_valid(0)
    chiselMapping.map { case (a, r, w) =>
      if (w != null) when (wen && waddr === a) { r := w(MaskData(r, wdata, wmask)) }
    }
  }
  def generate(default: UInt, mapping: Map[Int, (UInt, UInt => UInt)], addr: UInt, rdata: UInt, rvalid: Bool,
    wen: Bool, wdata: UInt, wmask: UInt):Unit = generate(default, mapping, addr, rdata, rvalid, addr, wen, wdata, wmask)
}

// Based on Xiangshan NewCSR
object OpType extends ChiselEnum {
  val ILLEGAL = Value(0.U)
  val CSRRW   = Value(1.U)
  val CSRRS   = Value(2.U)
  val CSRRC   = Value(3.U)
}
object PrivType extends ChiselEnum {
  val U = Value(0.U)
  val S = Value(1.U)
  val M = Value(3.U)
}
class CSRToIMSICBundle(params: IMSICParams) extends Bundle {
  val addr = ValidIO(UInt(params.iselectWidth.W))
  val virt = Bool()
  val priv = PrivType()
  val vgein = UInt(params.vgeinWidth.W)
  val wdata = ValidIO(new Bundle {
    val op = OpType()
    val data = UInt(params.xlen.W)
  })
  val claims = Vec(params.privNum, Bool())
}
class IMSICToCSRBundle(params: IMSICParams) extends Bundle {
  val rdata = ValidIO(UInt(params.xlen.W))
  val illegal = Bool()
  val pendings = Vec(params.intFilesNum, Bool())
  val topeis  = Vec(params.privNum, UInt(32.W))
}

case class IMSICParams(
  //MC IMSIC中断源数量的对数，默认值8表示IMSIC支持最多256（2^8）个中断源
  //MC （Logarithm of number of interrupt sources to IMSIC.
  //MC The default 8 means IMSIC support at most 256 (2^8) interrupt sources）:
  //MC{visible}
  imsicIntSrcWidth     : Int  = 8          ,
  //MC 👉 本IMSIC的机器态中断文件的地址（Address of machine-level interrupt files for this IMSIC）：
  mAddr           : Long = 0x00000L ,
  //MC 👉 本IMSIC的监管态和客户态中断文件的地址（Addr for supervisor-level and guest-level interrupt files for this IMSIC）:
  sgAddr          : Long = 0x10000L ,
  //MC 👉 客户中断文件的数量（Number of guest interrupt files）:
  geilen          : Int  = 4           ,
  //MC vgein信号的位宽（The width of the vgein signal）:
  vgeinWidth      : Int  = 6           ,
  //MC iselect信号的位宽(The width of iselect signal):
  iselectWidth    : Int  = 12          ,
  EnableImsicAsyncBridge: Boolean = false,
  //MC{hide}
) {
  lazy val xlen        : Int  = 64 // currently only support xlen = 64
  lazy val xlenWidth = log2Ceil(xlen)
  require(imsicIntSrcWidth <= 11, f"imsicIntSrcWidth=${imsicIntSrcWidth}, must not greater than log2(2048)=11, as there are at most 2048 eip/eie bits")
  lazy val privNum     : Int  = 3            // number of privilege modes: machine, supervisor, virtualized supervisor
  lazy val intFilesNum : Int  = 2 + geilen   // number of interrupt files, m, s, vs0, vs1, ...
  lazy val eixNum      : Int  = pow2(imsicIntSrcWidth).toInt / xlen // number of eip/eie registers
  lazy val intFileMemWidth : Int  = 12        // interrupt file memory region width: 12-bit width => 4KB size
  require(vgeinWidth >= log2Ceil(geilen))
  require(iselectWidth >=8, f"iselectWidth=${iselectWidth} needs to be able to cover addr [0x70, 0xFF], that is from CSR eidelivery to CSR eie63")
}

class IMSIC(
  params: IMSICParams,
  beatBytes: Int = 8,
)(implicit p: Parameters) extends Module {
  println(f"IMSICParams.geilen:            ${params.geilen          }%d")

  class IntFile extends Module {
    override def desiredName = "IntFile"
    val fromCSR = IO(Input(new Bundle {
      val seteipnum = ValidIO(UInt(params.imsicIntSrcWidth.W))
      val addr = ValidIO(UInt(params.iselectWidth.W))
      val wdata = ValidIO(new Bundle {
        val op = OpType()
        val data = UInt(params.xlen.W)
      })
      val claim = Bool()
    }))
    val toCSR = IO(Output(new Bundle {
      val rdata = ValidIO(UInt(params.xlen.W))
      val illegal = Bool()
      val pending = Bool()
      val topei  = UInt(params.imsicIntSrcWidth.W)
    }))

    /// indirect CSRs
    val eidelivery = RegInit(0.U(params.xlen.W))
    val eithreshold = RegInit(0.U(params.xlen.W))
    val eips = RegInit(VecInit.fill(params.eixNum){0.U(params.xlen.W)})
    val eies = RegInit(VecInit.fill(params.eixNum){0.U(params.xlen.W)})

    val illegal_wdata_op = WireDefault(false.B)
    locally { // scope for xiselect CSR reg map
      val wdata = WireDefault(0.U(params.xlen.W))
      val wmask = WireDefault(0.U(params.xlen.W))
      when(fromCSR.wdata.valid) {
        switch(fromCSR.wdata.bits.op) {
          is(OpType.ILLEGAL) {
            illegal_wdata_op := true.B
          }
          is(OpType.CSRRW) {
            wdata := fromCSR.wdata.bits.data
            wmask := Fill(params.xlen, 1.U)
          }
          is(OpType.CSRRS) {
            wdata := Fill(params.xlen, 1.U)
            wmask := fromCSR.wdata.bits.data
          }
          is(OpType.CSRRC) {
            wdata := 0.U
            wmask := fromCSR.wdata.bits.data
          }
        }
      }
      def bit0ReadOnlyZero(x: UInt): UInt = { x & ~1.U(x.getWidth.W) }
      RegMapDV.generate(
        0.U,
        Map(
          RegMapDV(0x70, eidelivery),
          RegMapDV(0x72, eithreshold),
          RegMapDV(0x80, eips(0), bit0ReadOnlyZero),
          RegMapDV(0xC0, eies(0), bit0ReadOnlyZero),
        ) ++ eips.drop(1).zipWithIndex.map { case (eip: UInt, i: Int) =>
          RegMapDV(0x82+i*2, eip)
        } ++ eies.drop(1).zipWithIndex.map { case (eie: UInt, i: Int) =>
          RegMapDV(0xC2+i*2, eie)
        },
        /*raddr*/ fromCSR.addr.bits,
        /*rdata*/ toCSR.rdata.bits,
        /*rdata*/ toCSR.rdata.valid,
        /*waddr*/ fromCSR.addr.bits,
        /*wen  */ fromCSR.wdata.valid,
        /*wdata*/ wdata,
        /*wmask*/ wmask,
      )
      toCSR.illegal := RegNext(fromCSR.addr.valid) & Seq(
        ~toCSR.rdata.valid,
        illegal_wdata_op,
      ).reduce(_|_)
    } // end of scope for xiselect CSR reg map

    locally {
      val index  = fromCSR.seteipnum.bits(params.imsicIntSrcWidth-1, params.xlenWidth)
      val offset = fromCSR.seteipnum.bits(params.xlenWidth-1, 0)
      when ( fromCSR.seteipnum.valid & eies(index)(offset) ) {
        // set eips bit
        eips(index) := eips(index) | UIntToOH(offset)
      }
    }

    locally { // scope for xtopei
      // The ":+ true.B" trick explain:
      //  Append true.B to handle the cornor case, where all bits in eip and eie are disabled.
      //  If do not append true.B, then we need to check whether the eip & eie are empty,
      //  otherwise, the returned topei will become the max index, that is 2^intSrcWidth-1
      // Noted: the support max interrupt sources number = 2^intSrcWidth
      //              [0,     2^intSrcWidth-1] :+ 2^intSrcWidth
      val eipBools = Cat(eips.reverse).asBools :+ true.B
      val eieBools = Cat(eies.reverse).asBools :+ true.B
      def xtopei_filter(xeidelivery: UInt, xeithreshold: UInt, xtopei: UInt): UInt = {
        val tmp_xtopei = Mux(xeidelivery(0), xtopei, 0.U)
        // {
        //   all interrupts are enabled, when eithreshold == 0;
        //   interrupts, when i < eithreshold, are enabled;
        // } <=> interrupts, when i <= (eithreshold -1), are enabled
        Mux(tmp_xtopei <= (xeithreshold-1.U), tmp_xtopei, 0.U)
      }
      toCSR.topei := xtopei_filter(
        eidelivery,
        eithreshold,
        ParallelPriorityMux(
          (eipBools zip eieBools).zipWithIndex.map {
            case ((p: Bool, e: Bool), i: Int) => (p & e, i.U)
          }
        )
      )
    } // end of scope for xtopei
    toCSR.pending := toCSR.topei =/= 0.U

    when(fromCSR.claim) {
      val index  = toCSR.topei(params.imsicIntSrcWidth-1, params.xlenWidth)
      val offset = toCSR.topei(params.xlenWidth-1, 0)
      // clear the pending bit indexed by xtopei in xeip
      eips(index) := eips(index) & ~UIntToOH(offset)
    }
  }

    val toCSR = IO(Output(new IMSICToCSRBundle(params)))
    val fromCSR = IO(Input(new CSRToIMSICBundle(params)))
    val io = IO(Input(new Bundle {
    val seteipnum = UInt(params.imsicIntSrcWidth.W)
    val valid = Vec(params.intFilesNum,Bool())
    }))
    private val illegal_priv = WireDefault(false.B)
    private val intFilesSelOH = WireDefault(0.U(params.intFilesNum.W))
    locally {
      val pv = Cat(fromCSR.priv.asUInt, fromCSR.virt)
      when      (pv === Cat(PrivType.M.asUInt, false.B)) { intFilesSelOH := UIntToOH(0.U) }
      .elsewhen (pv === Cat(PrivType.S.asUInt, false.B)) { intFilesSelOH := UIntToOH(1.U) }
      .elsewhen (pv === Cat(PrivType.S.asUInt,  true.B)) { intFilesSelOH := UIntToOH(2.U + fromCSR.vgein) }
      .otherwise { illegal_priv := true.B }
    }
    private val topeis_forEachIntFiles = Wire(Vec(params.intFilesNum, UInt(params.imsicIntSrcWidth.W)))
    private val illegals_forEachIntFiles = Wire(Vec(params.intFilesNum, Bool()))

    (Seq(1, 1+params.geilen)).zipWithIndex.map {
      case (intFilesNum: Int, i: Int)
    => {
      // j: index for S intFile: S, G1, G2, ...
      val maps = (0 until intFilesNum).map { j => {
        val flati = i + j
        val pi = if(flati>2) 2 else flati // index for privileges: M, S, VS.

        def sel[T<:Data](old: Valid[T]): Valid[T] = {
          val new_ = Wire(Valid(chiselTypeOf(old.bits)))
          new_.bits := old.bits
          new_.valid := old.valid & intFilesSelOH(flati)
          new_
        }
        val intFile = Module(new IntFile)
        intFile.fromCSR.seteipnum.bits  := io.seteipnum
        intFile.fromCSR.seteipnum.valid := io.valid(flati)
        intFile.fromCSR.addr            := sel(fromCSR.addr)
        intFile.fromCSR.wdata           := sel(fromCSR.wdata)
        intFile.fromCSR.claim           := fromCSR.claims(pi) & intFilesSelOH(flati)
        toCSR.rdata                     := intFile.toCSR.rdata
        toCSR.pendings(flati)           := intFile.toCSR.pending
        topeis_forEachIntFiles(flati)   := intFile.toCSR.topei
        illegals_forEachIntFiles(flati) := intFile.toCSR.illegal
      }}
    }}

    locally {
      // Format of *topei:
      // * bits 26:16 Interrupt identity
      // * bits 10:0 Interrupt priority (same as identity)
      // * All other bit positions are zeros.
      // For detailed explainations of these memory region arguments,
      // please refer to the manual *The RISC-V Advanced Interrupt Architeture*: 3.9. Top external interrupt CSRs
      def wrap(topei: UInt): UInt = {
        val zeros = 0.U((16-params.imsicIntSrcWidth).W)
        Cat(zeros, topei, zeros, topei)
      }
      toCSR.topeis(0) := wrap(topeis_forEachIntFiles(0)) // m
      toCSR.topeis(1) := wrap(topeis_forEachIntFiles(1)) // s
      toCSR.topeis(2) := wrap(ParallelMux(
        UIntToOH(fromCSR.vgein, params.geilen).asBools,
        topeis_forEachIntFiles.drop(2)
      )) // vs
    }
    toCSR.illegal := RegNext(fromCSR.addr.valid) & Seq(
      illegals_forEachIntFiles.reduce(_|_),
      fromCSR.vgein >= params.geilen.asUInt,
      illegal_priv,
    ).reduce(_|_)
}

class TLRegIMSIC(
  params: IMSICParams,
  beatBytes: Int = 8,
)(implicit p: Parameters) extends LazyModule {
    val fromMem = TLXbar()
  //val fromMem = LazyModule(new TLXbar).node
    private val intfileFromMems = Seq(
    AddressSet(params.mAddr,  pow2(params.intFileMemWidth) - 1),
    AddressSet(params.sgAddr, pow2(params.intFileMemWidth) * pow2(log2Ceil(1+params.geilen)) - 1),
  ).map ( addrset => {
    val intfileFromMem = TLRegMapperNode (
      address = Seq(addrset),
      beatBytes = beatBytes)
    intfileFromMem := fromMem; intfileFromMem
  })

  lazy val module = new TLRegIMSICImp(this)
  class TLRegIMSICImp(outer: LazyModule) extends LazyModuleImp(outer) {
    val io = IO(Output(new Bundle {
      val seteipnum = UInt(params.imsicIntSrcWidth.W)
      val valid = Vec(params.intFilesNum,Bool())
    }))
    private val reggen = Module(new RegGen(params, beatBytes))
    io.seteipnum := reggen.io.seteipnum
    io.valid     := reggen.io.valid
    (intfileFromMems zip reggen.regmapIOs).map {
      case (intfileFromMem, regmapIO) => intfileFromMem.regmap(regmapIO._1, regmapIO._2)
    }
  }
}

class TLIMSIC(
  params: IMSICParams,
  beatBytes: Int = 8,
)(implicit p: Parameters) extends LazyModule {
  val axireg = LazyModule(new TLRegIMSIC(params, beatBytes)(Parameters.empty))

  lazy val module = new Imp
  class Imp extends LazyModuleImp(this) {
    val toCSR = IO(Output(new IMSICToCSRBundle(params)))
    val fromCSR = IO(Input(new CSRToIMSICBundle(params)))
    private val imsic = Module(new IMSIC(params, beatBytes))
    toCSR := imsic.toCSR
    imsic.fromCSR := fromCSR
    imsic.io.seteipnum := axireg.module.io.seteipnum
    imsic.io.valid := axireg.module.io.valid
    /* code on when imsic has two clock domains.*/
    //--- define soc_clock for imsic bus logic ***//
    val soc_clock = IO(Input(Clock()))
    val soc_reset = IO(Input(Reset()))
    axireg.module.clock := soc_clock
    axireg.module.reset := soc_reset
    imsic.clock := clock
    imsic.reset := reset
    when(params.EnableImsicAsyncBridge.B) {
      val FifoDataWidth = params.imsicIntSrcWidth + params.intFilesNum
      //---- instance async fifo ----//
      //--- fifo wdata: {vector_valid,setipnum}, fifo wren: |vector_valid---//
      val fifo_wdata = Wire(Valid(UInt(FifoDataWidth.W)))
      fifo_wdata.bits := Cat(axireg.module.io.valid.asUInt, axireg.module.io.seteipnum)
      fifo_wdata.valid := axireg.module.io.valid.reduce(_ | _)
      //--- instance about fifo async queue sink  ---//
      val sink = Module(new AsyncQueueSink(UInt(FifoDataWidth.W),AsyncQueueParams(8,3,false,false)))
      sink.io.deq.ready := true.B
      //--- fifo rdata decode ---//
      imsic.io.seteipnum := sink.io.deq.bits(params.imsicIntSrcWidth - 1, 0)

      val fifo_rvalids = sink.io.deq.bits(FifoDataWidth - 1, params.imsicIntSrcWidth)
      val rvalids_tovec = VecInit(Seq.fill(params.intFilesNum)(false.B)) // bits->vector
      for (i <- 0 until params.intFilesNum) {
        rvalids_tovec(i) := fifo_rvalids(i)
      }
      when(sink.io.deq.valid) { // active when sink.valid active
        imsic.io.valid := rvalids_tovec
      }.otherwise {
        imsic.io.valid := Seq.fill(params.intFilesNum)(false.B)
      }
      //--- instance about fifo async queue source  ---//
      val source = Module(new AsyncQueueSource(UInt(FifoDataWidth.W),AsyncQueueParams(8,3,false,false)))
      source.clock := soc_clock
      source.reset := soc_reset
      source.io.enq.valid := fifo_wdata.valid
      source.io.enq.bits := fifo_wdata.bits
      sink.io.async <> source.io.async

    }.otherwise {
      imsic.io.seteipnum := axireg.module.io.seteipnum
      imsic.io.valid := axireg.module.io.valid
    }
  }
}

//integrated for async clock domain,kmh,zhaohong
class RegGen(
  params: IMSICParams,
  beatBytes: Int = 8,
) extends Module {
  val regmapIOs = Seq(
    params.intFileMemWidth,
    params.intFileMemWidth + log2Ceil(1+params.geilen)
  ).map(width => {
    val regmapParams = RegMapperParams(width-log2Up(beatBytes), beatBytes)
    ( IO(Flipped(Decoupled(new RegMapperInput(regmapParams)))),
      IO(Decoupled(new RegMapperOutput(regmapParams))))
  })
  //define the output reg: seteipnum is the MSI id,vld[],valid flag for interrupt file domains: m,s,vs1~vsgeilen
  val io = IO(Output(new Bundle {
    val seteipnum = UInt(params.imsicIntSrcWidth.W)
    val valid = Vec(params.intFilesNum,Bool())
  }))
  val valids = WireInit(VecInit(Seq.fill(params.intFilesNum)(false.B)))
  val seteipnums = WireInit(VecInit(Seq.fill(params.intFilesNum)(0.U(params.imsicIntSrcWidth.W))))
  val outseteipnum = RegInit(0.U(params.imsicIntSrcWidth.W))
  val outvalids = RegInit(VecInit(Seq.fill(params.intFilesNum)(false.B)))

  (regmapIOs zip Seq(1, 1+params.geilen)).zipWithIndex.map { //seq[0]: m interrupt file, seq[1]: s&vs interrupt file
    case ((regmapIO: (DecoupledIO[RegMapperInput], DecoupledIO[RegMapperOutput]),intFilesNum: Int), i: Int)
    => {
      // j: index is 0 for m file for seq[0],index is 0~params.geilen for S intFile for seq[1]: S, G1, G2, ...
      val maps = (0 until intFilesNum).map { j => {
        val flati = i + j       //seq[0]:0+0=0;seq[1]:(0~geilen)+1
        val seteipnum = WireInit(0.U.asTypeOf(Valid(UInt(params.imsicIntSrcWidth.W)))); /*for debug*/dontTouch(seteipnum)
        valids(flati) := seteipnum.valid
        seteipnums(flati) := seteipnum.bits
        (j * pow2(params.intFileMemWidth).toInt -> Seq(RegField(32, 0.U,
          RegWriteFn((valid, data) => {
            when (valid) { seteipnum.bits := data(params.imsicIntSrcWidth-1,0); seteipnum.valid := true.B }; true.B
          }))))
          }}
      regmapIO._2 <> RegMapper(beatBytes, 1, true, regmapIO._1, maps: _*)
    }
  outseteipnum := seteipnums.reduce(_|_)
  outvalids    := valids
  io.seteipnum := outseteipnum
  io.valid     := outvalids
  }
}

//generate axi42reg for IMSIC
class AXIRegIMSIC(
                 params: IMSICParams,
                 beatBytes: Int = 8,
               )(implicit p: Parameters) extends LazyModule {
  val fromMem = AXI4Xbar()
  private val intfileFromMems = Seq(
    AddressSet(params.mAddr,  pow2(params.intFileMemWidth) - 1),
    AddressSet(params.sgAddr, pow2(params.intFileMemWidth) * pow2(log2Ceil(1+params.geilen)) - 1),
  ).map(addrset => {
    val intfileFromMem = AXI4RegMapperNode(
      address = addrset,
      beatBytes = beatBytes)
    intfileFromMem := fromMem
    intfileFromMem
  })

  lazy val module = new AXIRegIMSICImp(this)
  class AXIRegIMSICImp(outer: LazyModule) extends LazyModuleImp(outer) {
    val io = IO(Output(new Bundle {
      val seteipnum = UInt(params.imsicIntSrcWidth.W)
      val valid = Vec(params.intFilesNum,Bool())
    }))

    private val reggen = Module(new RegGen(params, beatBytes))

    io.seteipnum := reggen.io.seteipnum
    io.valid     := reggen.io.valid
    (intfileFromMems zip reggen.regmapIOs).map {
      case (intfileFromMem, regmapIO) => intfileFromMem.regmap(regmapIO._1, regmapIO._2)
    }
  }
}

class AXI4IMSIC(
  params: IMSICParams,
  beatBytes: Int = 8,
)(implicit p: Parameters) extends LazyModule {
  val axireg = LazyModule(new AXIRegIMSIC(params, beatBytes)(Parameters.empty))
  lazy val module = new Imp
  class Imp extends LazyModuleImp(this) {
    val toCSR = IO(Output(new IMSICToCSRBundle(params)))
    val fromCSR = IO(Input(new CSRToIMSICBundle(params)))
    private val imsic = Module(new IMSIC(params, beatBytes))
    toCSR := imsic.toCSR
    imsic.fromCSR := fromCSR
    imsic.io.seteipnum := axireg.module.io.seteipnum
    imsic.io.valid := axireg.module.io.valid
    /* code on when imsic has two clock domains.*/
    //--- define soc_clock for imsic bus logic ***//
    val soc_clock = IO(Input(Clock()))
    val soc_reset = IO(Input(Reset()))
    axireg.module.clock := soc_clock
    axireg.module.reset := soc_reset
    imsic.clock := clock
    imsic.reset := reset
    when(params.EnableImsicAsyncBridge.B) {
      val FifoDataWidth = params.imsicIntSrcWidth + params.intFilesNum
      //---- instance async fifo ----//
      //--- fifo wdata: {vector_valid,setipnum}, fifo wren: |vector_valid---//
      val fifo_wdata = Wire(Valid(UInt(FifoDataWidth.W)))
      fifo_wdata.bits := Cat(axireg.module.io.valid.asUInt, axireg.module.io.seteipnum)
      fifo_wdata.valid := axireg.module.io.valid.reduce(_|_)
      //--- instance about fifo async queue sink  ---//
      val sink = Module(new AsyncQueueSink(UInt(FifoDataWidth.W),AsyncQueueParams(8,3,false,false)))
      sink.io.deq.ready := true.B
      //--- fifo rdata decode ---//
      imsic.io.seteipnum := sink.io.deq.bits(params.imsicIntSrcWidth-1, 0)

      val fifo_rvalids = sink.io.deq.bits(FifoDataWidth-1, params.imsicIntSrcWidth)
      val rvalids_tovec = VecInit(Seq.fill(params.intFilesNum)(false.B))// bits->vector
      for (i <- 0 until params.intFilesNum) {
        rvalids_tovec (i) := fifo_rvalids(i)
      }
       when(sink.io.deq.valid) {  // active when sink.valid active
         imsic.io.valid := rvalids_tovec
       }.otherwise{
         imsic.io.valid := Seq.fill(params.intFilesNum)(false.B)
       }
      //--- instance about fifo async queue source  ---//
      val source = Module(new AsyncQueueSource(UInt(FifoDataWidth.W),AsyncQueueParams(8,3,false,false)))

      source.clock := soc_clock
      source.reset := soc_reset
      source.io.enq.valid := fifo_wdata.valid
      source.io.enq.bits := fifo_wdata.bits
      sink.io.async <> source.io.async

    }.otherwise {
      imsic.io.seteipnum := axireg.module.io.seteipnum
      imsic.io.valid := axireg.module.io.valid
    }
  }
}
