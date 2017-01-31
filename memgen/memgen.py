#!/usr/bin/python3

import sys
import re
import math

### Helpers ###
def print_usage():
    print("Usage                    : ./memgen.py <tech> <infile>")
    print("")
    print("")
    print("      <tech>             : Target technology for memory generation.")
    print("                           Supported technologies: unisim")
    print("")
    print("      <infile>           : List of required memories to generate.")
    print("                           One descriptor per line.")
    print("")
    print("")
    print("")
    print("Memory descriptor syntax : <name> <words> <width> <parallel_op_list>")
    print("")
    print("")
    print("      <name>             : Memory name")
    print("")
    print("      <words>            : Number of logic words in memory")
    print("")
    print("      <width>            : Word bit-width")
    print("")
    print("      <parallel_op_list> : List of parallel accesses to memory. These may require one or more ports.")
    print("")
    print("")
    print("")
    print("Operation-list element   : <write_pattern>:<read_pattern>")
    print("")
    print("")
    print("      <read_pattern>     : 0r                 -> no read operation")
    print("                         : 1r                 -> 1 read operation")
    print("                         : <[2|4|8|16]>r      -> parallel read operations with known (modulo) address pattern.")
    print("                                                 Data are distributed across banks and the number of banks must")
    print("                                                 be a power of two to have low-overhead bank-selection logic")
    print("                         : <N>ru              -> N parallel read operations with unknown address pattern. This")
    print("                                                 option incurs data and memory duplication. N can be any number")
    print("                                                 from 2 to 16.")
    print("")
    print("      <write_pattern>    : 0w                 -> no write operation")
    print("                         : 1w                 -> 1 write operation")
    print("                         : <[2|4|8|16]>w      -> 2 parallel write operations with known (modulo) address pattern.")
    print("                                                 Data are distributed across banks and the number of banks must")
    print("                                                 be a power of two to have low-overhead bank-selection logic")
    print("                         : 2wu                -> 2 parallel write operations with unknown address pattern. This is")
    print("                                                 viable by using both physical ports of dual-port banks, but only")
    print("                                                 in combination with \"0r\" as read pattern.")
    print("")
    sys.exit(1)


def die_werr(message):
    print("  ERROR: " + message)
    sys.exit(2)


def warn(message):
    print("  WARNING: " + message)


def is_power2z(n):
    # True if zero or power of 2
    return ((n & (n - 1)) == 0)

ASSERT_ON = True

### Data structures ###
class sram():
    name = ""
    words = 0
    width = 0
    area = 0.0
    ports = 0

    def __init__(self, name, words, width, area, ports):
        self.name = name
        self.words = words
        self.width = width
        self.area = area
        self.ports = ports

    def print(self):
        token1 = self.name
        token1 = format(token1, '>20')
        token2 = str(self.words)
        token2 = format(token2, '>7')
        token3 = str(self.width)
        token3 = format(token3, '>3')
        token4 = str(self.ports)
        token4 = format(token4, '>2')
        print("  INFO: Found SRAM definition " + \
              token1 + token2 + token3 + "-bit words " + \
              token4 + " read/write ports ")



class memory_operation():
    rn = 1
    rp = "unknown"
    wn = 1
    wp = "unknown"

    def __init__(self, rn, rp, wn, wp):
        self.rn = rn
        self.rp = rp
        self.wn = wn
        self.wp = wp

    def __str__(self):
        if self.rp == "modulo":
            rp = "r"
        else:
            rp = "ru"
        if self.wp == "modulo":
            wp = "w"
        else:
            wp = "wu"
        return str(self.wn) + wp + ":" + str(self.rn) + rp



