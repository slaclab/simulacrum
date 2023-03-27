import os
import sys
import asyncio
import json
import functools
import math
from collections import OrderedDict
from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
#from caproto.server.records import _Limits 
from caproto.server.records.mixins import _Limits
from caproto import ChannelType
import simulacrum
import zmq
from zmq.asyncio import Context

#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')

class MagnetPV(PVGroup):
    bcon = pvproperty(value=0.0, name=':BCON')
    bdes = pvproperty(value=0.0, name=':BDES')
    bact = pvproperty(value=0.0, name=':BACT', read_only=True)
    bmin = pvproperty(value=0.0, name=':BMIN', read_only=True)
    bmax = pvproperty(value=0.0, name=':BMAX', read_only=True)
    blem = pvproperty(value=0.0, name=':BLEM')
    eact = pvproperty(value=0.0, name=':EACT')
    edes = pvproperty(value=0.0, name=':EDES')
    eerr = pvproperty(value=0.0, name=':EERR')
    stat = pvproperty(value=65.0, name=':STAT')
    bdes_save = pvproperty(value=0.0, name=':BDESSAVE')
    edes_save = pvproperty(value=0.0, name=':EDESSAVE')
    ctrl_strings = ("Ready", "TRIM", "PERTURB", "BCON_TO_BDES", "SAVE_BDES",
                    "LOAD_BDES", "UNDO_BDES", "DAC_ZERO", "CALB", "STDZ",
                    "RESET", "TURN_ON", "TURN_OFF")                
    ctrl = pvproperty(value=0, name=':CTRL', dtype=ChannelType.ENUM,
                      enum_strings=ctrl_strings)
    func = pvproperty(value=0, name=':FUNC', dtype=ChannelType.ENUM,
                      enum_strings=ctrl_strings)
    madname = pvproperty(name=":MADNAME", read_only=True, dtype=ChannelType.STRING)
    statmsg = pvproperty(value=0, name=':STATMSG', read_only=True, dtype=ChannelType.ENUM,
        enum_strings=("Good", "BCON Warning", "Offline", "PAU Ctrl", "Turned Off", "Not Degaus'd",
                      "Not Cal'd", "Feedback Ctrl", "Tripped", "DAC Error", "ADC Error", "Not Stdz'd",
                      "Out-of-Tol", "BAD Ripple", "BAD BACT", "No Control"))
    abort = pvproperty(value=0, name=':ABORT', dtype=ChannelType.ENUM,
                      enum_strings=("Ready", "Abort"))
    select = pvproperty(value=0, name=':SELECT', dtype=ChannelType.ENUM, enum_strings=("NO", "YES"))
    selecten = pvproperty(value=0, name=':SELECTEN', dtype=ChannelType.ENUM, enum_strings=("NO", "YES"))
    bdesegu = pvproperty(name=":BDES.EGU", read_only=True, dtype=ChannelType.STRING)
    bactegu = pvproperty(name=":BACT.EGU", read_only=True, dtype=ChannelType.STRING)
    bctrlegu = pvproperty(name=":BCTRL.EGU", read_only=True, dtype=ChannelType.STRING)
    bconegu = pvproperty(name=":BCON.EGU", read_only=True, dtype=ChannelType.STRING)
    
    def __init__(self, device_name, element_name, change_callback, length, initial_value, read_only=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_name = device_name
        self.element_name = element_name
        self.length = length
        self.read_only = read_only
        self.saved_bdes = None
        self.bdes_for_undo = None
        self.madname._data['value'] = element_name
        self.bcon._data['value'] = float(initial_value['bact'])
        self.bdes._data['value'] = float(initial_value['bact'])
        self.bact._data['value'] = float(initial_value['bact'])
        self.bctrl._data['value'] = float(initial_value['bact'])
        if not read_only:
            self.change_callback = change_callback
        if 'precision' in initial_value:
            prec = int(initial_value['precision'])
            self.bcon._data['precision'] = prec
            self.bdes._data['precision'] = prec
            self.bact._data['precision'] = prec
            self.bctrl._data['precision'] = prec
        if 'units' in initial_value:
            egu = initial_value['units']
            self.bcon._data['units'] = egu
            self.bdes._data['units'] = egu
            self.bact._data['units'] = egu
            self.bctrl._data['units'] = egu
            self.bconegu._data['value'] = egu
            self.bdesegu._data['value'] = egu
            self.bactegu._data['value'] = egu
            self.bctrlegu._data['value'] = egu
            self.bmin._data['units'] = egu
            self.bmax._data['units'] = egu
        if 'upper_ctrl_limit' in initial_value:
            hopr = float(initial_value['upper_ctrl_limit'])
            self.bcon._data['upper_ctrl_limit'] = hopr
            self.bdes._data['upper_ctrl_limit'] = hopr
            self.bact._data['upper_ctrl_limit'] = hopr
            self.bctrl._data['upper_ctrl_limit'] = hopr
            self.bctrl._data['upper_disp_limit'] = hopr
            self.bmax._data['value'] = hopr
        if 'lower_ctrl_limit' in initial_value:
            lopr = float(initial_value['lower_ctrl_limit'])
            self.bcon._data['lower_ctrl_limit'] = lopr
            self.bdes._data['lower_ctrl_limit'] = lopr
            self.bact._data['lower_ctrl_limit'] = lopr
            self.bctrl._data['lower_ctrl_limit'] = lopr
            self.bctrl._data['lower_disp_limit'] = lopr
            self.bmin._data['value'] = lopr
        
    @ctrl.putter
    async def ctrl(self, instance, value):
        if self.read_only:
            L.info("Ignoring write to read-only magnet: %s", self.device_name)
            return 0
        ioc = instance.group
        if value == "PERTURB":
            await ioc.bact.write(ioc.bdes.value)
            if self.change_callback:
                await self.change_callback(self, ioc.bact.value)
        elif value == "TRIM":
            await asyncio.sleep(0.2)
            await ioc.bact.write(ioc.bdes.value)
            if self.change_callback:
                await self.change_callback(self, ioc.bact.value)
        elif value == "BCON_TO_BDES":
            await ioc.bdes.write(ioc.bcon.value)
        elif value == "SAVE_BDES":
            self.saved_bdes = ioc.bdes.value
        elif value == "LOAD_BDES":
            if self.saved_bdes:
                await ioc.bdes.write(self.saved_bdes)
        elif value == "UNDO_BDES":
            if self.bdes_for_undo:
                await ioc.bdes.write(self.bdes_for_undo)
        else:
           L.warning("Warning, using a non-implemented magnet control function.")
        return 0
    
    @pvproperty(value=0.0, name=":BCTRL",record='ao')
    async def bctrl(self, instance):
        # We have to do some hacky stuff with caproto private data
        # because otherwise, the putter method gets called any time
        # we read.
        ioc = instance.group
        instance._data['value'] = ioc.bact.value
        return None
    
    @bctrl.putter
    async def bctrl(self, instance, value):
        if self.read_only:
            return
        ioc = instance.group
        instance._data['value'] = value
        await ioc.bdes.write(value)
        await ioc.ctrl.write("PERTURB")
        return value
    
    @bact.putter
    async def bact(self, instance, value):
        ioc = instance.group
        bctrl_val = self.bctrl._data['value']
        if bctrl_val != value:
            L.debug("bctrl = {}, value = {}".format(bctrl_val, value))
            self.bctrl._data['value'] = value
            await self.bctrl.publish(0)
        return value
    
    @bdes.putter
    async def bdes(self, instance, value):
        if self.read_only:
            return
        ioc = instance.group
        self.bdes_for_undo = ioc.bdes.value
        return value
    
    @bact.putter
    async def bact(self, instance, value):
        ioc = instance.group
        self.bctrl._data['value'] = value
        await self.bctrl.publish(0)
        return value

def _parse_corr_table(table):
    """ Build a dictionary of element_name -> (BACT)."""
    # We use the 'tesla_to_kGm' function here for both bends and quads,
    # even though quads actually just use kG units (not kG*m).
    # This is because BMAD specifies quad strength as a gradient (T/m),
    # so the math is the same for quads and bends.
    splits = [row.split() for row in table]
    return {simulacrum.util.convert_element_to_device(ele_name): {"length": float(l), "bact": bl_kick_to_BACT(float(bl_kick))} for (_, ele_name, _, _, l, bl_kick) in splits if ele_name in simulacrum.util.element_names}

def _parse_quad_table(table):
    splits = [row.split() for row in table]
    return {simulacrum.util.convert_element_to_device(ele_name): {"length": float(l), "bact": quad_gradient_to_BACT(float(b1_gradient), float(l))} for (_, ele_name, _, _, l, b1_gradient) in splits if ele_name in simulacrum.util.element_names}

def _parse_multipole_table(table):
    splits = [row.split() for row in table]
    return {simulacrum.util.convert_element_to_device(ele_name): {"length": 0.0, "bact": multipole_K1L_to_BACT(float(k1l), float(p0c))} for (_, ele_name, _, _, _, k1l, p0c) in splits if ele_name in simulacrum.util.element_names}

def _parse_bend_table(table):
    splits = [row.split() for row in table]
    return {simulacrum.util.convert_element_to_device(ele_name): {"length": float(l), "bact": bend_b_field_to_BACT(float(b_field), float(l))} 
        for (_, ele_name, _, _, l, b_field) in splits if ele_name in simulacrum.util.element_names}

def bl_kick_to_BACT(bl_kick, l=None):
    """Convert the bl_kick attribute (T*m) for a corrector into SLAC BACT compatible kG*m units"""
    return -bl_kick*10.0

def BACT_to_bl_kick(bact, l=None):
    """Convert SLAC corrector BACT (kG*m) into Bmad compatible T*m units"""
    return -bact/10.0

def quad_gradient_to_BACT(b1_gradient, l):
    """Convert the b1_gradient (T/m) attribute for a quad into SLAC BACT kG units"""
    return -b1_gradient*10.0*l

def quad_BACT_to_gradient(bact, l):
    """Convert a SLAC quad BACT (kG) into Bmad b1_gradient T/m units"""
    return -bact/(10.0*l)                                                                                                  

def multipole_K1L_to_BACT(k1l,p0c):
    """Convert K1L attribute for skew quad into SLAC BACT kG units"""
    b_rho = p0c * 1E-9 / 299.792458*1e4
    return k1l * b_rho

def multipole_BACT_to_K1L(bact,p0c):
    """Convert a SLAC skew quad BACT (kG) into Bmad K1L"""
    b_rho = p0c * 1E-9 / 299.792458*1e4
    return bact/b_rho

def bend_BACT_to_b_field(bact, l):
    """Convert a SLAC bend BACT (GeV/c) into BMAD b_field T units"""
    return -bact*9.06721219/l

def bend_b_field_to_BACT(b_field, l):
    """Convert a BMAD b_field (T) into SLAC bend BACT (GeV/c)"""
    return -b_field*.11028748186*l

class MagnetService(simulacrum.Service):
    attr_for_mag_type = {"XCOR": "bl_hkick", "YCOR": "bl_vkick", "QUAD": "b1_gradient", "BEND": "b_field"}
    conversion_to_BMAD_for_mag_type = {"XCOR": BACT_to_bl_kick, "YCOR": BACT_to_bl_kick, "QUAD": quad_BACT_to_gradient, "BEND": bend_BACT_to_b_field}
    def __init__(self):
        super().__init__()
        self.ctx = Context.instance()
        #cmd socket is a synchronous socket, we don't want the asyncio context.
        self.cmd_socket = zmq.Context().socket(zmq.REQ)
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))
        init_vals = self.get_initial_values()
        magnet_element_list = self.get_magnet_list_from_model()
        magnet_device_list = [simulacrum.util.convert_element_to_device(element) for element in magnet_element_list]
        mag_pvs = {device_name: MagnetPV(device_name, simulacrum.util.convert_device_to_element(device_name), self.on_magnet_change, length=init_vals[device_name]['length'], initial_value=init_vals[device_name], prefix=device_name) 
                    for device_name in magnet_device_list
                    if device_name in init_vals}
        self.add_pvs(mag_pvs)
        #print(init_vals.keys())

        #print(mag_pvs.keys())
        # Lets do some custom additions to handle bend magnets.
        self.add_pvs(self.make_bends())
        
        # Now that we've set up all the magnets, we need to send the model a
        # command to use non-normalized magnetic field units.
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "set ele Hkicker::*,Vkicker::*,Quadrupole::*,Sbend::*,Multipole::* field_master = T"})
        self.cmd_socket.recv_pyobj()
        L.info("Initialization complete.")
        
    def get_magnet_list_from_model(self):
        element_list = []
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show ele -no_slaves Hkicker::*,Vkicker::*"})
        l1 =  self.cmd_socket.recv_pyobj()['result'][:-1]
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show ele -no_slaves Quadrupole::*,Multipole::*"})
        l2 =  self.cmd_socket.recv_pyobj()['result'][:-1]
        for row in l1 + l2:
            element_list.append(row.split(None, 3)[1])
        #print(element_list)
        return element_list
    
    def get_initial_values(self):
        init_vals = self.get_magnet_BACTs_from_model()
        path_to_limits_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "magnet_limits.json")
        with open(path_to_limits_file) as f:
            limits = json.load(f)
            for device_name in init_vals:
                try:
                    init_vals[device_name]["units"] = limits[device_name]["EGU"]
                    init_vals[device_name]["precision"] = limits[device_name]["PREC"]
                    init_vals[device_name]["upper_ctrl_limit"] = limits[device_name]["HOPR"]
                    init_vals[device_name]["lower_ctrl_limit"] = limits[device_name]["LOPR"]
                except KeyError:
                    pass
        return init_vals
    
    def get_magnet_BACTs_from_model(self):
        init_vals = {}
        for (attr, dev_list, parse_func) in [("bl_kick", "Hkicker::X*", _parse_corr_table), ("bl_kick", "Vkicker::Y*", _parse_corr_table), ("b1_gradient", "Quadrupole::* ", _parse_quad_table),  ("b_field", "Sbend::*", _parse_bend_table), ("K1L -attribute P0C", "Multipole::*", _parse_multipole_table)]:
            self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show lat -no_label_lines -attribute {attr} {list}".format(attr=attr, list=dev_list)})
            table = self.cmd_socket.recv_pyobj()
            init_vals.update(parse_func(table['result']))
        return init_vals

    async def on_magnet_change(self, magnet_pv, value):
        """ This method gets called any time a PV updates for XCORs, YCORs, or QUADs. """
        mag_type = magnet_pv.device_name.split(":")[0]
        mag_attr = self.attr_for_mag_type[mag_type]
        conv = self.conversion_to_BMAD_for_mag_type[mag_type]
        l = magnet_pv.length
        L.debug('Updating {}... '.format(magnet_pv.device_name))
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "set ele {element} {attr} = {val}".format(element=magnet_pv.element_name, 
                                                                                                   attr=mag_attr,
                                                                                                   val=conv(value, l))})
        self.cmd_socket.recv_pyobj()
        L.debug('Updated {}.'.format(magnet_pv.device_name))

    def make_bends(self):
        """ Make PVs for all the bends.  This is a lengthy procedure due to the
        ridiculous complexity of how these are defined: bends are usually strings,
        different types of bends work differently, naming conventions aren't
        consistent, etc etc."""
        # We treat chicane bends differently than the rest of the bends - they use kG*m units, rather than GeV/c
        # Tao has no way to tell the two apart, so we have to do it ourselves.  Yuck.
        # NOTE: These lists only include cu_hxr and cu_sxr devices right now.
        # This dictionary maps BMAD elements to the "master" bend element.
        # In the case of split bends, both splits map to the same master.
        chicane_bends = {"BXH1": "BXH2", "BXH2": "BXH2", "BXH3": "BXH2", "BXH4": "BXH2",
                         "BX11": "BX12", "BX12": "BX12", "BX13": "BX12", "BX14": "BX12",
                         "BX21": "BX22", "BX22": "BX22", "BX23": "BX22", "BX24": "BX22",
                         "BCX311": "BCX312", "BCX312": "BCX312", "BCX313": "BCX312", "BCX314": "BCX312",
                         "BCX31B1": "BCX31B2", "BCX31B2": "BCX31B2", "BCX31B3": "BCX31B2", "BCX31B4": "BCX31B2",
                         "BCX321": "BCX322", "BCX322": "BCX322", "BCX323": "BCX322", "BCX324": "BCX322",
                         "BCX32B1": "BCX32B2", "BCX32B2": "BCX32B2", "BCX32B3": "BCX32B2", "BCX32B4": "BCX32B2",
                         "BCX351": "BCX352", "BCX352": "BCX352", "BCX353": "BCX352", "BCX354": "BCX352",
                         "BCX361": "BCX362", "BCX362": "BCX362", "BCX363": "BCX362", "BCX364": "BCX362",
                         "BCXHS1": "BCXHS2", "BCXHS2": "BCXHS2", "BCXHS3": "BCXHS2", "BCXHS4": "BCXHS2",
                         "BCXXL1": "BCXXL2", "BCXXL2": "BCXXL2", "BCXXL3": "BCXXL2", "BCXXL4": "BCXXL2",
                         "BCXSS1": "BCXSS2", "BCXSS2": "BCXSS2", "BCXSS3": "BCXSS2", "BCXSS4": "BCXSS2",
                         "BCXH1": "BCXH2",  "BCXH2": "BCXH2",  "BCXH3": "BCXH2",  "BCXH4":  "BCXH2",
                         "BCX11":  "BCX12", "BCX12":   "BCX12", "BCX13":   "BCX12", "BCX14":   "BCX12",
                         "BCX21":   "BCX22", "BCX22":   "BCX22", "BCX23":  "BCX22", "BCX24":   "BCX22",
                         "BCXDLU1": "BCXDLU2", "BCXDLU2": "BCXDLU2", "BCXDLU3": "BCXDLU2", "BCXDLU4": "BCXDLU2", 
                         "BCXDLD1": "BCXDLD2", "BCXDLD2": "BCXDLD2", "BCXDLD3": "BCXDLD2", "BCXDLD4": "BCXDLD2"
                        }

        dl_bends = {"BX01": "BX02", "BX02": "BX02",
                    "BYCUS1": "BYCUS1", "BYCUS2": "BYCUS1",
                    "BRCUSDC1": "BRCUSDC1", "BRCUSDC2": "BRCUSDC1",
                    "BLRCUS": "BLRCUS",
                    "BKRCUS": "BKRCUS",
                    "BRCUS1": "BRCUS1",
                    "BY1": "BY1", "BY2": "BY1",
                    "BY1B": "BY1B", "BY2B": "BY1B",
                    "BX31": "BYD1", "BX32": "BYD1", "BX35": "BYD1", "BX36": "BYD1", "BYD1": "BYD1", "BYD2": "BYD1", "BYD3": "BYD1",
                    "BYDSH": "BYDSH",
                    "BX31B": "BYD1B", "BX32B": "BYD1B", "BX35B": "BYD1B", "BX36B": "BYD1B", "BYD1B": "BYD1B", "BYD2B": "BYD1B", "BYD3B": "BYD1B",
                    "BYDSS": "BYDSS",
                    "BXKIK": "BXKIK",
                    "BYKIK1": "BYKIK1", "BYKIK2": "BYKIK1",
                    "BYKIK1S": "BYKIK1S", "BYKIK2S": "BYKIK1S",
                    "BRB1":   "BRB1", "BRB2": "BRB1",  
                    "BKYSP0H": "BKYSP0H", "BKYSP1H": "BKYSP0H", "BKYSP2H": "BKYSP0H", "BKYSP3H": "BKYSP0H", "BKYSP4H": "BKYSP0H", "BKYSP5H": "BKYSP0H",
                    "BLXSPH": "BLXSPH", 
                    "BYSP1H": "BYSP1H", "BYSP2H": "BYSP1H", 
                    "BRSP1H": "BRSP1H", "BRSP2H":  "BRSP1H",
                    "BXSP1H": "BXSP1H",
                   }
        # Get a list of all bends, and the attributes we need to use them.
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show lat -tracking_elements -no_label_lines -attribute g -attribute b_field -attribute b_field_err SBend::*"})
        result = self.cmd_socket.recv_pyobj()
        # Parse this list, make all the conversion factors, and create the magnet PVs for the bends.
        # We store them in a 'bends' dictionary, keyed on the element name of the master bend.
        bends = {}
        master_bends = {}
        for line in result['result']:
            L.debug(line)
            s = line.split()
            element_name = s[1]
            l = float(s[4]) # Length of the magnet (in meters)
            g = float(s[5]) # g = 1/rho, where rho is bend radius.  g has units of 1/meter
            b_init_tesla = float(s[6]) # The "design" magnetic field for the magnet, in tesla.
            b_field_err_init = float(s[7]) # The "field error" for this magnet, in tesla.
            # Make a 'BendElement', which is usually half of a bend, for every item in this list.
            bend_type = None
            if element_name in chicane_bends:
                L.debug("{} is in a chicane".format(element_name))
                master_bend_name = chicane_bends[element_name]
                bend_type = "chicane"
            elif element_name in dl_bends:
                L.debug("{} is in a bend".format(element_name))
                master_bend_name = dl_bends[element_name]
                bend_type = "dogleg"
            else:
                L.warning("Found an un-handled bend magnet: {}.  Ignoring it, not creating PVs.".format(element_name))
            if bend_type:
                if master_bend_name not in bends:
                    bends[master_bend_name] = []
                bend = Bend(element_name, l, g, b_init_tesla, b_field_err_init, bend_type)
                bends[master_bend_name].append(bend)
                if element_name == master_bend_name:
                    master_bends[master_bend_name] = bend
                
        # Make BendString objects for each string we've found.
        bend_strings = []
        for string_name in bends:
            bends_for_string = bends[string_name]
            # Determine the 'master' bend.
            master_bend = master_bends[string_name]
            L.debug("Making a string for {}.  Bend list: {}.  Master: {}".format(string_name, [bend.element_name for bend in bends_for_string], master_bend.element_name))
            bend_strings.append(BendString(bends_for_string, master_bend, self.cmd_socket))
        
        # Make all the PV objects.
        path_to_limits_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "magnet_limits.json")
        with open(path_to_limits_file) as f:
            limits = json.load(f)
            pvs = {}
            for string in bend_strings:
                pvs.update({bend_pv.device_name: bend_pv for bend_pv in string.make_pvs(limits)})
            #print(pvs.keys())
            return pvs

