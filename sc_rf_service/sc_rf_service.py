import asyncio
import os
from collections import OrderedDict

import zmq
from caproto import ChannelType
from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
from zmq.asyncio import Context

import simulacrum

DEBUG = False

# Known bug:
# First set up your terminal. Run model_service sc_hxr in the background
# Run this file in the background
# "caput ACCL:L1B:0220:SSA:PowerOff 1"   <-- This will reveal a bug on line 137: "await self.ssaOnOff_Act.write(0)"
# For some reason, the service won't recognize ssaOnOff_Act as a valid PV to write to (pv defined on line 39)
# This is weird because there's nothing unique about the way I define ssaOnOff_Act or its putter

# set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0],
                                  level='INFO')

# A note on the lattice: Oddly, phase and gradient are given by phi0_err and gradient_err
# I also include rf_frequency and is_on attributes because they might be useful later on??
# The 'alias' attribute is the device name, e.g., 'ACCL:L3B:3070'
taoAttributeTypeMap = OrderedDict({("gradient", float), ("gradient_err", float),
                                   ("phi0", float), ("phi0_err", float),
                                   ("rf_frequency", float), ("is_on", str),
                                   ("alias", str)})

taoAttributes = list(taoAttributeTypeMap.keys())

nameIdx = taoAttributes.index("alias") + 5

# the first five entries returned by tao are: ?, element name, ?, z position, length
lengthIdx = 4
zPositionIdx = 3
elemNameIdx = 1

cryomodulePrefixes = set()


class CryomodulePV(PVGroup):
    cryoSumLatchA = pvproperty(value=0, name=":CRYOSUMA_LTCH",
                               dtype=ChannelType.ENUM,
                               enum_strings=("OK", "Faulted"))
    cryoSumLatchB = pvproperty(value=0, name=":CRYOSUMB_LTCH",
                               dtype=ChannelType.ENUM,
                               enum_strings=("OK", "Faulted"))


class RackPV_HWI(PVGroup):
    hwi = pvproperty(value=0.0, name=":HWINITSUM", dtype=ChannelType.ENUM,
                     enum_strings=("Ok", "HW Init running", "LLRF chassis problem"))
    fro = pvproperty(value=0, name=":FREQSUM", dtype=ChannelType.ENUM,
                     enum_strings=("OK", "Still OK", "Faulted"))


class RackPV_Vacuum(PVGroup):
    beamLineVacuumA = pvproperty(value=0.0, name=":BMLNVACA_LTCH", dtype=ChannelType.ENUM,
                                 enum_strings=("Ok", "Fault"))
    beamLineVacuumB = pvproperty(value=0.0, name=":BMLNVACB_LTCH", dtype=ChannelType.ENUM,
                                 enum_strings=("Ok", "Fault"))


class RackPV_couplerVacuum(PVGroup):
    couplerVacuumA = pvproperty(value=0.0, name=":CPLRVACA_LTCH", dtype=ChannelType.ENUM,
                                enum_strings=("Ok", "Fault"))
    couplerVacuumB = pvproperty(value=0.0, name=":CPLRVACB_LTCH", dtype=ChannelType.ENUM,
                                enum_strings=("Ok", "Fault"))


class WatcherPV(PVGroup):
    heartbeat = pvproperty(value=0, name="SC_CAV_FAULT_HEARTBEAT",
                           dtype=ChannelType.INT)
    heartbeatWatcher = pvproperty(value=0, name="SC_CAV_FAULT:ALHBERR", dtype=ChannelType.ENUM,
                                  enum_strings=("RUNNING", "NOT_RUNNING", "INVALID"))