class memory():
    name = ""
    words = 0
    width = 0
    ops = [ ]

    read_interfaces = 1
    write_interfaces = 1
    need_dual_port = False
    need_parallel_rw = False
    duplication_factor = 1
    distribution_factor = 1
    # Horizontally duplicated banks when read pattern is unknown
    dbanks = 1
    # Horizontally composed banks to obtain desired parallelism
    hbanks = 1
    # Vertically composed banks to obtain desired word count
    vbanks = 1
    # Horizontally composed banks to obtain desired bit-width
    hhbanks = 1
    # Type of SRAM chosen to implement banks
    bank_type = None
    # Total area
    area = float('inf')

    def __init__(self, name, words, width, ops):
        self.name = name
        if words <= 0:
            die_werr("Memory "+name+" has illegal number of words")
        if width <= 0:
            die_werr("Memory "+name+" has illegal bit-width")
        if len(ops) == 0:
            die_werr("No operation specified for memory \"" + name + "\"")
        self.words = words
        self.width = width
        self.ops = ops

    def print(self):
        operations = " ".join(map(str, self.ops))
        print("  INFO: Generating " + self.name + "...")
        print("        " + str(self.words) + " words, " + str(self.width) + " bits, " + operations)

    def __find_hbanks(self):
        for op in self.ops:
            self.read_interfaces = max(self.read_interfaces, op.rn)
            self.write_interfaces = max(self.write_interfaces, op.wn)
            # parallel_rw
            self.need_parallel_rw = (self.need_parallel_rw or
                                     (op.rn > 0 and op.wn > 0))
            # Note that we force dual-port memories to get half the number of hbanks when possible
            # dual_port
            self.need_dual_port = (self.need_dual_port or
                                   self.need_parallel_rw or
                                   (op.wn == 2 and op.wp == "unknown") or
                                   ((not self.need_parallel_rw) and (op.rn > 1 or op.wn > 1)))

        for op in self.ops:
            # Duplication
            op_duplication_factor = 1
            if (op.rp == "unknown" and op.rn > 1):
                if (op.wn == 0):
                    op_duplication_factor = int(math.ceil(op.rn / 2))
                else:
                    op_duplication_factor = op.rn
            if (op.wp == "unknown" and op.wn > 1):
                if (op.rn == 0):
                    op_duplication_factor = int(math.ceil(op.wn / 2))
                else:
                    op_duplication_factor = max(op_duplication_factor, op.wn)
            self.duplication_factor = max(self.duplication_factor, op_duplication_factor)

        for op in self.ops:
            # Distribution
            op_distribution_factor = 1
            if (op.rp == "modulo" and op.rn > 1):
                if (op.wn != 0 or self.need_parallel_rw ):
                    op_distribution_factor = op.rn
                else:
                    op_distribution_factor = op.rn >> 1
            if (op.wp == "modulo" and op.wn > 1):
                if (op.rn != 0 or self.need_parallel_rw):
                    op_distribution_factor = max(op_distribution_factor, op.wn)
                else:
                    op_distribution_factor = op.wn >> 1
            self.distribution_factor = max(self.distribution_factor, op_distribution_factor)

        # Number of distributed banks and duplicated bank sets
        self.dbanks = self.duplication_factor
        self.hbanks = self.distribution_factor

    def __find_vbanks(self, lib):
        words_per_hbank = int(math.ceil(self.words / self.hbanks))
        d = self.dbanks
        h = self.hbanks
        for ram in lib:
            if self.need_dual_port and (ram.ports < 2):
                continue
            hh = int(math.ceil(self.width / ram.width))
            v = int(math.ceil(words_per_hbank / ram.words))
            new_area = d * h * hh * v * ram.area
            if self.area > (new_area):
                self.vbanks = v
                self.hhbanks = hh
                self.bank_type = ram
                self.area = new_area

    def __write_check_access_task(self, fd):
        fd.write("\n")
        fd.write("  task check_access;\n")
        fd.write("    input integer iface;\n")
        fd.write("    input integer d;\n")
        fd.write("    input integer h;\n")
        fd.write("    input integer v;\n")
        fd.write("    input integer hh;\n")
        fd.write("    input integer p;\n")
        fd.write("  begin\n")
        fd.write("    if ((check_bank_access[d][h][v][hh][p] != -1) &&\n")
        fd.write("        (check_bank_access[d][h][v][hh][p] != iface)) begin\n")
        fd.write("      $display(\"ASSERTION FAILED in %m: port conflict on bank\", h, \"h\", v, \"v\", hh, \"hh\", \" for port\", p, \" involving interfaces\", check_bank_access[d][h][v][hh][p], iface);\n")
        fd.write("      $finish;\n")
        fd.write("    end\n")
        fd.write("    else begin\n")
        fd.write("      check_bank_access[d][h][v][hh][p] = iface;\n")
        fd.write("    end\n")
        fd.write("  end\n")
        fd.write("  endtask\n")



    def __write_ctrl_assignment(self, fd, bank_addr_range_str, hh_range_str, duplicated_bank_set, port, iface, is_write, parallelism):
        ce_str = [ ]
        a_str = [ ]
        d_str = [ ]
        we_str = [ ]
        wem_str = [ ]
        for d in range(0, self.dbanks):
            ce_str_i = [ ]
            a_str_i = [ ]
            d_str_i = [ ]
            we_str_i = [ ]
            wem_str_i = [ ]
            for p in range(0, self.bank_type.ports):
                ce_str_i.append ("              bank_CE["  + str(d) + "][h][v][hh]["  + str(p) + "]  = "  + self.name + "_CE")
                a_str_i.append  ("              bank_A["   + str(d) + "][h][v][hh]["  + str(p) + "]   = " + self.name + "_A")
                d_str_i.append  ("              bank_D["   + str(d) + "][h][v][hh]["  + str(p) + "]   = " + self.name + "_D")
                we_str_i.append ("              bank_WE["  + str(d) + "][h][v][hh]["  + str(p) + "]  = "  + self.name + "_WE")
                wem_str_i.append("              bank_WEM[" + str(d) + "][h][v][hh]["  + str(p) + "] = "   + self.name + "_WEM")
            ce_str.append(ce_str_i)
            a_str.append(a_str_i)
            d_str.append(d_str_i)
            we_str.append(we_str_i)
            wem_str.append(wem_str_i)

        # This handles cases in which there are multiple parallel ops with pattern "modulo", but different distribution factor.
        if parallelism != 0:
            normalized_iface = iface
            # If access patter is modulo, we know it's a power of two. If it's not modulo parallelism is set to 0 when calling this method
            if not is_write:
                normalized_iface = iface - self.write_interfaces
            normalized_iface = normalized_iface % self.hbanks
            normalized_parallelism = min(parallelism, self.hbanks)
            fd.write("          if (h % " + str(normalized_parallelism) + " == " + str(normalized_iface) + ") begin\n")
        fd.write("            if (ctrlh[" + str(iface) + "] == h && ctrlv[" + str(iface) + "] == v && " + self.name + "_CE" + str(iface) + " == 1'b1) begin\n")
        # Check that no port is accessed by more than one interface
        if (ASSERT_ON):
            fd.write("// synthesis translate_off\n")
            fd.write("              check_access(" + str(iface) + ", " + str(duplicated_bank_set) + ", h, v, hh, " + str(port) + ");\n")
            fd.write("// synthesis translate_on\n")
        fd.write(ce_str[duplicated_bank_set][port]  + str(iface)                       + ";\n")
        fd.write(a_str[duplicated_bank_set][port]   + str(iface) + bank_addr_range_str + ";\n")
        if is_write:
            fd.write(d_str[duplicated_bank_set][port]   + str(iface) + hh_range_str        + ";\n")
            fd.write(we_str[duplicated_bank_set][port]  + str(iface)                       + ";\n")
            fd.write(wem_str[duplicated_bank_set][port] + str(iface) + hh_range_str        + ";\n")
        fd.write("            end\n")
        if parallelism != 0:
            fd.write("          end\n")

    def write_verilog(self):
        try:
            fd = open(self.name + ".v", 'w')
        except IOError as e:
            die_werr(e)
        fd.write("/**\n")
        fd.write("* Created with the ESP Memory Generator\n")
        fd.write("*\n")
        fd.write("* Copyright (c) 2014-2017, Columbia University\n")
        fd.write("*\n")
        fd.write("* @author Paolo Mantovani <paolo@cs.columbia.edu>\n")
        fd.write("*/\n")
        fd.write("\n")
        fd.write("`timescale  1 ps / 1 ps\n")
        fd.write("\n")
        fd.write("module " + self.name + "(\n")
        fd.write("    CLK")
        # Module interface
        for i in range(0, self.write_interfaces):
            fd.write(",\n    " + self.name + "_CE" + str(i))
            fd.write(",\n    " + self.name + "_A" + str(i))
            fd.write(",\n    " + self.name + "_D" + str(i))
            fd.write(",\n    " + self.name + "_WE" + str(i))
            fd.write(",\n    " + self.name + "_WEM" + str(i))
        for i in range(self.write_interfaces, self.write_interfaces + self.read_interfaces):
            fd.write(",\n    " + self.name + "_CE" + str(i))
            fd.write(",\n    " + self.name + "_A" + str(i))
            fd.write(",\n    " + self.name + "_Q" + str(i))
        fd.write("\n  );\n")
        fd.write("  input CLK;\n")
        for i in range(0, self.write_interfaces):
            fd.write("  " + "input " + self.name + "_CE" + str(i) + ";\n")
            fd.write("  " + "input " + "[" + str(int(math.ceil(math.log(self.words, 2)))-1) + ":0] " + self.name + "_A" + str(i) + ";\n")
            fd.write("  " + "input " + "[" + str(self.width-1) + ":0] " + self.name + "_D" + str(i) + ";\n")
            fd.write("  " + "input " + self.name + "_WE" + str(i) + ";\n")
            fd.write("  " + "input " + "[" + str(self.width-1) + ":0] " + self.name + "_WEM" + str(i) + ";\n")
        for i in range(self.write_interfaces, self.write_interfaces + self.read_interfaces):
            fd.write("  " + "input " + self.name + "_CE" + str(i) + ";\n")
            fd.write("  " + "input " + "[" + str(int(math.ceil(math.log(self.words, 2)))-1) + ":0] " + self.name + "_A" + str(i) + ";\n")
            fd.write("  " + "output " + "[" + str(self.width-1) + ":0] " + self.name + "_Q" + str(i) + ";\n")
        fd.write("  genvar d, h, v, hh;\n")
        fd.write("\n")

        # Wire for banks
        bank_wire_addr_width     = int(math.ceil(math.log(self.bank_type.words, 2)))
        bank_wire_data_width     = self.bank_type.width
        sel_dbank_reg_width      = int(math.ceil(math.log(self.dbanks, 2)))
        sel_hbank_reg_width      = int(math.ceil(math.log(self.hbanks, 2)))
        sel_vbank_reg_width      = int(math.ceil(math.log(self.vbanks, 2)))
        signle_wire_width_str    = "            "
        bank_wire_dims_str       = "[" + str(self.dbanks - 1) + ":0]" + "[" + str(self.hbanks - 1) + ":0]" + "[" + str(self.vbanks - 1) + ":0]" + "[" + str(self.hhbanks - 1) + ":0]" + "[" + str(self.bank_type.ports - 1) + ":0]"
        bank_wire_addr_width_str = "[" + str(bank_wire_addr_width - 1) + ":0]"
        bank_wire_addr_width_str = format(bank_wire_addr_width_str, ">12")
        bank_wire_data_width_str = "[" + str(bank_wire_data_width - 1) + ":0]"
        bank_wire_data_width_str = format(bank_wire_data_width_str, ">12")
        ctrl_wire_dims_str        = "[" + str(self.write_interfaces + self.read_interfaces - 1) + ":0]"
        sel_reg_dims_str         = "[" + str(self.write_interfaces + self.read_interfaces - 1) + ":" + str(self.write_interfaces) + "]"
        if self.dbanks > 1:
            sel_dbank_reg_width_str  = "[" + str(sel_dbank_reg_width - 1) + ":0]"
        else:
            sel_dbank_reg_width_str  = "[0:0]"
        sel_dbank_reg_width_str  = format(sel_dbank_reg_width_str, ">12")
        if self.hbanks > 1:
            sel_hbank_reg_width_str  = "[" + str(sel_hbank_reg_width - 1) + ":0]"
        else:
            sel_hbank_reg_width_str  = "[0:0]"
        sel_hbank_reg_width_str  = format(sel_hbank_reg_width_str, ">12")
        if self.vbanks > 1:
            sel_vbank_reg_width_str  = "[" + str(sel_vbank_reg_width - 1) + ":0]"
        else:
            sel_vbank_reg_width_str  = "[0:0]"
        sel_vbank_reg_width_str  = format(sel_vbank_reg_width_str, ">12")
        fd.write("  " + "reg  " + signle_wire_width_str    + " bank_CE  " + bank_wire_dims_str + ";\n")
        fd.write("  " + "reg  " + bank_wire_addr_width_str + " bank_A   " + bank_wire_dims_str + ";\n")
        fd.write("  " + "reg  " + bank_wire_data_width_str + " bank_D   " + bank_wire_dims_str + ";\n")
        fd.write("  " + "reg  " + signle_wire_width_str    + " bank_WE  " + bank_wire_dims_str + ";\n")
        fd.write("  " + "reg  " + bank_wire_data_width_str + " bank_WEM " + bank_wire_dims_str + ";\n")
        fd.write("  " + "wire " + bank_wire_data_width_str + " bank_Q   " + bank_wire_dims_str + ";\n")
        fd.write("  " + "wire " + sel_dbank_reg_width_str  + " ctrld    " + sel_reg_dims_str   + ";\n")
        fd.write("  " + "wire " + sel_hbank_reg_width_str  + " ctrlh    " + ctrl_wire_dims_str + ";\n")
        fd.write("  " + "wire " + sel_vbank_reg_width_str  + " ctrlv    " + ctrl_wire_dims_str + ";\n")
        fd.write("  " + "reg  " + sel_dbank_reg_width_str  + " seld     " + sel_reg_dims_str   + ";\n")
        fd.write("  " + "reg  " + sel_hbank_reg_width_str  + " selh     " + sel_reg_dims_str   + ";\n")
        fd.write("  " + "reg  " + sel_vbank_reg_width_str  + " selv     " + sel_reg_dims_str   + ";\n")
        if (ASSERT_ON):
            fd.write("// synthesis translate_off\n")
            fd.write("  " + "integer check_bank_access " + bank_wire_dims_str + ";\n")
            self.__write_check_access_task(fd)
            fd.write("// synthesis translate_on\n")
        fd.write("\n")

        # Control selection
        for ri in range(self.write_interfaces, self.write_interfaces + self.read_interfaces):
            # For ru type of operations we guarantee to insist on different copies of the memory structure
            if self.dbanks > 1:
                fd.write("  assign ctrld[" + str(ri) + "] = " + str(ri % self.dbanks) + ";\n")
            else:
                fd.write("  assign ctrld[" + str(ri) + "] = 0;\n")
        for ri in range(0, self.write_interfaces + self.read_interfaces):
            if self.hbanks > 1:
                fd.write("  assign ctrlh[" + str(ri) + "] = " + self.name + "_A" + str(ri) + "[" + str(sel_hbank_reg_width - 1) + ":" + "0" + "];\n")
            else:
                fd.write("  assign ctrlh[" + str(ri) + "] = 0;\n")
        for ri in range(0, self.write_interfaces + self.read_interfaces):
            if self.vbanks > 1:
                fd.write("  assign ctrlv[" + str(ri) + "] = " + self.name + "_A" + str(ri) + "[" + str(bank_wire_addr_width + sel_hbank_reg_width + sel_vbank_reg_width - 1) + ":" +str(bank_wire_addr_width + sel_hbank_reg_width) + "];\n")
            else:
                fd.write("  assign ctrlv[" + str(ri) + "] = 0;\n")
        fd.write("\n")

        # Output bank selection
        fd.write("  always @(posedge CLK) begin\n")
        for ri in range(self.write_interfaces, self.write_interfaces + self.read_interfaces):
            fd.write("    seld[" + str(ri) + "] <= ctrld[" + str(ri) + "];\n")
            fd.write("    selh[" + str(ri) + "] <= ctrlh[" + str(ri) + "];\n")
            fd.write("    selv[" + str(ri) + "] <= ctrlv[" + str(ri) + "];\n")
        fd.write("  end\n")
        fd.write("\n")

        # Control ports CE, A, D, WE, WEM assignment
        hh_msb_str = str(bank_wire_data_width) + " * (hh + 1) - 1"
        hh_lsb_str = str(bank_wire_data_width) + " * hh"
        hh_range_str = "[" + hh_msb_str + ":" + hh_lsb_str + "]"
        bank_addr_msb_str = str(min(int(math.ceil(math.log(self.words, 2))) - 1, bank_wire_addr_width + sel_hbank_reg_width - 1))
        bank_addr_lsb_str = str(sel_hbank_reg_width)
        bank_addr_range_str = "[" + bank_addr_msb_str + ":" + bank_addr_lsb_str + "]"
        fd.write("  generate\n")
        fd.write("  for (h = 0; h < " + str(self.hbanks) + "; h = h + 1) begin : gen_ctrl_hbanks\n")
        fd.write("    for (v = 0; v < " + str(self.vbanks) + "; v = v + 1) begin : gen_ctrl_vbanks\n")
        fd.write("      for (hh = 0; hh < " + str(self.hhbanks) + "; hh = hh + 1) begin : gen_ctrl_hhbanks\n")
        fd.write("\n")
        fd.write("        always @(*) begin : handle_ops\n")
        fd.write("\n")
        fd.write("          /** Default **/\n")
        for d in range(0, self.dbanks):
            for p in range(0, self.bank_type.ports):
                if (ASSERT_ON):
                    # Initialize variable for conflicts check
                    fd.write("// synthesis translate_off\n")
                    fd.write("          check_bank_access["  + str(d) + "][h][v][hh]["  + str(p) + "] = -1;\n")
                    fd.write("// synthesis translate_on\n")
                # Dfault assignment
                fd.write("          bank_CE["  + str(d) + "][h][v][hh][" + str(p) + "]  = 0;\n")
                fd.write("          bank_A["   + str(d) + "][h][v][hh][" + str(p) + "]   = 0;\n")
                fd.write("          bank_D["   + str(d) + "][h][v][hh][" + str(p) + "]   = 0;\n")
                fd.write("          bank_WE["  + str(d) + "][h][v][hh][" + str(p) + "]  = 0;\n")
                fd.write("          bank_WEM[" + str(d) + "][h][v][hh][" + str(p) + "] = 0;\n")
            fd.write("\n")
        # Go through parallel accesses
        # In some cases we're building a full cross-bar, however most links will be trimmed away by
        # constant propagation if the accelerator is accessing data in a distributed fashion across
        # interfaces. This occurs, because ctrh[iface] becomes a constant.
        for op in self.ops:
            fd.write("          /** Handle " + str(op) + " **/\n")
            # Handle 2wu:0r
            if op.wp == "unknown" and op.wn == 2:
                for d in range(0, self.dbanks):
                    fd.write("          // Duplicated bank set " + str(d) + "\n")
                    for wi in range(0, op.wn):
                        p = wi % self.bank_type.ports
                        self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, d, p, wi, True, 0)
            # Handle <N>w:0r with N power of 2
            if op.rn == 0 and op.wp == "modulo":
                # Write to all duplicated sets
                for d in range(0, self.dbanks):
                    fd.write("          // Duplicated bank set " + str(d) + "\n")
                    for wi in range(0, op.wn):
                        p = 0
                        if not self.need_parallel_rw:
                            p = (int(wi / self.hbanks) + (wi % self.bank_type.ports)) % self.bank_type.ports
                        self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, d, p, wi, True, op.wn)
            # Handle 0w:<N>r with N power of 2
            if op.wn == 0 and op.rp == "modulo":
                # All duplicated sets would return the same data. 0 is correct even with no duplication
                d = 0
                fd.write("          // Always choose duplicated bank set " + str(d) + "\n")
                for ri in range(0, op.rn):
                    p = 1
                    if not self.need_parallel_rw:
                        p = (int(ri / self.hbanks) + (ri % self.bank_type.ports)) % self.bank_type.ports
                    self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, d, p, ri + self.write_interfaces, False, op.rn)

            # Handle <N>r:<M>w with N and M power of 2. In this case hbanks matches max(op.rn, op.wn) foreach op in the list of operations
            if op.wn > 0 and op.rn > 0 and op.wp == "modulo" and op.rp == "modulo":
                # Write to all duplicated sets
                for d in range(0, self.dbanks):
                    fd.write("          // Duplicated bank set " + str(d) + "\n")
                    for wi in range(0, op.wn):
                        p = 0
                        self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, d, p, wi, True, op.wn)
                # All duplicated sets would return the same data. 0 is correct even with no duplication
                d = 0
                fd.write("          // Always choose duplicated bank set " + str(d) + "\n")
                for ri in range(0, op.rn):
                    p = 1
                    self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, d, p, ri + self.write_interfaces, False, op.rn)
            # Handle <N>ru:0w with N > 1
            if op.rn > 1 and op.wn == 0 and op.rp == "unknown":
                # Duplicated set matches the read interface number
                for ri in range(0, op.rn):
                    p = (int(ri / self.dbanks) + (ri % self.bank_type.ports)) % self.bank_type.ports
                    self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, ri % self.dbanks, p, ri + self.write_interfaces, False, 0)
            # Handle <N>ru:<M>w with N > 1 and M power of 2
            if op.rn > 1 and op.wn > 0 and op.rp == "unknown" and op.wp == "modulo":
                # Write to all duplicated sets
                for d in range(0, self.dbanks):
                    fd.write("          // Duplicated bank set " + str(d) + "\n")
                    for wi in range(0, op.wn):
                        p = 0
                        self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, d, p, wi, True, op.wn)
                # Duplicated set matches the read interface number
                for ri in range(0, op.rn):
                    p = 1
                    self.__write_ctrl_assignment(fd, bank_addr_range_str, hh_range_str, ri % self.dbanks, p, ri + self.write_interfaces, False, 0)
            fd.write("\n")
        fd.write("        end\n")
        fd.write("\n")
        fd.write("      end\n")
        fd.write("    end\n")
        fd.write("  end\n")
        fd.write("  endgenerate\n")
        fd.write("\n")

        # Read port Q assignment
        # When parallel rw is required, port 0 is used for write and port 1 is used for read
        # Otherwise, modulo is applied to choose which port should be used.
        fd.write("  generate\n")
        fd.write("  for (hh = 0; hh < " + str(self.hhbanks) + "; hh = hh + 1) begin : gen_q_assign_hhbanks\n")
        hh_last_msb_str = str(int(min(self.width - 1, self.hhbanks * self.bank_type.width - 1)))
        hh_last_range_str = "[" + hh_last_msb_str + ":" + hh_lsb_str + "]"

        for ri in range(self.write_interfaces, self.write_interfaces + self.read_interfaces):
            p = 1
            if self.bank_type.ports == 1:
                p = 0
            elif not self.need_parallel_rw:
                p = ri % self.bank_type.ports
            fd.write("    if (hh == " + str(self.hhbanks - 1) + " && (hh + 1) * " + str(self.bank_type.width) + " > " + str(self.width) + ")\n")
            fd.write("      assign " + self.name + "_Q" + str(ri) + hh_last_range_str + " = bank_Q" + "[seld[" + str(ri) +"]]" + "[selh[" + str(ri) +"]]" + "[selv[" + str(ri) +"]]" + "[hh]" + "[" + str(p) + "][" + str((self.width - 1) % self.bank_type.width) + ":0];\n")
            fd.write("    else\n")
            fd.write("      assign " + self.name + "_Q" + str(ri) + hh_range_str + " = bank_Q" + "[seld[" + str(ri) +"]]" + "[selh[" + str(ri) +"]]" + "[selv[" + str(ri) +"]]" + "[hh]" + "[" + str(p) + "];\n")
        fd.write("  end\n")
        fd.write("  endgenerate\n")
        fd.write("\n")

        # Bank instances
        fd.write("  generate\n")
        fd.write("  for (d = 0; d < " + str(self.dbanks) + "; d = d + 1) begin : gen_wires_dbanks\n")
        fd.write("    for (h = 0; h < " + str(self.hbanks) + "; h = h + 1) begin : gen_wires_hbanks\n")
        fd.write("      for (v = 0; v < " + str(self.vbanks) + "; v = v + 1) begin : gen_wires_vbanks\n")
        fd.write("        for (hh = 0; hh < " + str(self.hhbanks) + "; hh = hh + 1) begin : gen_wires_hhbanks\n")
        fd.write("\n")
        fd.write("          " + self.bank_type.name + " bank_i(\n")
        fd.write("              .CLK(CLK)")
        for p in range(0, self.bank_type.ports):
            fd.write(",\n              .CE"  + str(p) + "(bank_CE[d][h][v][hh]["  + str(p) + "])")
            fd.write(",\n              .A"   + str(p) + "(bank_A[d][h][v][hh]["   + str(p) + "])")
            fd.write(",\n              .D"   + str(p) + "(bank_D[d][h][v][hh]["   + str(p) + "])")
            fd.write(",\n              .WE"  + str(p) + "(bank_WE[d][h][v][hh]["  + str(p) + "])")
            fd.write(",\n              .WEM" + str(p) + "(bank_WEM[d][h][v][hh][" + str(p) + "])")
            fd.write(",\n              .Q"   + str(p) + "(bank_Q[d][h][v][hh]["   + str(p) + "])")
        fd.write("\n            );\n")
        fd.write("\n")
        if (ASSERT_ON):
            fd.write("// synthesis translate_off\n")
            fd.write("            always @(posedge CLK) begin\n")
            for p0 in range(0, self.bank_type.ports):
                for p1 in range(p0 + 1, self.bank_type.ports):
                    fd.write("              if " + "((bank_CE[d][h][v][hh]["  + str(p0) + "] & " + "bank_CE[d][h][v][hh]["  + str(p1) + "]) &&\n")
                    fd.write("                 " + " (bank_WE[d][h][v][hh]["  + str(p0) + "] | " + "bank_WE[d][h][v][hh]["  + str(p1) + "]) &&\n")
                    fd.write("                 " + " (bank_A[d][h][v][hh]["  + str(p0) + "] == " + "bank_A[d][h][v][hh]["  + str(p1) + "])) begin\n")
                    fd.write("                $display(\"ASSERTION FAILED in %m: address conflict on bank\", h, \"h\", v, \"v\", hh, \"hh\");\n")
                    fd.write("                $finish;\n")
                    fd.write("              end\n")
                    fd.write("            end\n")
                    fd.write("// synthesis translate_on\n")
                    fd.write("\n")
        fd.write("        end\n")
        fd.write("      end\n")
        fd.write("    end\n")
        fd.write("  end\n")
        fd.write("  endgenerate\n")
        fd.write("\n")
        fd.write("endmodule\n")
        fd.close()


    def gen(self, lib):
        # Determine memory requirements (first pass over ops list)
        self.__find_hbanks()
        self.__find_vbanks(lib)
        print("        " + "read_interfaces " + str(self.read_interfaces))
        print("        " + "write_interfaces " + str(self.write_interfaces))
        print("        " + "duplication_factor " + str(self.duplication_factor))
        print("        " + "distribution_factor " + str(self.distribution_factor))
        print("        " + "need_dual_port " + str(self.need_dual_port))
        print("        " + "need_parallel_rw " + str(self.need_parallel_rw))
        print("        " + "d-banks " + str(self.dbanks))
        print("        " + "h-banks " + str(self.hbanks))
        print("        " + "v-banks " + str(self.vbanks))
        print("        " + "hh-banks " + str(self.hhbanks))
        print("        " + "bank type " + str(self.bank_type.name))
        print("        " + "Total area " + str(self.area))