class Bend:
    """ Represents one bend magnet.  Usually these are part of a string.
        One MagnetPV object is created for each bend magnet. """
    def __init__(self, name, l, g, b_init_tesla, b_field_err_init, bend_type):
        self.element_name = name
        self.device_name = simulacrum.util.convert_element_to_device(self.element_name)
        self.l = l
        self.g = g
        self.b_init_tesla = b_init_tesla
        self.b_field_err_init = b_field_err_init
        self.bend_type = bend_type
        assert bend_type in ("chicane", "dogleg")
        if bend_type == "chicane":
            self.unit = "kG*m"
        elif bend_type == "dogleg":
            self.unit = "GeV/c"
        
    def convert_to_b_field_err(self, b_field):
        if self.bend_type == "chicane":
            # b_field is in kG, convert to Tesla.
            field_units = "kG"
            b_field_tesla = -1.0 * math.copysign(1, self.g) * b_field / 10.0
        elif self.bend_type == "dogleg":
            # b_field is in GeV/c, convert to Tesla.
            field_units = "GeV/c"
            b_field_tesla = ((-1.0 * 10**9 * b_field * self.g)/2.99792458e8)
        b_field_error =  b_field_tesla - self.b_init_tesla
        L.debug("%s: Converted %f %s to %f T.  b_init = %f, b_err = %f", self.element_name, b_field, field_units, b_field_tesla, self.b_init_tesla, b_field_error)
        return b_field_error
    
    def convert_tesla_to_epics_units(self, b_field_tesla):
        if self.bend_type == "chicane":
            b_field_kgm = -10.0 * math.copysign(1, self.g) * b_field_tesla * self.l
        elif self.bend_type == "dogleg":
            if self.g == 0:
              b_field_kgm = 0.0
            else:
              b_field_kgm = -1.0 * 2.99792458e8 * b_field_tesla / (self.g * 10**9)
        L.debug("%s: Converted %f T to %f kGm.  Length is %f", self.element_name, b_field_tesla, b_field_kgm, self.l)
        return b_field_kgm
    
    def set_field_strength_command(self, b_field):
        if self.bend_type == "chicane":
            b_err = self.convert_to_b_field_err(b_field/self.l)
        elif self.bend_type == "dogleg":
            b_err = self.convert_to_b_field_err(b_field)
        return f"set ele {self.element_name} b_field_err = {b_err}"
    
    def make_pv(self, read_only, precision=None, upper_ctrl_limit=None, lower_ctrl_limit=None, change_callback=None):
        init_vals = {"bact": self.convert_tesla_to_epics_units(self.b_init_tesla), "units": self.unit}
        if precision:
            init_vals["precision"] = precision
        if upper_ctrl_limit:
            init_vals["upper_ctrl_limit"] = upper_ctrl_limit
        if lower_ctrl_limit:
            init_vals["lower_ctrl_limit"] = lower_ctrl_limit
        L.debug("%s: Making PV.  Init Vals: %s", self.element_name, repr(init_vals))
        self.pv = MagnetPV(self.device_name, self.element_name, change_callback, length=self.l, initial_value=init_vals, read_only=read_only, prefix=self.device_name)
        return self.pv
        
