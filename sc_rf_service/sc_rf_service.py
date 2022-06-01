from asyncio import sleep

import asyncio
from caproto import ChannelEnum, ChannelInteger, ChannelType
from caproto.server import (PVGroup, PvpropertyChar, PvpropertyEnum,
                            PvpropertyEnumRO, PvpropertyFloat, PvpropertyFloatRO, PvpropertyString,
                            ioc_arg_parser, pvproperty, run)
from random import random

from lcls_tools.superconducting.scLinac import L1BHL, LINAC_TUPLES
from simulacrum import Service


class HWIPVGroup(PVGroup):
    hwi = pvproperty(value=0, name="HWINITSUM", dtype=ChannelType.ENUM,
                     enum_strings=("Ok", "HW Init running", "LLRF chassis problem"))
    fro = pvproperty(value=0, name="FREQSUM", dtype=ChannelType.ENUM,
                     enum_strings=("OK", "Still OK", "Faulted"))


class BeamlineVacuumPVGroup(PVGroup):
    rackA = pvproperty(value=0, name="BMLNVACA_LTCH", dtype=ChannelType.ENUM,
                       enum_strings=("Ok", "Fault"))
    rackB = pvproperty(value=0, name="BMLNVACB_LTCH", dtype=ChannelType.ENUM,
                       enum_strings=("Ok", "Fault"))


class CouplerVacuumPVGroup(PVGroup):
    rackA = pvproperty(value=0, name=":CPLRVACA_LTCH", dtype=ChannelType.ENUM,
                       enum_strings=("Ok", "Fault"))
    rackB = pvproperty(value=0, name=":CPLRVACB_LTCH", dtype=ChannelType.ENUM,
                       enum_strings=("Ok", "Fault"))


class StepperPVGroup(PVGroup):
    move_pos = pvproperty(name="MOV_REQ_POS")
    move_neg = pvproperty(name="MOV_REQ_NEG")
    abort = pvproperty(name="ABORT_REQ")
    step_des = pvproperty(name="NSTEPS")
    max_steps = pvproperty(name="NSTEPS.DRVH")
    speed = pvproperty(name="VELO")
    step_tot = pvproperty(name="REG_TOTABS")
    step_signed = pvproperty(name="REG_TOTSGN")
    reset_tot = pvproperty(name="TOTABS_RESET")
    reset_signed = pvproperty(name="TOTSGN_RESET")
    steps_cold_landing = pvproperty(name="NSTEPS_COLD")
    push_signed_cold = pvproperty(name="PUSH_NSTEPS_COLD.PROC")
    push_signed_park = pvproperty(name="PUSH_NSTEPS_PARK.PROC")
    motor_moving = pvproperty(name="STAT_MOV")
    motor_done = pvproperty(name="STAT_DONE")


class PiezoPVGroup(PVGroup):
    enable = pvproperty(name="ENABLE")
    feedback_mode = pvproperty(value=1, name="MODECTRL",
                               dtype=ChannelType.ENUM,
                               enum_strings=("Manual", "Feedback"))
    dc_setpoint = pvproperty(name="DAC_SP")
    bias_voltage = pvproperty(name="BIAS")
    prerf_test_start = pvproperty(name="TESTSTRT")
    prerf_cha_status = pvproperty(name="CHA_TESTSTAT")
    prerf_chb_status = pvproperty(name="CHB_TESTSTAT")
    prerf_cha_testmsg = pvproperty(name="CHA_TESTMSG1")
    prerf_chb_testmsg = pvproperty(name="CHA_TESTMSG2")
    capacitance_a = pvproperty(name="CHA_C")
    capacitance_b = pvproperty(name="CHB_C")
    prerf_test_status: PvpropertyEnum = pvproperty(name="TESTSTS",
                                                   dtype=ChannelType.ENUM,
                                                   value=0,
                                                   enum_strings=("", "Complete",
                                                                 "Running"))
    
    withrf_run_check = pvproperty(name="RFTESTSTRT")
    withrf_check_status = pvproperty(name="RFTESTSTS")
    withrf_status = pvproperty(name="RFSTESTSTAT")
    amplifiergain_a = pvproperty(name="CHA_AMPGAIN")
    amplifiergain_b = pvproperty(name="CHB_AMPGAIN")
    withrf_push_dfgain = pvproperty(name="PUSH_DFGAIN.PROC")
    withrf_save_dfgain = pvproperty(name="SAVE_DFGAIN.PROC")
    detunegain_new = pvproperty(name="DFGAIN_NEW")
    hardware_sum = pvproperty(value=0, name="HWSTATSUM", dtype=ChannelType.ENUM,
                              enum_strings=("", "", "Fault"))
    feedback_sum = pvproperty(value=0, name="FBSTATSUM",
                              dtype=ChannelType.ENUM,
                              enum_strings=("", "", "Fault"))
    
    @prerf_test_start.putter
    async def prerf_test_start(self, instance, value):
        await self.prerf_test_status.write("Running")
        await sleep(5)
        await self.prerf_test_status.write("Complete")