### Input parsing ###
def parse_sram(s):
    item = s.split()
    words = int(item[0])
    width = int(item[1])
    name = item[2]
    area = float(item[3])
    # We assume rw ports supporting one read or one write per cycle
    ports = int(item[4])
    if ports < 1 or ports > 2:
        warn("Skipping SRAM type " + name + " with unsopported number of ports")
        return None
    return sram(name, words, width, area, ports)

def parse_op(op, mem_words):
    item = op.split(":")
    write_number = int(re.split('[a-z]+', item[0], re.M|re.I)[0])
    write_pattern_abbrv = str(re.split('[0-9]+', item[0], re.M|re.I)[1])
    read_number = int(re.split('[a-z]+', item[1], re.M|re.I)[0])
    read_pattern_abbrv = str(re.split('[0-9]+', item[1], re.M|re.I)[1])

    if read_number > mem_words or write_number > mem_words:
        die_werr("Too many ports for the specified number of words for "+op)

    if read_number > 16 or read_number < 0:
        die_werr("Too many paralle accesses specified for "+op);

    if re.match(r'ru', read_pattern_abbrv, re.M|re.I):
        read_pattern = "unknown"
    elif re.match(r'r', read_pattern_abbrv, re.M|re.I):
        read_pattern = "modulo"
        if not is_power2z(read_number):
            die_werr("Operation "+op+" implies known access patter (modulo), but the number of accesses is not a power of 2")
    else:
        die_werr("Parallel read access "+op+" not recognized")

    if write_number > 16 or write_number < 0:
        die_werr("Too many paralle accesses specified for "+op);

    if re.match(r'wu', write_pattern_abbrv, re.M|re.I):
        write_pattern = "unknown"
        if write_number > 2:
            die_werr("Too many parallel write accesses with unknown pattern for "+op)
        if write_number == 2 and read_number != 0:
            die_werr("2 parallel write accesses with unknown pattern for "+op+" have non-zero parallel read access")
    elif re.match(r'w', write_pattern_abbrv, re.M|re.I):
        write_pattern = "modulo"
        if not is_power2z(write_number):
            die_werr("Operation "+op+" implies known access patter (modulo), but the number of accesses is not a power of 2")
    else:
        die_werr("Parallel write access "+op+" not recognized")

    return memory_operation(read_number, read_pattern, write_number, write_pattern)