class BendString:
    """ Represents a whole string of bends.  This class is responsible for
        setting magnet strengths in the model. """
    def __init__(self, bends, master, cmd_socket):
        self.bends = bends
        self.master_bend = master
        self.cmd_socket = cmd_socket
    
    def send_field_strength_to_model(self, b_field_from_epics):
        commands = []
        for bend in self.bends:
            sub_command = bend.set_field_strength_command(b_field_from_epics)
            commands.append(sub_command)
        L.debug("Sending batch to model: {}".format(commands))
        self.cmd_socket.send_pyobj({"cmd": "tao_batch", "val": commands})
        return self.cmd_socket.recv_pyobj()
    
    def make_pvs(self, limit_vals):
        for bend in self.bends:
            if bend != self.master_bend:
                read_only = True
                bend.make_pv(read_only, limit_vals[bend.device_name]['PREC'] if bend.device_name in limit_vals else None, 
                             limit_vals[bend.device_name]['HOPR'] if bend.device_name in limit_vals else None,
                             limit_vals[bend.device_name]['LOPR'] if bend.device_name in limit_vals else None)
        # Now make the master bend PV        
        async def change_callback(magnet_pv, value):
            L.debug("Changing bend strength to %f", value)
            self.send_field_strength_to_model(value)
            for bend in self.bends:
                if bend != self.master_bend:
                    # Update all the non-master bend PVs, without triggering their callbacks.
                    bend.pv.bctrl._data['value'] = value
                    await bend.pv.bctrl.publish(0)
                    bend.pv.bdes._data['value'] = value
                    await bend.pv.bdes.publish(0)
                    bend.pv.bact._data['value'] = value
                    await bend.pv.bact.publish(0)
                
        read_only = False 
        self.master_bend.make_pv(read_only, limit_vals[bend.device_name]['PREC'] if bend.device_name in limit_vals else None, 
                                           limit_vals[bend.device_name]['HOPR'] if bend.device_name in limit_vals else None,
                                           limit_vals[bend.device_name]['LOPR'] if bend.device_name in limit_vals else None,
                                           change_callback)
                
        return [bend.pv for bend in self.bends]

def main():
    service = MagnetService()
    loop = asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix='',
        desc="Simulated Magnet Service")
    run(service, **run_options)
    
if __name__ == '__main__':
    main()
    
    
