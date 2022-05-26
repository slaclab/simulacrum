import asyncio
from caproto import ChannelEnum, ChannelInteger, ChannelType
from caproto.server import PVGroup, PvpropertyEnum, PvpropertyFloat, PvpropertyFloatRO, ioc_arg_parser, pvproperty, run

from lcls_tools.superconducting.scLinac import L1BHL, LINAC_TUPLES
from simulacrum import Service


class CryomodulePVGroup(PVGroup):
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
    prerf_test_status = pvproperty(name="TESTSTS")
    
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


class CavityPVGroup(PVGroup):
    ades: PvpropertyFloat = pvproperty(value=16.6, name='ADES', precision=1)
    aact: PvpropertyFloatRO = pvproperty(value=16.6, name='AACT', read_only=True, precision=1)
    amean: PvpropertyFloatRO = pvproperty(value=16.6, name='AACTMEAN', read_only=True, precision=1)
    gdes = pvproperty(value=16.0, name='GDES', precision=1)
    gact = pvproperty(value=16.0, name='GACT', read_only=True, precision=1)
    
    cudStatus = pvproperty(value="TLC", name="CUDSTATUS", dtype=ChannelType.STRING)
    cudSevr = pvproperty(value=1, name="CUDSEVR", dtype=ChannelType.ENUM,
                         enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID",
                                       "PARKED"))
    cudDesc = pvproperty(value="Name", name="CUDDESC", dtype=ChannelType.CHAR)
    
    cryoSummary = pvproperty(value=0, name="CRYO_LTCH", dtype=ChannelType.ENUM,
                             enum_strings=("Ok", "Fault"))
    resLinkLatch = pvproperty(value=0, name="RESLINK_LTCH",
                              dtype=ChannelType.ENUM, enum_strings=("OK", "Fault"))
    pllLatch = pvproperty(value=0, name="PLL_LTCH", dtype=ChannelType.ENUM,
                          enum_strings=("Ok", "Fault"))
    pllFault = pvproperty(value=0, name="PLL_FLT", dtype=ChannelType.ENUM,
                          enum_strings=("Ok", "Fault"))
    iocWatchdogLatch = pvproperty(value=0, name="IOCWDOG_LTCH",
                                  dtype=ChannelType.ENUM,
                                  enum_strings=("OK", "Fault"))
    couplerTemp1Latch = pvproperty(value=0, name="CPLRTEMP1_LTCH",
                                   dtype=ChannelType.ENUM,
                                   enum_strings=("Ok", "Fault"))
    couplerTemp2Latch = pvproperty(value=0, name="CPLRTEMP2_LTCH",
                                   dtype=ChannelType.ENUM,
                                   enum_strings=("Ok", "Faulted"))
    stepperTempLatch = pvproperty(value=0, name="STEPTEMP_LTCH",
                                  dtype=ChannelType.ENUM,
                                  enum_strings=("Ok", "Fault"))
    quenchLatch = pvproperty(value=0, name="QUENCH_LTCH", dtype=ChannelType.ENUM,
                             enum_strings=("Ok", "Fault"))
    resonanceChassisSummary = pvproperty(value=0, name="RESINTLK_LTCH", dtype=ChannelType.ENUM,
                                         enum_strings=("Ok", "Fault"))
    rfPermit = pvproperty(value=1, name="RFPERMIT", dtype=ChannelType.ENUM,
                          enum_strings=("RF inhibit", "RF allow"))
    cavityController = pvproperty(value=0, name="CTRL_SUM.SEVR", dtype=ChannelType.ENUM,
                                  enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID"))
    rfReadyForBeam = pvproperty(value=1, name="RFREADYFORBEAM", dtype=ChannelType.ENUM,
                                enum_strings=("Not Ready", "Ready"))
    
    ampFeedbackSum = pvproperty(value=0, name="AMPFB_SUM", dtype=ChannelType.ENUM,
                                enum_strings=("Not clipped", "Clipped RF-only mode",
                                              "Clipped beam mode"))
    phaseFeedbackSum = pvproperty(value=0, name="PHAFB_SUM", dtype=ChannelType.ENUM,
                                  enum_strings=("Not clipped", "Clipped RF-only mode",
                                                "Clipped beam mode"))
    feedbackSum = pvproperty(value=0, name="FB_SUM", dtype=ChannelType.ENUM,
                             enum_strings=("Not clipped", "Clipped RF-only mode",
                                           "Clipped beam mode"))
    parked = pvproperty(value=0, name="PARK", dtype=ChannelType.ENUM,
                        enum_strings=("Not parked", "Parked"))
    rfState_Des = pvproperty(value=1, name='RFCTRL', dtype=ChannelType.ENUM,
                             enum_strings=("Off", "On"))
    # Defaults to pulse
    rfMode_Des = pvproperty(value=4, name='RFMODECRTL', dtype=ChannelType.ENUM,
                            enum_strings=("SELAP", "SELA", "SEL", "SEL Raw",
                                          "Pulse", "Chirp"))
    # Defaults to on
    rfState_Act = pvproperty(value=1, name='RFSTATE', dtype=ChannelType.ENUM,
                             enum_strings=("Off", "On"))
    # Defaults to pulse
    rfMode_Act = pvproperty(value=4, name='RFMODE', dtype=ChannelType.ENUM,
                            enum_strings=("SELAP", "SELA", "SEL", "SEL Raw",
                                          "Pulse", "Chirp"))
    adesMax = pvproperty(value=21, name="ADES_MAX_SRF", dtype=ChannelType.FLOAT)
    
    pdes = pvproperty(value=0.0, name='PDES')
    pmean = pvproperty(value=0.0, name='PMEAN')
    pact = pvproperty(value=0.0, name='PACT')


class SSAPVGroup(PVGroup):
    on: PvpropertyEnum = pvproperty(value=1, name='PowerOn', dtype=ChannelType.ENUM,
                                    enum_strings=("False", "True"))
    off: PvpropertyEnum = pvproperty(value=0, name='PowerOff', dtype=ChannelType.ENUM,
                                     enum_strings=("False", "True"))
    alarm_sum: PvpropertyEnum = pvproperty(value=0, name="AlarmSummary.SEVR",
                                           dtype=ChannelType.ENUM,
                                           enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID"))
    latch: PvpropertyEnum = pvproperty(value=1, name=":SSA_LTCH", dtype=ChannelType.ENUM,
                                       enum_strings=("OK", "Fault"))
    
    status_msg: PvpropertyEnum = pvproperty(value=0, name='StatusMsg', dtype=ChannelType.ENUM,
                                            enum_strings=("Unknown", "Faulted", "SSA Off",
                                                          "SSA On", "Resetting Faults...",
                                                          "Powering ON...", "Powering Off...",
                                                          "Fault Reset Failed...",
                                                          "Power On Failed...",
                                                          "Power Off Failed...",
                                                          "Rebooting SSA...",
                                                          "Rebooting X-Port...",
                                                          "Resetting Processor..."))
    
    cal_start = pvproperty(value=0, name="CALSTRT")
    cal_status: PvpropertyEnum = pvproperty(value=1, name="CALSTS", dtype=ChannelType.ENUM,
                                            enum_strings=("Running", "Complete"))
    cal_stat: PvpropertyEnum = pvproperty(value=0, dtype=ChannelType.ENUM, name="CALSTAT",
                                          enum_strings=("Success", "Crash"))
    slope_old = pvproperty(value=0.0, name="SLOPE", dtype=ChannelType.FLOAT)
    slope_new = pvproperty(value=0.0, name="SLOPE_NEW", dtype=ChannelType.FLOAT)
    
    def __init__(self, prefix, cavityGroup: CavityPVGroup):
        
        super().__init__(prefix)
        self.cavityGroup: CavityPVGroup = cavityGroup
    
    @on.putter
    async def on(self, instance, value):
        if value == "True" and self.status_msg.value != "SSA On":
            print("Turning SSA on")
            await self.status_msg.write("Resetting Faults...")
            await self.status_msg.write("Powering ON...")
            await self.status_msg.write("SSA On")
            print(self.status_msg.value)
            await self.off.write("False")
            await self.cavityGroup.aact.write(self.cavityGroup.ades.value)
            await self.cavityGroup.amean.write(self.cavityGroup.ades.value)
            await self.cavityGroup.gact.write(self.cavityGroup.gdes.value)
    
    @off.putter
    async def off(self, instance, value):
        if value == "True" and self.status_msg.value != "SSA Off":
            print("Turning SSA off")
            await self.status_msg.write("Powering Off...")
            await self.status_msg.write("SSA Off")
            print(self.status_msg.value)
            await self.on.write("False")
            await self.cavityGroup.amean.write(0)
            await self.cavityGroup.aact.write(0)
            await self.cavityGroup.gact.write(0)


class CavityService(Service):
    def __init__(self):
        super().__init__()
        self["PHYS:SYS0:1:SC_CAV_FAULT_HEARTBEAT"] = ChannelInteger(value=0)
        
        self["ALRM:SYS0:SC_CAV_FAULT:ALHBERR"] = ChannelEnum(enum_strings=("RUNNING",
                                                                           "NOT_RUNNING",
                                                                           "INVALID"),
                                                             value=0)
        
        for linac_name, cm_list in LINAC_TUPLES:
            if linac_name == "L1B":
                cm_list += L1BHL
            for cm_name in cm_list:
                for cav_num in range(1, 9):
                    prefix = f"ACCL:{linac_name}:{cm_name}{cav_num}0:"
                    cavityGroup = CavityPVGroup(prefix=prefix)
                    self.add_pvs(cavityGroup)
                    self.add_pvs(SSAPVGroup(prefix=prefix + "SSA:",
                                            cavityGroup=cavityGroup))
                    self.add_pvs(PiezoPVGroup(prefix=prefix + "PZT:"))
                    self.add_pvs(StepperPVGroup(prefix=prefix + "STEP:"))


def main():
    service = CavityService()
    asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
            default_prefix='',
            desc="Simulated CM Cavity Service")
    run(service, **run_options)


if __name__ == '__main__':
    main()