def read_techfile(tech, sram_list):
    try:
        fd = open(tech + "/lib.txt", 'r')
    except IOError as e:
        die_werr(e)
    for line in fd:
        line.strip()
        # Check for commented line
        if re.match(r'#\.*', line, re.M|re.I):
            continue
        ram = parse_sram(line)
        if ram == None:
            continue
        sram_list.append(ram)
    fd.close()


def read_infile(name, mem_list):
    try:
        fd = open(name, 'r')
    except IOError as e:
        die_werr(e)
    for line in fd:
        line.strip()
        item = line.split()
        # Check for commented line
        if re.match(r'#\.*', line, re.M|re.I):
            continue
        mem_name = item[0]
        mem_words = int(item[1])
        mem_width = int(item[2])
        mem_ops = []
        for i in range(3, len(item)):
            mem_ops.append(parse_op(item[i], mem_words))
        mem = memory(mem_name, mem_words, mem_width, mem_ops)
        mem_list.append(mem)
    fd.close()


### Start script ###
if len(sys.argv) != 3:
    print_usage()
tech = sys.argv[1]
infile = sys.argv[2]
mem_list = []
sram_list = []

print("  INFO: Target technology: " + tech)
read_techfile(tech, sram_list)
for ram in sram_list:
    ram.print()

print("  INFO: Memory list file: " + infile)
read_infile(infile, mem_list)
for mem in mem_list:
    mem.print()
    mem.gen(sram_list)
    mem.write_verilog()
