import numpy as np
import sys
import os
from scipy.interpolate import CubicSpline
from scipy.io import loadmat
import asyncio
from collections import OrderedDict
from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
from caproto import ChannelType
import simulacrum
import zmq
from zmq.asyncio import Context
    
m_electron = 0.5109989461E6 #eV
c_light = 2.99792458E8 # m/sec
#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')


class LaserHeaterUndulatorPV(PVGroup):
    trim =  pvproperty(value=0, name=':TRIM.PROC')
    kactH = pvproperty(value=0.0, name=':KACT', read_only=True)
    kdesH = pvproperty(value=0.0, name=':KDES')

    def __init__(self, device_name, element_name, change_callback, initial_values, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_name = device_name  
        self.element_name = element_name
        self.kactH._data['value'] = float(initial_values['kactH'])
        self.kdesH._data['value'] = float(initial_values['kactH'])
        self.change_callback = change_callback 

    @trim.putter
    async def trim(self, instance, value):
        ioc = instance.group
        await asyncio.sleep(0.2)
        await ioc.kactH.write(ioc.kdesH.value)
        await self.change_callback(self, ioc.kactH.value)  

 
class phaseShifterPV(PVGroup):
    phas_proc =  pvproperty(value=0, name=':ConvertPI2Gap.PROC' ) #Go command 
    piact = pvproperty(value=0.0, name=':PIAct', read_only=True)
    pides = pvproperty(value=0.0, name=':PIDes')


    def __init__(self, device_name, element_name, change_callback, initial_values, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_name = device_name  
        self.element_name = element_name
        self.piact._data['value'] = float(initial_values['piact'])
        self.pides._data['value'] = float(initial_values['piact'])
        self.change_callback = change_callback 

    @phas_proc.putter
    async def phas_proc(self, instance, value):
        ioc = instance.group
        await asyncio.sleep(0.2)
        await ioc.piact.write(ioc.pides.value)
        await self.change_callback(self, ioc.piact.value)  


class UndulatorPV(PVGroup):
    useg_proc = pvproperty(value=0, name=':ConvertK2Gap.PROC' ) #Go command
    #gapact = pvproperty(value=0.0, name=':GapAct')
    #gapdes = pvproperty(value=0.0, name=':GapDes')
    kact = pvproperty(value=0.0, name=':KAct', read_only=True)
    kdes = pvproperty(value=0.0, name=':KDes')
    taper_des = pvproperty(value=0.0, name=':TaperDes')
    taper_act = pvproperty(value=0.0, name=':TaperAct', read_only=True)
    symm_act = pvproperty(value=0.0, name=':SymmetryAct', read_only=True)
    serial_n = pvproperty(value=0.0, name=':SerialNum')

    def __init__(self, device_name, element_name, change_callback, initial_values, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_name = device_name  
        self.element_name = element_name
        self.kact._data['value'] = float(initial_values['kact'])
        self.kdes._data['value'] = float(initial_values['kact'])
        self.taper_des._data['value'] = 0
        self.symm_act._data['value'] = 0
        self.change_callback = change_callback 

    @useg_proc.putter
    async def useg_proc(self, instance, value):
        ioc = instance.group
        await asyncio.sleep(0.2)
        await ioc.kact.write(ioc.kdes.value)
        await self.change_callback(self, ioc.kact.value)  

  
def _parse_undulator_table(table):
    splits = [row.split() for row in table if ("#" not in row and 'PSC' not in row)] 
    unds = {simulacrum.util.convert_element_to_device(ele_name): {"kact": und_B_max_to_Kact(float(b_max))} for (_, ele_name, _, _, l, b_max) in splits if 'UM' in ele_name}
    phas = {simulacrum.util.convert_element_to_device(ele_name): {"piact": B_max_to_PhaseIntegral(float(b_max))} for (_, ele_name, _, _, l, b_max) in splits if 'PS' in ele_name}
    vals = dict(unds, **phas)
    return vals

def und_B_max_to_Kact(b_max):
    # k=2, b_max = 8.2382661E-01 T
    return  (c_light * 0.026)  *  b_max / (2*np.pi*m_electron) 

def B_max_to_PhaseIntegral(b_max):
    pshxh_L        = 0.0495 # m 
    pshxh_L_period = 0.045 # m 
    phaseIntegral = pshxh_L /2 * (b_max *  pshxh_L_period / (2*np.pi))**2 *1E9
    return phaseIntegral

def Kact_to_und_B_max(k):
    #SXR b_max = my_umasxh_k * 2*pi*m_electron / (c_light * 0.039)
    #HXR b_max = my_umahxh_k * 2*pi*m_electron / (c_light * 0.026) with my_umahxh_k = 2.0
    return k * 2*np.pi*m_electron / (c_light * 0.026)

def Kact_to_heater_b_max(und_k):
    b_max = und_k * 2*np.pi*m_electron / (c_light * 0.054)
    return b_max

def PhaseIntegral_to_und_B_max(phaseIntegral):
    #from ...lcls-lattice/bmad/master/UND.bmad
    #SXR b_max = 2*pi / pssxh_L_period * sqrt(2 * pssxh_phase_integral / pssxh_L  ) with pssxh_L        = 0.0825   ! m and pssxh_L_period = 0.075 ! m 
    pshx_L_period = 0.045 # m 
    pshx_L        = 0.0495 # m 
    b_max = 2*np.pi / pshx_L_period * np.sqrt(2 * phaseIntegral / pshx_L  )
    return b_max

def get_bpm_offset_form_gap(gap):
    return  -0.002850/gap**3;

def get_bpm_element_from_useg(usegElement):
    unit = usegElement[-2:]
    beamLine = usegElement[3]
    return 'RFB' + beamLine + 'X' + unit

#TODO:
#The maximum BPM  movements when changing the gaps from fully open to fully closed would then be (as a function of cell):
#Cell13: dx~+0.9 microns, dy~-6.6 microns
#Cell14: dx~+1.0 microns, dy~-7.5 microns
#Cell15: dx~+1.3 microns, dy~-9.4 microns
#Cell16: dx~+0.9 microns, dy~-6.6 microns

def get_undulator_gap_from_K(element, valueK):
    try:
        get_undulator_gap_from_K.timesUsed += 1
    except AttributeError:
        ul = {}
        print('Loading /mccfs2/u1/lcls/matlab/ULT_GuiData/UL.mat data...')
        loadmat('/mccfs2/u1/lcls/matlab/ULT_GuiData/UL', ul, True, variable_names= 'ul')
        get_undulator_gap_from_K.timesUsed = 1

    beamLineIndx = 0 if 'UMAH' in element else 1
    useg = ul['ul'][beamLineIndx]['SplineData'][0]['USEG'][0][0][0]
    for indx in range(1,useg.size):
        try:
            usegIndx = indx if useg[indx][0][0][7][0][0][6][0] == element else -1
            if usegIndx>0:
                break
        except:
            pass
    if usegIndx <0:
        print(f'Failed to find {element}')
        return 0

    (SerialNumber,  Dataset, MMFtemp, MMFtemp_unit, gap_unit, K_unit, inFileDate, Rundate, SN,gap, K) = useg[usegIndx][0][0][0][0][0] 
    K = K.squeeze()[::-1] 
    gap = gap.squeeze()[::-1]
    cs = CubicSpline(K,gap)
    return cs(valueK)



class UndulatorService(simulacrum.Service):
    conversion_to_BMAD_for_und_type = {"USEG": Kact_to_und_B_max, "PHAS": PhaseIntegral_to_und_B_max}
    def __init__(self):
        super().__init__()
        self.ctx = Context.instance()
        #cmd socket is a synchronous socket, we don't want the asyncio context.
        self.cmd_socket = zmq.Context().socket(zmq.REQ)
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))
        init_vals = self.get_initial_values()
        undulator_element_list = self.get_undulator_list_from_model()
        undulator_device_list = [simulacrum.util.convert_element_to_device(element) for element in undulator_element_list]
        for device_name in undulator_device_list:
            if device_name in init_vals:
                initial_value=init_vals[device_name]
                #print(f'{device_name} {simulacrum.util.convert_device_to_element(device_name)} {initial_value}')
        und_pvs = {device_name: UndulatorPV(device_name, simulacrum.util.convert_device_to_element(device_name), self.on_undulator_change, initial_values=init_vals[device_name], prefix=device_name) 
                    for device_name in undulator_device_list
                    if device_name in init_vals and device_name.startswith('USEG')}
        phas_pvs = {device_name: phaseShifterPV(device_name, simulacrum.util.convert_device_to_element(device_name), self.on_undulator_change, initial_values=init_vals[device_name], prefix=device_name) 
                    for device_name in undulator_device_list
                    if device_name in init_vals and device_name.startswith('PHAS')}
        dev_name = 'USEG:IN20:466'
        init_valsH={'kactH':1.3852} 
        laser_heater_pvs = {dev_name:  LaserHeaterUndulatorPV('USEG:IN20:466', 'LH_UND', self.on_heater_und_change,  initial_values=init_valsH , prefix=dev_name)}
        #laser_heater_pvs = {dev_name:  LaserHeaterUndulatorPV('USEG:IN20:466', 'LH_UND', self.on_undulator_change,  initial_values=init_valsH , prefix=dev_name)}
        #print(laser_heater_pvs.keys())
        #print(phas_pvs.keys()) 
        self.add_pvs(laser_heater_pvs)
        self.add_pvs(phas_pvs)
        self.add_pvs(und_pvs)
        L.info("Initialization complete.")

    def get_undulator_list_from_model(self):
        element_list = []
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show ele -no_slaves Wiggler::*  "})
        for row in self.cmd_socket.recv_pyobj()['result'][:-1]:
            element_list.append(row.split(None, 3)[1])
        return element_list


    def get_initial_values(self):
        init_vals = self.get_undulator_Kacts_from_model()
        #path_to_limits_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "undulator_limits.json")
        #with open(path_to_limits_file) as f:
        #    limits = json.load(f)
        #    for device_name in init_vals:
        #        try:
        #            init_vals[device_name]["units"] = limits[device_name]["EGU"]
        #            init_vals[device_name]["precision"] = limits[device_name]["PREC"]
        #            init_vals[device_name]["upper_ctrl_limit"] = limits[device_name]["HOPR"]
        #            init_vals[device_name]["lower_ctrl_limit"] = limits[device_name]["LOPR"]
        #        except KeyError:
        #            pass
        return init_vals

    def get_undulator_Kacts_from_model(self):
        init_vals = {}
        for (attr, dev_list, parse_func) in [("B_MAX", "UM*", _parse_undulator_table), ("B_MAX", "PS*", _parse_undulator_table)]:
            self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show lat -no_label_lines -attribute {attr} {list}".format(attr=attr, list=dev_list)})
#        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show lat -no_label_lines -no_slaves -attribute {attr} {list}".format(attr="B_MAX", list="UMAHX*")})
            table = self.cmd_socket.recv_pyobj()
            init_vals.update(_parse_undulator_table(table['result']))
        return init_vals

    async def on_undulator_change(self, undulator_pv, valueK): 
        und_type = undulator_pv.device_name.split(":")[0]
        und_attr = 'B_MAX' 
        conv = self.conversion_to_BMAD_for_und_type[und_type]
        #l = magnet_pv.length
        L.debug('Updating {}... '.format( undulator_pv.device_name ) )
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "set ele {element} {attr} = {val}".format(element=undulator_pv.element_name, 
                                                                                                   attr=und_attr,
                                                                                                   val=conv(valueK))})
        self.cmd_socket.recv_pyobj()
        #Update BPM offsets when K changes see gapFromK.py
        gap =  get_undulator_gap_from_K(undulator_pv.element_name, valueK)
        bpm_yOffset = get_bpm_offset_form_gap(gap)
        bpm_element = get_bpm_element_from_useg(undulator_pv.element_name)
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "set ele {element} y_offset = {val}".format(element=bpm_element,  val=bpm_yOffset)})
        self.cmd_socket.recv_pyobj()

        L.info('Updated {}.'.format(undulator_pv.device_name))

    async def on_heater_und_change(self, undulator_pv, value):
        b_max = Kact_to_heater_b_max(value)
        L.debug('Updating {}... '.format( undulator_pv.device_name ) )
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "set ele LH_UND B_MAX = {bmax}".format(bmax=b_max)})
        self.cmd_socket.recv_pyobj()
        L.info('Updated {}.'.format(undulator_pv.device_name))


def main():
    service = UndulatorService()
    loop = asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix='',
        desc="Simulated Undulator Service")
    run(service, **run_options)
    
if __name__ == '__main__':
    main()
    
    