class CavFaultPVGroup(PVGroup):
    cryoSummary: PvpropertyEnum = pvproperty(value=0, name="CRYO_LTCH",
                                             dtype=ChannelType.ENUM,
                                             enum_strings=("Ok", "Fault"))
    resLinkLatch: PvpropertyEnum = pvproperty(value=0, name="RESLINK_LTCH",
                                              dtype=ChannelType.ENUM,
                                              enum_strings=("OK", "Fault"))
    pllLatch: PvpropertyEnum = pvproperty(value=0, name="PLL_LTCH",
                                          dtype=ChannelType.ENUM,
                                          enum_strings=("Ok", "Fault"))
    pllFault: PvpropertyEnum = pvproperty(value=0, name="PLL_FLT",
                                          dtype=ChannelType.ENUM,
                                          enum_strings=("Ok", "Fault"))
    iocWatchdogLatch: PvpropertyEnum = pvproperty(value=0, name="IOCWDOG_LTCH",
                                                  dtype=ChannelType.ENUM,
                                                  enum_strings=("OK", "Fault"))
    couplerTemp1Latch: PvpropertyEnum = pvproperty(value=0, name="CPLRTEMP1_LTCH",
                                                   dtype=ChannelType.ENUM,
                                                   enum_strings=("Ok", "Fault"))
    couplerTemp2Latch: PvpropertyEnum = pvproperty(value=0, name="CPLRTEMP2_LTCH",
                                                   dtype=ChannelType.ENUM,
                                                   enum_strings=("Ok", "Faulted"))
    stepperTempLatch: PvpropertyEnum = pvproperty(value=0, name="STEPTEMP_LTCH",
                                                  dtype=ChannelType.ENUM,
                                                  enum_strings=("Ok", "Fault"))
    quenchLatch: PvpropertyEnum = pvproperty(value=0, name="QUENCH_LTCH",
                                             dtype=ChannelType.ENUM,
                                             enum_strings=("Ok", "Fault"))
    resChasSum: PvpropertyEnum = pvproperty(value=0, name="RESINTLK_LTCH",
                                            dtype=ChannelType.ENUM,
                                            enum_strings=("Ok", "Fault"))
    cavityController: PvpropertyEnum = pvproperty(value=0, name="CTRL_SUM.SEVR",
                                                  dtype=ChannelType.ENUM,
                                                  enum_strings=("NO_ALARM",
                                                                "MINOR",
                                                                "MAJOR",
                                                                "INVALID"))
    
    ampFeedbackSum: PvpropertyEnum = pvproperty(value=0, name="AMPFB_SUM",
                                                dtype=ChannelType.ENUM,
                                                enum_strings=("Not clipped",
                                                              "Clipped RF-only mode",
                                                              "Clipped beam mode"))
    phaseFeedbackSum: PvpropertyEnum = pvproperty(value=0, name="PHAFB_SUM",
                                                  dtype=ChannelType.ENUM,
                                                  enum_strings=("Not clipped",
                                                                "Clipped RF-only mode",
                                                                "Clipped beam mode"))
    feedbackSum: PvpropertyEnum = pvproperty(value=0, name="FB_SUM",
                                             dtype=ChannelType.ENUM,
                                             enum_strings=("Not clipped",
                                                           "Clipped RF-only mode",
                                                           "Clipped beam mode"))