class CavityPV(PVGroup):
    pdes = pvproperty(value=0.0, name=':PDES', precision=1)
    pmean = pvproperty(value=0.0, name=':PMEAN', precision=1)
    pact = pvproperty(value=0.0, name=':PACT', precision=1)
    phas = pvproperty(value=0.0, name=':PHASE', read_only=True, precision=1)
    ades = pvproperty(value=0.0, name=':ADES', precision=1)
    aact = pvproperty(value=0.0, name=':AACT', read_only=True, precision=1)
    amean = pvproperty(value=0.0, name=':AMEAN', read_only=True, precision=1)
    gdes = pvproperty(value=100.0, name=':GDES', precision=1)
    gact = pvproperty(value=0.0, name=':GACT', read_only=True, precision=1)
    # l = pvproperty(value=1.038, name=':L', read_only=True, precision=1)
    z = pvproperty(value=0.0, name=':Z', read_only=True, precision=1)
    # ison = pvproperty(value=1, name=':RFREADYFORBEAM', dtype=ChannelType.ENUM,
    #                   enum_strings=("Not ready", "Ready"))
    #    phas = pvproperty(value=0.0, name=':PHASE', read_only=True, precision=1)
    pref = pvproperty(value=0.0, name=':PREF', precision=1)

    cudStatus = pvproperty(value="TLC", name=":CUDSTATUS", dtype=ChannelType.STRING)
    cudSevr = pvproperty(value=1, name=":CUDSEVR", dtype=ChannelType.ENUM,
                         enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID",
                                       "PARKED"))
    cudDesc = pvproperty(value="Name", name=":CUDDESC", dtype=ChannelType.CHAR)

    # ssa defaults to On = True
    ssaOn_Des = pvproperty(value=1, name=':SSA:PowerOn', dtype=ChannelType.ENUM,
                           enum_strings=("False", "True"))
    ssaOff_Des = pvproperty(value=0, name=':SSA:PowerOff', dtype=ChannelType.ENUM,
                            enum_strings=("False", "True"))
    ssaOnOff_Act = pvproperty(value=1, name=':IS_ON', dtype=ChannelType.ENUM,
                              enum_strings=("F", "T"))
    ssaLatch = pvproperty(value=1, name=":SSA_LTCH", dtype=ChannelType.ENUM,
                          enum_strings=("OK", "Fault"))
    ssaAlarmSum = pvproperty(value=0, name=":SSA:AlarmSummary.SEVR",
                             dtype=ChannelType.ENUM,
                             enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID"))
    cryoSummary = pvproperty(value=0, name=":CRYO_LTCH", dtype=ChannelType.ENUM,
                             enum_strings=("Ok", "Fault"))
    resLinkLatch = pvproperty(value=0, name=":RESLINK_LTCH",
                              dtype=ChannelType.ENUM, enum_strings=("OK", "Fault"))
    pllLatch = pvproperty(value=0, name=":PLL_LTCH", dtype=ChannelType.ENUM,
                          enum_strings=("Ok", "Fault"))
    pllFault = pvproperty(value=0, name=":PLL_FLT", dtype=ChannelType.ENUM,
                          enum_strings=("Ok", "Fault"))
    iocWatchdogLatch = pvproperty(value=0, name=":IOCWDOG_LTCH",
                                  dtype=ChannelType.ENUM,
                                  enum_strings=("OK", "Fault"))
    couplerTemp1Latch = pvproperty(value=0, name=":CPLRTEMP1_LTCH",
                                   dtype=ChannelType.ENUM,
                                   enum_strings=("Ok", "Fault"))
    couplerTemp2Latch = pvproperty(value=0, name=":CPLRTEMP2_LTCH",
                                   dtype=ChannelType.ENUM,
                                   enum_strings=("Ok", "Faulted"))
    stepperTempLatch = pvproperty(value=0, name=":STEPTEMP_LTCH",
                                  dtype=ChannelType.ENUM,
                                  enum_strings=("Ok", "Fault"))
    quenchLatch = pvproperty(value=0, name=":QUENCH_LTCH", dtype=ChannelType.ENUM,
                             enum_strings=("Ok", "Fault"))
    resonanceChassisSummary = pvproperty(value=0, name=":RESINTLK_LTCH", dtype=ChannelType.ENUM,
                                         enum_strings=("Ok", "Fault"))
    rfPermit = pvproperty(value=1, name=":RFPERMIT", dtype=ChannelType.ENUM,
                          enum_strings=("RF inhibit", "RF allow"))
    piezoHardwareSummary = pvproperty(value=0, name=":PZT:HWSTATSUM", dtype=ChannelType.ENUM,
                                      enum_strings=("", "", "Fault"))
    stepperHardwareSummary = pvproperty(value=0, name=":STEP:HWSTATSUM", dtype=ChannelType.ENUM,
                                        enum_strings=("", "", "Fault"))
    cavityCharacterization = pvproperty(value=0, name=":CAV:CALSTATSUM", dtype=ChannelType.ENUM,
                                        enum_strings=("", "", "Fault"))
    calibrationSum = pvproperty(value=0, name=":CAV:CALSUM", dtype=ChannelType.ENUM,
                                enum_strings=("Done", "Incomplete", "Error"))
    cavityController = pvproperty(value=0, name=":CTRL_SUM.SEVR", dtype=ChannelType.ENUM,
                                  enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID"))
    rfReadyForBeam = pvproperty(value=1, name=":RFREADYFORBEAM", dtype=ChannelType.ENUM,
                                enum_strings=("Not Ready", "Ready"))
    piezoFeedbackStatus = pvproperty(value=1, name=":PZT:MODECTRL",
                                     dtype=ChannelType.ENUM,
                                     enum_strings=("Manual", "Feedback"))
    piezoFeedbackSummary = pvproperty(value=0, name=":PZT:FBSTATSUM",
                                      dtype=ChannelType.ENUM,
                                      enum_strings=("", "", "Fault"))
    ampFeedbackSum = pvproperty(value=0, name=":AMPFB_SUM", dtype=ChannelType.ENUM,
                                enum_strings=("Not clipped", "Clipped RF-only mode",
                                              "Clipped beam mode"))
    phaseFeedbackSum = pvproperty(value=0, name=":PHAFB_SUM", dtype=ChannelType.ENUM,
                                  enum_strings=("Not clipped", "Clipped RF-only mode",
                                                "Clipped beam mode"))
    feedbackSum = pvproperty(value=0, name=":FB_SUM", dtype=ChannelType.ENUM,
                             enum_strings=("Not clipped", "Clipped RF-only mode",
                                           "Clipped beam mode"))
    parked = pvproperty(value=0, name=":PARK", dtype=ChannelType.ENUM,
                        enum_strings=("Not parked", "Parked"))

    # only using 2=off, 3=on. Defaults to on
    ssa_StatusMsg = pvproperty(value=3, name=':StatusMsg', dtype=ChannelType.ENUM,
                               enum_strings=("Unknown", "Faulted", "SSA Off",
                                             "SSA On", "Resetting Faults...",
                                             "Powering ON...", "Powering Off...",
                                             "Fault Reset Failed...",
                                             "Power On Failed...",
                                             "Power Off Failed...",
                                             "Rebooting SSA...",
                                             "Rebooting X-Port..."))

    ades = pvproperty(value=0.0, name=':ADES', precision=1)
    aact = pvproperty(value=0.0, name=':AACT', read_only=True, precision=1)
    amean = pvproperty(value=0.0, name=':AMEAN', read_only=True, precision=1)

    gdes = pvproperty(value=0.0, name=':GDES', precision=1)
    gact = pvproperty(value=0.0, name=':GACT', read_only=True, precision=1)

    length = pvproperty(value=1.038, name=':L', read_only=True, precision=1)
    z = pvproperty(value=0.0, name=':Z', read_only=True, precision=1)

    # 0 = off, 1 = on. Defaults to on
    rfState_Des = pvproperty(value=1, name=':RFCTRL', dtype=ChannelType.ENUM,
                             enum_strings=("Off", "On"))
    # Defaults to pulse
    rfMode_Des = pvproperty(value=4, name=':RFMODECRTL', dtype=ChannelType.ENUM,
                            enum_strings=("SELAP", "SELA", "SEL", "SEL Raw",
                                          "Pulse", "Chirp"))
    # Defaults to on
    rfState_Act = pvproperty(value=1, name=':RFSTATE', dtype=ChannelType.ENUM,
                             enum_strings=("Off", "On"))
    # Defaults to pulse
    rfMode_Act = pvproperty(value=4, name=':RFMODE', dtype=ChannelType.ENUM,
                            enum_strings=("SELAP", "SELA", "SEL", "SEL Raw",
                                          "Pulse", "Chirp"))

    def __init__(self, device_name, change_callback, initial_values, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_name = device_name
        self.element_name = initial_values[3]
        self.ssa_on = True
        self.gdes_i = initial_values[0] * 1.e-6  # Saves initial values
        self.aact_i = initial_values[0] * 1.e-6
        self.pdes_i = initial_values[1] * 360
        self.pact_i = initial_values[1] * 360
        self.pdes._data['value'] = initial_values[1] * 360
        self.pmean._data['value'] = initial_values[1] * 360
        self.pact._data['value'] = initial_values[1] * 360
        self.phas._data['value'] = initial_values[1] * 360
        self.ades._data['value'] = initial_values[0] * initial_values[4] * 1.e-6
        self.aact._data['value'] = initial_values[0] * initial_values[4] * 1.e-6
        self.amean._data['value'] = initial_values[0] * initial_values[4] * 1.e-6
        self.gdes._data['value'] = initial_values[0] * initial_values[4] * 1.e-6
        self.gact._data['value'] = initial_values[0] * initial_values[4] * 1.e-6
        self.length._data['value'] = initial_values[4]
        self.z._data['value'] = initial_values[3]
        self.rfReadyForBeam._data['value'] = 1 if initial_values[5] == 'T' else 0

    @phas.putter
    async def phas(self, instance, value):
        print('Setting phase to ', value)
        self.change_callback(self, value, "PHAS")
        return

    @gact.putter
    async def gact(self, instance, value):
        print('Setting gact to ', value)
        self.change_callback(self, value, "GACT")
        return

    @aact.putter
    async def aact(self, instance, value):
        # For now, we are making amean = aact
        self.amean._data['value'] = value
        await self.amean.publish(0)
        return

    @ssaOnOff_Act.putter
    async def ssaOnOff_Act(self, instance, value):
        print("Trying to execute on/off putter")
        if value == 0:
            self.change_callback(self, 'F', "IS_ON")
        elif value == 1:
            self.change_callback(self, 'T', "IS_ON")
        else:
            print('Invalid value for ssa on/off')
        return

    @ades.putter
    async def ades(self, instance, value):
        print('Setting ades to ', value)
        new_gdes = value / float(self.length.value)
        await self.gdes.write(new_gdes)
        return

    @pdes.putter
    async def pdes(self, instance, value):
        print('Setting pdes to ', value)
        await self.phas.write(value)
        return

    @gdes.putter
    async def gdes(self, instance, value):
        print('Setting gdes to ', value)
        await self.gact.write(value)
        new_ades = float(value) * float(self.length.value)
        self.ades._data['value'] = new_ades
        print('Setting aact to ', new_ades)
        await self.aact.write(new_ades)
        await self.ades.publish(0)
        return

    @ssa_StatusMsg.putter
    async def ssa_StatusMsg(self, instance, value):
        if value == 'SSA Off':  # 2 = 'SSA Off':
            print("Making status = SSA Off")
            await self.phas.write(0)
            await self.gact.write(0)
            await self.ssaOnOff_Act.write(0)
        elif value == 'SSA On':  # 3 = 'SSA On'
            print("Making status = SSA On")
            await self.phas.write(self.pdes.value)
            await self.gact.write(self.gdes.value)
            await self.ssaOnOff_Act.write(1)
        return

    @ssaOn_Des.putter
    async def ssaOn_Des(self, instance, value):
        if value == 'False':  # If On = False, then we need to make Off = True
            '''Here, I need to use the publish format because I'm trying to avoid
            triggering ssaOff_Des.putter. This avoids the two putters infinitely 
            calling each other because .publish() does not run a secondary .putter'''
            print("Making On = False")
            self.ssaOff_Des._data['value'] = 1
            await self.ssaOff_Des.publish(0)
            await self.ssa_StatusMsg.write(2)  # In ssa_Status, 2 = 'SSA Off'
        else:  # If On = True, then we need to make Off = False
            print("Making On = True")
            self.ssaOff_Des._data['value'] = 0
            await self.ssaOff_Des.publish(0)
            await self.ssa_StatusMsg.write(3)  # In ssa_Status, 3 = 'SSA On'
        return

    @ssaOff_Des.putter
    async def ssaOff_Des(self, instance, value):
        if value == 'False':  # If Off = False, then we need to make On = True
            '''See comments in ssaOn_Des'''
            print("Making Off = False")
            self.ssaOn_Des._data['value'] = 1
            await self.ssaOn_Des.publish(0)
            await self.ssa_StatusMsg.write(3)  # In ssa_Status, 3 = 'SSA On'
        else:  # If Off = True, then we need to make On = False
            print("Making Off = True")
            self.ssaOn_Des._data['value'] = 0
            await self.ssaOn_Des.publish(0)
            await self.ssa_StatusMsg.write(2)  # In ssa_Status, 2 = 'SSA Off'
        return


def _parse_cav_table(table):
    splits = [row.split() for row in table]
    return {simulacrum.util.convert_element_to_device(elemName): (
        float(bmadGrad), float(bmadPhas), float(Z), elemName, float(L), str(is_on)) for
        (_, elemName, _, Z, L, bmadGrad, bmadPhas, is_on) in splits}


def _make_linac_table(init_vals):
    L2list = ''.join([f"CAVL{number:02d}*," for number in range(4, 16)])
    L3_1list = ''.join([f"CAVL{number:02d}*," for number in range(16, 26)])
    L3_2list = ''.join([f"CAVL{number:02d}*," for number in range(26, 36)])
    sections = {"L1B": ("ACCL:L1B:0210", "CAVL02*,CAVL03*,"), "HL1B": ("ACCL:L1B:H110", "CAVC01*,CAVC02*,"),
                "L2B": ("ACCL:L2B:0410", L2list), "L3B1": ("ACCL:L3B:1610", L3_1list),
                "L3B2": ("ACCL:L3B:1610", L3_2list)};
    linac_pvs = {}
    for section in sections.keys():
        device = sections[section]
        device_name = device[0];
        element = device[1];
        linac_pvs["ACCL:" + section + ":ALL"] = init_vals[device_name][:3] + (element[:-1],)
    return linac_pvs


class CavityService(simulacrum.Service):
    def __init__(self):
        super().__init__()
        self.ctx = Context.instance()
        # cmd socket is a synchronous socket, we don't want the asyncio context.
        self.cmd_socket = zmq.Context().socket(zmq.REQ)
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))
        init_vals = self.get_cavity_ACTs_from_model()

        self.add_pvs({"PHYS:SYS0:1:": WatcherPV(prefix="PHYS:SYS0:1:")})
        self.add_pvs({"ALRM:SYS0:": WatcherPV(prefix="ALRM:SYS0:")})

        cav_pvs = {prefix: CavityPV(prefix, self.on_cavity_change, initial_values=init_vals[prefix],
                                    prefix=prefix) for prefix in init_vals.keys()}

        # setting up convenient linac section PVs for changing all of the L1B/L2B/L3B cavities simultaneously.
        # print(cav_pvs.keys())
        linac_init_vals = _make_linac_table(init_vals)
        # linac_pvs = {device_name: CavityPV(device_name, self.on_cavity_change, initial_values=linac_init_vals[device_name], prefix=device_name) for device_name in linac_init_vals.keys()}

        self.add_pvs(cav_pvs)
        # self.add_pvs(linac_pvs);
        L.info("Initialization complete.")

        hwi_prefix = {}
        blv_prefix = {}
        cpv_prefix = {}
        for device_name in init_vals.keys():
            cavityNumber = device_name[-2]
            if (device_name == "TCAV:DMPH:361" or device_name == "TCAV:DMPH:360"
                    or device_name == "ACCL:GUNB:455"):
                pass
            elif cavityNumber == "1" or cavityNumber == "2" or cavityNumber == "3" or cavityNumber == "4":
                hwi_prefix[device_name[:-2] + "00:RACKA"] = init_vals[device_name]
                blv_prefix[device_name[:-2] + "00"] = init_vals[device_name]
                cpv_prefix[device_name[:-2] + "10"] = init_vals[device_name]

            elif cavityNumber == "5" or cavityNumber == "6" or cavityNumber == "7" or cavityNumber == "8":
                hwi_prefix[device_name[:-2] + "00:RACKB"] = init_vals[device_name]
                blv_prefix[device_name[:-2] + "00"] = init_vals[device_name]
                cpv_prefix[device_name[:-2] + "10"] = init_vals[device_name]

            else:
                print("something is wrong with ", device_name)

        hwi_pvs = {device_name: RackPV_HWI(prefix=device_name) for device_name in hwi_prefix.keys()}

        blv_pvs = {device_name: RackPV_Vacuum(prefix=device_name) for device_name in blv_prefix.keys()}

        cpv_pvs = {device_name: RackPV_couplerVacuum(prefix=device_name) for device_name in cpv_prefix.keys()}

        self.add_pvs(hwi_pvs)
        self.add_pvs(blv_pvs)
        self.add_pvs(cpv_pvs)

        self.add_pvs({"ALRM:SYS0:": WatcherPV(prefix="ALRM:SYS0:")})

    def get_cavity_ACTs_from_model(self):
        init_vals = {}
        self.cmd_socket.send_pyobj({"cmd": "tao",
                                    "val": "show lat -no_label_lines -attribute gradient -attribute phi0 -attribute is_on lcavity::* -no_slaves"})
        # self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show lat -no_label_lines -attribute gradient_err -attribute phi0_err -attribute rf_frequency -attribute is_on -attribute alias lcavity::*"})
        '''
        cav_pvs = {}
        cm_pvs = {}
        for device_name in init_vals.keys():
            cav_pvs[device_name] = CavityPV(self.on_cavity_change,
                                            initial_values=init_vals[device_name],
                                            prefix=device_name)
            cryomodulePrefixes.add(device_name[:-2] + "00")

        for prefix in cryomodulePrefixes:
            cm_pvs[prefix] = CryomodulePV(prefix=prefix)
            '''
        '''
        self.add_pvs(cav_pvs)
        self.add_pvs(cm_pvs)
        print("Initialization complete.") '''

        '''    def get_cavity_ACTs_from_model(self):

        queryString = "show lat -no_label_lines -attribute {joinedKeys} lcavity::* -no_slaves"

        self.cmd_socket.send_pyobj({"cmd": "tao",
                                    "val": queryString.format(
                                            joinedKeys=" -attribute ".join(taoAttributeTypeMap.keys()))})
                                            '''
        table = self.cmd_socket.recv_pyobj()['result']
        ''' The following section adds aliases to each row'''
        '''
        index = 0
        for row in table:
            if (row.find('ACCL:') == -1) and (row.find('TCAV:') == -1):
                elemName = table[index].split()[1]
                table[index] = row + "  NoAliasFor|" + elemName
                index += 1
            else:
                index += 1
        '''

        '''End of adding aliases. The "NoAlias" section was needed
        because not every element has an alias, and we need a dummy
        string in place of it so that the return statement in 
        _parse_cav_table finds the same # of elements in each row'''
        init_vals = _parse_cav_table(table)

        if DEBUG:
            print(init_vals)

        return init_vals

    def on_cavity_change(self, cavity_pv, value, parameter):
        element = cavity_pv.element_name
        if parameter == "PREF":
            return
        elif parameter == "PDES":
            cav_attr = "phi0_err";
            cavity_pv.phas._data['value'] = value;
            value = (value - cavity_pv.pdes_i - cavity_pv.pref._data['value']) / 360.0;
        elif parameter == "GDES":
            value = (value - cavity_pv.gdes_i) * 1e6
            cav_attr = "gradient_err";
        elif parameter == "SSA_ON":
            cav_attr = "is_on";
            value = 'T' if value is 'ON' else 'F'

        cmd = f'set ele {element} {cav_attr} = {value}'
        # L.info(cmd)
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": cmd})
        msg = self.cmd_socket.recv_pyobj()['result']
        # L.info(msg)


def main():
    service = CavityService()
    asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix='',
        desc="Simulated CM Cavity Service")
    run(service, **run_options)


if __name__ == '__main__':
    main()