class CavityPVGroup(PVGroup):
    ades: PvpropertyFloat = pvproperty(value=16.6, name='ADES', precision=1)
    aact: PvpropertyFloatRO = pvproperty(value=16.6, name='AACT',
                                         read_only=True, precision=1)
    amean: PvpropertyFloatRO = pvproperty(value=16.6, name='AACTMEAN',
                                          read_only=True, precision=1)
    gdes: PvpropertyFloat = pvproperty(value=16.0, name='GDES', precision=1)
    gact: PvpropertyFloatRO = pvproperty(value=16.0, name='GACT',
                                         read_only=True, precision=1)
    rf_state_des: PvpropertyEnum = pvproperty(value=1, name='RFCTRL',
                                              dtype=ChannelType.ENUM,
                                              enum_strings=("Off", "On"))
    # Defaults to pulse
    rf_mode_des: PvpropertyEnum = pvproperty(value=4, name='RFMODECRTL',
                                             dtype=ChannelType.ENUM,
                                             enum_strings=("SELAP", "SELA",
                                                           "SEL", "SEL Raw",
                                                           "Pulse", "Chirp"))
    # Defaults to on
    rf_state_act: PvpropertyEnumRO = pvproperty(value=1, name='RFSTATE',
                                                dtype=ChannelType.ENUM,
                                                enum_strings=("Off", "On"),
                                                read_only=True)
    # Defaults to pulse
    rf_mode_act: PvpropertyEnumRO = pvproperty(value=4, name='RFMODE',
                                               dtype=ChannelType.ENUM,
                                               enum_strings=("SELAP", "SELA",
                                                             "SEL", "SEL Raw",
                                                             "Pulse", "Chirp"),
                                               read_only=True)
    adesMax: PvpropertyFloat = pvproperty(value=21, name="ADES_MAX_SRF",
                                          dtype=ChannelType.FLOAT)
    
    pdes: PvpropertyFloat = pvproperty(value=0.0, name='PDES')
    pmean: PvpropertyFloat = pvproperty(value=0.0, name='PMEAN')
    pact: PvpropertyFloatRO = pvproperty(value=0.0, name='PACT', read_only=True)
    rfPermit: PvpropertyEnum = pvproperty(value=1, name="RFPERMIT",
                                          dtype=ChannelType.ENUM,
                                          enum_strings=("RF inhibit",
                                                        "RF allow"))
    rf_ready_for_beam: PvpropertyEnum = pvproperty(value=1, name="RFREADYFORBEAM",
                                                   dtype=ChannelType.ENUM,
                                                   enum_strings=("Not Ready",
                                                                 "Ready"))
    parked: PvpropertyEnum = pvproperty(value=0, name="PARK",
                                        dtype=ChannelType.ENUM,
                                        enum_strings=("Not parked", "Parked"))
    
    # Cavity Summary Display PVs
    cudStatus: PvpropertyString = pvproperty(value="TLC", name="CUDSTATUS",
                                             dtype=ChannelType.STRING)
    cudSevr: PvpropertyEnum = pvproperty(value=1, name="CUDSEVR",
                                         dtype=ChannelType.ENUM,
                                         enum_strings=("NO_ALARM", "MINOR",
                                                       "MAJOR", "INVALID",
                                                       "PARKED"))
    cudDesc: PvpropertyChar = pvproperty(value="Name", name="CUDDESC",
                                         dtype=ChannelType.CHAR)
    
    def __init__(self, prefix, length):
        
        super().__init__(prefix)
        self.length = length
    
    @ades.putter
    async def ades(self, instance, value):
        await self.aact.write(value)
        await self.amean.write(value)
        gradient = value / self.length
        if self.gact.value != gradient:
            await self.gdes.write(gradient)
    
    @pdes.putter
    async def pdes(self, instance, value):
        value = value % 360
        await self.pact.write(value)
        await self.pmean.write(value)
    
    @gdes.putter
    async def gdes(self, instance, value):
        await self.gact.write(value)
        amplitude = value * self.length
        if self.aact.value != amplitude:
            await self.ades.write(amplitude)
    
    @rf_state_des.putter
    async def rf_state_des(self, instance, value):
        if value == "Off":
            await self.power_off()
        elif value == "On":
            await self.power_on()
    
    @rf_mode_des.putter
    async def rf_mode_des(self, instance, value):
        await self.rf_mode_act.write(value)
    
    async def power_off(self):
        await self.amean.write(0)
        await self.aact.write(0)
        await self.gact.write(0)
        await self.rf_state_act.write("Off")
    
    async def power_on(self):
        await self.aact.write(self.ades.value)
        await self.amean.write(self.ades.value)
        await self.gact.write(self.gdes.value)
        await self.rf_state_act.write("On")


class SSAPVGroup(PVGroup):
    on: PvpropertyEnum = pvproperty(value=1, name='PowerOn',
                                    dtype=ChannelType.ENUM,
                                    enum_strings=("False", "True"))
    off: PvpropertyEnum = pvproperty(value=0, name='PowerOff',
                                     dtype=ChannelType.ENUM,
                                     enum_strings=("False", "True"))
    alarm_sum: PvpropertyEnum = pvproperty(value=0, name="AlarmSummary.SEVR",
                                           dtype=ChannelType.ENUM,
                                           enum_strings=("NO_ALARM", "MINOR",
                                                         "MAJOR", "INVALID"))
    latch: PvpropertyEnum = pvproperty(value=1, name=":SSA_LTCH",
                                       dtype=ChannelType.ENUM,
                                       enum_strings=("OK", "Fault"))
    
    status_msg: PvpropertyEnum = pvproperty(value=0, name='StatusMsg',
                                            dtype=ChannelType.ENUM,
                                            enum_strings=("Unknown", "Faulted",
                                                          "SSA Off",
                                                          "SSA On",
                                                          "Resetting Faults...",
                                                          "Powering ON...",
                                                          "Powering Off...",
                                                          "Fault Reset Failed...",
                                                          "Power On Failed...",
                                                          "Power Off Failed...",
                                                          "Rebooting SSA...",
                                                          "Rebooting X-Port...",
                                                          "Resetting Processor..."))
    
    cal_start: PvpropertyEnum = pvproperty(value=0, name="CALSTRT",
                                           dtype=ChannelType.ENUM,
                                           enum_strings=("Start", "Start"))
    cal_status: PvpropertyEnum = pvproperty(value=1, name="CALSTS",
                                            dtype=ChannelType.ENUM,
                                            enum_strings=("Running",
                                                          "Complete"))
    cal_stat: PvpropertyEnum = pvproperty(value=0, dtype=ChannelType.ENUM,
                                          name="CALSTAT",
                                          enum_strings=("Success", "Crash"))
    slope_old: PvpropertyFloat = pvproperty(value=0.0, name="SLOPE",
                                            dtype=ChannelType.FLOAT)
    slope_new: PvpropertyFloat = pvproperty(value=0.0, name="SLOPE_NEW",
                                            dtype=ChannelType.FLOAT)
    
    def __init__(self, prefix, cavityGroup: CavityPVGroup):
        
        super().__init__(prefix)
        self.cavityGroup: CavityPVGroup = cavityGroup
    
    @cal_start.putter
    async def cal_start(self, instance, value):
        """
        Trying to simulate SSA Calibration with 20% chance of failing. Needs
        some work to make the PV enums are actually right
        """
        await self.cal_status.write("Running")
        await sleep(5)
        await self.cal_status.write("Complete")
        if random() < .2:
            await self.cal_stat.write("Crash")
        else:
            await self.cal_stat.write("Success")
    
    @on.putter
    async def on(self, instance, value):
        if value == "True" and self.status_msg.value != "SSA On":
            print("Turning SSA on")
            await self.status_msg.write("Resetting Faults...")
            await self.status_msg.write("Powering ON...")
            await self.status_msg.write("SSA On")
            print(self.status_msg.value)
            await self.off.write("False")
            if self.cavityGroup.rf_state_des.value == "On":
                await self.cavityGroup.power_on()
    
    @off.putter
    async def off(self, instance, value):
        if value == "True" and self.status_msg.value != "SSA Off":
            print("Turning SSA off")
            await self.status_msg.write("Powering Off...")
            await self.status_msg.write("SSA Off")
            print(self.status_msg.value)
            await self.on.write("False")
            await self.cavityGroup.power_off()


class CavityService(Service):
    def __init__(self):
        super().__init__()
        self["PHYS:SYS0:1:SC_CAV_FAULT_HEARTBEAT"] = ChannelInteger(value=0)
        
        self["ALRM:SYS0:SC_CAV_FAULT:ALHBERR"] = ChannelEnum(enum_strings=("RUNNING",
                                                                           "NOT_RUNNING",
                                                                           "INVALID"),
                                                             value=0)
        
        rackA = range(1, 5)
        
        for linac_name, cm_list in LINAC_TUPLES:
            if linac_name == "L1B":
                cm_list += L1BHL
            for cm_name in cm_list:
                
                if cm_name in L1BHL:
                    length = 0.346
                else:
                    length = 1.038
                
                for cav_num in range(1, 9):
                    cm_prefix = f"ACCL:{linac_name}:{cm_name}"
                    cav_prefix = cm_prefix + f"{cav_num}0:"
                    
                    cavityGroup = CavityPVGroup(prefix=cav_prefix, length=length)
                    self.add_pvs(cavityGroup)
                    self.add_pvs(SSAPVGroup(prefix=cav_prefix + "SSA:",
                                            cavityGroup=cavityGroup))
                    
                    self.add_pvs(PiezoPVGroup(prefix=cav_prefix + "PZT:"))
                    self.add_pvs(StepperPVGroup(prefix=cav_prefix + "STEP:"))
                    self.add_pvs(CavFaultPVGroup(prefix=cav_prefix))
                    
                    # Rack PVs are stupidly inconsistent
                    if cav_num in rackA:
                        hwi_prefix = cm_prefix + "00:RACKA:"
                    else:
                        hwi_prefix = cm_prefix + "00:RACKB:"
                    
                    self.add_pvs(HWIPVGroup(prefix=hwi_prefix))
                    self.add_pvs(BeamlineVacuumPVGroup(prefix=cm_prefix + "00:"))
                    self.add_pvs(CouplerVacuumPVGroup(prefix=cm_prefix + "10:"))


def main():
    service = CavityService()
    asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
            default_prefix='',
            desc="Simulated CM Cavity Service")
    run(service, **run_options)


if __name__ == '__main__':
    main()
