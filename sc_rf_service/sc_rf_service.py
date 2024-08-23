from asyncio import create_subprocess_exec, get_event_loop, sleep
from datetime import datetime
from random import random, randrange, uniform, randint
from typing import List

from caproto import ChannelEnum, ChannelFloat, ChannelInteger, ChannelType
from caproto.server import (
    PVGroup,
    PvpropertyBoolEnum,
    PvpropertyChar,
    PvpropertyDouble,
    PvpropertyEnum,
    PvpropertyEnumRO,
    PvpropertyFloat,
    PvpropertyFloatRO,
    PvpropertyInteger,
    PvpropertyString,
    ioc_arg_parser,
    pvproperty,
    run,
)
from lcls_tools.superconducting.sc_cavity import Cavity
from lcls_tools.superconducting.sc_linac import MACHINE
from lcls_tools.superconducting.sc_linac_utils import (
    ESTIMATED_MICROSTEPS_PER_HZ,
    L1BHL,
    LINAC_TUPLES,
    PIEZO_HZ_PER_VOLT, LINAC_CM_DICT,
)

from simulacrum import Service

class SeverityProp(pvproperty):
    def __init__(self, name, value, **cls_kwargs):
        super().__init__(
            name=name + ".SEVR",
            value=value,
            dtype=ChannelType.ENUM,
            enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID"),
            **cls_kwargs,
        )


class AutoSetupPVGroup(PVGroup):
    setup_start: PvpropertyBoolEnum = pvproperty(name="SETUPSTRT")
    setup_stop: PvpropertyBoolEnum = pvproperty(name="SETUPSTOP")
    setup_status: PvpropertyBoolEnum = pvproperty(name="SETUPSTS")
    setup_timestamp: PvpropertyBoolEnum = pvproperty(name="SETUPTS")

    ssa_cal: PvpropertyBoolEnum = pvproperty(name="SETUP_SSAREQ", value=True)
    tune: PvpropertyEnum = pvproperty(name="SETUP_TUNEREQ", value=True)
    cav_char: PvpropertyEnum = pvproperty(name="SETUP_CHARREQ", value=True)
    ramp: PvpropertyEnum = pvproperty(name="SETUP_RAMPREQ", value=True)

    off_start: PvpropertyBoolEnum = pvproperty(name="OFFSTRT")
    off_stop: PvpropertyBoolEnum = pvproperty(name="OFFSTOP")
    off_status: PvpropertyBoolEnum = pvproperty(name="OFFSTS")
    off_timestamp: PvpropertyBoolEnum = pvproperty(name="OFFTS")

    abort: PvpropertyEnum = pvproperty(
        name="ABORT",
        dtype=ChannelType.ENUM,
        enum_strings=("No abort request", "Abort request"),
    )

    def __init__(self, prefix: str, script_args: List[str] = None):
        super().__init__(prefix + "AUTO:")
        self.script_args = script_args

    def trigger_setup_script(self):
        raise NotImplementedError

    def trigger_shutdown_script(self):
        raise NotImplementedError

    @setup_start.putter
    async def setup_start(self, instance, value):
        await self.trigger_setup_script()

    @off_start.putter
    async def off_start(self, instance, value):
        await self.trigger_shutdown_script()


class AutoSetupCMPVGroup(AutoSetupPVGroup):
    def __init__(self, prefix: str, cm_name: str):
        super().__init__(prefix)
        self.cm_name: str = cm_name

    async def trigger_setup_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_cm_setup_launcher.py",
            f"-cm={self.cm_name}",
        )

    async def trigger_shutdown_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_cm_setup_launcher.py",
            f"-cm={self.cm_name}",
            "-off",
        )


class AutoSetupLinacPVGroup(AutoSetupPVGroup):
    def __init__(self, prefix: str, linac_idx: int):
        super().__init__(prefix)
        self.linac_idx: int = linac_idx

    async def trigger_setup_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_linac_setup_launcher.py",
            f"-cm={self.linac_idx}",
        )

    async def trigger_shutdown_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_linac_setup_launcher.py",
            f"-cm={self.linac_idx}",
            "-off",
        )


class AutoSetupGlobalPVGroup(AutoSetupPVGroup):
    def __init__(self, prefix: str):
        super().__init__(prefix)

    async def trigger_setup_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_global_setup_launcher.py",
        )

    async def trigger_shutdown_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_global_setup_launcher.py",
            "-off",
        )


class AutoSetupCavityPVGroup(AutoSetupPVGroup):
    progress: PvpropertyFloat = pvproperty(
        name="PROG", value=0.0, dtype=ChannelType.FLOAT
    )
    status_sevr: SeverityProp = SeverityProp(name="STATUS", value=0)
    status: PvpropertyEnum = pvproperty(
        name="STATUS",
        dtype=ChannelType.ENUM,
        enum_strings=("Ready", "Running", "Error"),
    )
    status_message: PvpropertyChar = pvproperty(
        name="MSG", value="Ready", dtype=ChannelType.CHAR
    )

    time_stamp: PvpropertyChar = pvproperty(
        name="TS",
        value=datetime.now().strftime("%m/%d/%y %H:%M:%S.%f"),
        dtype=ChannelType.CHAR,
    )
    setup_stop: PvpropertyBoolEnum = pvproperty(name="SETUPSTOP")

    ssa_cal: PvpropertyBoolEnum = pvproperty(name="SETUP_SSAREQ")
    tune: PvpropertyEnum = pvproperty(name="SETUP_TUNEREQ")
    cav_char: PvpropertyEnum = pvproperty(name="SETUP_CHARREQ")
    ramp: PvpropertyEnum = pvproperty(name="SETUP_RAMPREQ")

    def __init__(self, prefix: str, cm_name: str, cav_num: int):
        super().__init__(prefix)
        self.cm_name: str = cm_name
        self.cav_num: int = cav_num

    @status.putter
    async def status(self, instance, value):
        if isinstance(value, int):
            await self.status_sevr.write(value)
        else:
            await self.status_sevr.write(["Ready", "Running", "Error"].index(value))

    async def trigger_setup_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_cavity_setup_launcher.py",
            f"-cm={self.cm_name}",
            f"-cav={self.cav_num}",
        )

    async def trigger_shutdown_script(self):
        process = await create_subprocess_exec(
            "python",
            "/Users/soham/srf_auto_setup/srf_cavity_setup_launcher.py",
            f"-cm={self.cm_name}",
            f"-cav={self.cav_num}",
            "-off",
        )

class LiquidLevelPVGroup(PVGroup):
    upstream = pvproperty(name="2601:US:LVL", value=75.0)
    downstream = pvproperty(name="2301:DS:LVL", value=93.0)


class JTPVGroup(PVGroup):
    readback = pvproperty(name="ORBV", value=30.0)
    ds_setpoint = pvproperty(name="SP_RQST", value=30.0)
    manual = pvproperty(name="MANUAL", value=0)
    auto = pvproperty(name="AUTO", value=0)
    mode = pvproperty(name="MODE", value=0)
    man_pos = pvproperty(name="MANPOS_RQST", value=40.0)
    mode_string: PvpropertyString = pvproperty(name="MODE_STRING", value="AUTO")

    def __init__(self, prefix, ll_group: LiquidLevelPVGroup, cm_group):
        super().__init__(prefix)

        self.ll_group = ll_group
        self.cm_group = cm_group
        self.stable_value = self.cm_group.total_heat(on_start=True)

    @man_pos.putter
    async def man_pos(self, instance, value):
        await self.readback.write(value)
        self.stable_value = self.cm_group.total_heat()
        if value * 1.1 > self.stable_value:
            while self.man_pos.value * 1.1 > value:
                curr = self.ll_group.downstream.value
                await self.ll_group.downstream.write(curr - 0.01)
                await sleep(1)
        elif value * 0.9 < self.stable_value:
            while self.man_pos.value * 0.9 < value:
                curr = self.ll_group.downstream.value
                await self.ll_group.downstream.write(curr + 0.01)
                await sleep(1)


class HeaterPVGroup(PVGroup):
    setpoint = pvproperty(name="MANPOS_RQST", value=24.0)
    readback = pvproperty(name="ORBV", value=24.0)
    mode = pvproperty(name="Mode", value=1)
    mode_string: PvpropertyString = pvproperty(name="MODE_STRING", value="SEQUENCER")
    manual: PvpropertyBoolEnum = pvproperty(name="MANUAL")
    sequencer: PvpropertyBoolEnum = pvproperty(name="SEQUENCER")

    def __init__(self, prefix, jt_group: JTPVGroup, cm_group):
        super().__init__(prefix)
        self.jt_group = jt_group
        self.cm_group = cm_group

    @manual.putter
    async def manual(self, instance, value):
        if value == 1:
            await self.mode.write(0)
            await self.mode_string.write("MANUAL")

    @sequencer.putter
    async def sequencer(self, instance, value):
        if value == 1:
            await self.mode.write(1)
            await self.mode_string.write("SEQUENCER")

    @setpoint.putter
    async def setpoint(self, instance, value):
        self.cm_group.heater_value = value
        self.jt_group.stable_value = self.cm_group.total_heat(heater_value=value)
        if self.jt_group.man_pos.value * 1.1 > self.jt_group.stable_value:
             while self.jt_group.man_pos.value * 1.1 > self.jt_group.stable_value:
                curr = self.jt_group.ll_group.downstream.value
                await self.jt_group.ll_group.downstream.write(curr - 0.01)
                await sleep(1)
        elif self.jt_group.man_pos.value * 0.9 < self.jt_group.stable_value:
            while self.jt_group.man_pos.value * 0.9 < self.jt_group.stable_value:
                curr = self.jt_group.ll_group.downstream.value
                await self.jt_group.ll_group.downstream.write(curr + 0.01)
                await sleep(1)

class CryomodulePVGroup(PVGroup):
    nrp = pvproperty(
        value=0, name="NRP:STATSUMY", dtype=ChannelType.DOUBLE, record="ai"
    )
    aact_mean_sum = pvproperty(value=0, name="AACTMEANSUM")
    # TODO - find this and see what type pv it is on bcs/ops_lcls2_bcs_main.edl
    bcs = pvproperty(value=0, name="BCSDRVSUM", dtype=ChannelType.DOUBLE)

    def __init__(self, prefix, cavities):

        super().__init__(prefix)
        self.cavities = cavities
        self.heater_value = 24.0

    def calc_rf_heat_load(self):
        rf_heat = 0
        for _, cavity in self.cavities.items():
            rf_heat += (cavity.aact.value * 1e6) ** 2 / (1012 * cavity.q0.value)
        return rf_heat

    def total_heat(self, on_start=False, heater_value=None):
        if heater_value:
            self.heater_value = heater_value
        total_heat = self.calc_rf_heat_load() + self.heater_value
        if not on_start:
            print(f'New JT stable position = Total Heat = {total_heat}')
        return total_heat

class CryoPVGroup(PVGroup):
    uhl = SeverityProp(name="LVL", value=0)


class HOMPVGroup(PVGroup):
    upstreamHOM = SeverityProp(value=0, name="18:UH:TEMP")
    downstreamHOM = SeverityProp(value=0, name="20:DH:TEMP")


class RACKPVGroup(PVGroup):
    hwi = pvproperty(
        value=0,
        name="HWINITSUM",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "HW Init running", "LLRF chassis problem"),
        record="mbbi",
    )
    fro = pvproperty(
        value=0,
        name="FREQSUM",
        dtype=ChannelType.ENUM,
        enum_strings=("OK", "Still OK", "Faulted"),
    )
    fscan_start = pvproperty(value=0, name="FSCAN:FREQ_START")
    fscan_stop = pvproperty(value=0, name="FSCAN:FREQ_STOP")
    fscan_thresh = pvproperty(value=0, name="FSCAN:RMS_THRESH")
    fscan_overlap = pvproperty(value=0, name="FSCAN:MODE_OVERLAP")
    prl = SeverityProp(value=0, name="PRLSUM")
    pjt: PvpropertyDouble = pvproperty(
        value=0, name="PRLJITSUM", dtype=ChannelType.DOUBLE
    )


class BeamlineVacuumPVGroup(PVGroup):
    rackA = pvproperty(
        value=0,
        name="BMLNVACA_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )
    rackB = pvproperty(
        value=0,
        name="BMLNVACB_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )


class CouplerVacuumPVGroup(PVGroup):
    rackA = pvproperty(
        value=0,
        name="CPLRVACA_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )
    rackB = pvproperty(
        value=0,
        name="CPLRVACB_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )


class StepperPVGroup(PVGroup):
    move_pos = pvproperty(name="MOV_REQ_POS")
    move_neg = pvproperty(name="MOV_REQ_NEG")
    abort = pvproperty(name="ABORT_REQ")
    step_des: PvpropertyInteger = pvproperty(value=0, name="NSTEPS")
    max_steps = pvproperty(name="NSTEPS.DRVH")
    speed: PvpropertyInteger = pvproperty(value=20000, name="VELO")
    step_tot: PvpropertyInteger = pvproperty(value=0, name="REG_TOTABS")
    step_signed: PvpropertyInteger = pvproperty(value=0, name="REG_TOTSGN")
    reset_tot = pvproperty(name="TOTABS_RESET")
    reset_signed = pvproperty(name="TOTSGN_RESET")
    steps_cold_landing = pvproperty(name="NSTEPS_COLD")
    nsteps_park = pvproperty(name="NSTEPS_PARK", value=5000000)
    push_signed_cold = pvproperty(name="PUSH_NSTEPS_COLD.PROC")
    push_signed_park = pvproperty(name="PUSH_NSTEPS_PARK.PROC")
    motor_moving: PvpropertyBoolEnum = pvproperty(
        value=0,
        name="STAT_MOV",
        enum_strings=("Not Moving", "Moving"),
        dtype=ChannelType.ENUM,
    )
    motor_done: PvpropertyBoolEnum = pvproperty(
        value=1,
        name="STAT_DONE",
        enum_strings=("Not Done", "Done"),
        dtype=ChannelType.ENUM,
    )
    hardware_sum = pvproperty(
        value=0,
        name="HWSTATSUM",
        dtype=ChannelType.ENUM,
        enum_strings=("", "", "Fault"),
    )
    limit_switch_a = pvproperty(
        value=0,
        name="STAT_LIMA",
        dtype=ChannelType.ENUM,
        enum_strings=("not at limit", "at limit"),
    )
    limit_switch_b = pvproperty(
        value=0,
        name="STAT_LIMB",
        dtype=ChannelType.ENUM,
        enum_strings=("not at limit", "at limit"),
    )
    hz_per_microstep = pvproperty(
        value=1 / ESTIMATED_MICROSTEPS_PER_HZ, name="SCALE", dtype=ChannelType.FLOAT
    )

    def __init__(self, prefix, cavity_group, piezo_group):
        super().__init__(prefix)
        self.cavity_group: CavityPVGroup = cavity_group
        self.piezo_group: PiezoPVGroup = piezo_group
        if not self.cavity_group.is_hl:
            self.steps_per_hertz = 256 / 1.4
        else:
            self.steps_per_hertz = 256 / 18.3

    async def move(self, move_sign_des: int):
        print("Motor moving")
        await self.motor_moving.write("Moving")
        steps = 0
        step_change = move_sign_des * self.speed.value
        freq_move_sign = move_sign_des if self.cavity_group.is_hl else -move_sign_des
        starting_detune = self.cavity_group.detune.value

        while self.step_des.value - steps >= self.speed.value and self.abort.value != 1:
            await self.step_tot.write(self.step_tot.value + self.speed.value)
            await self.step_signed.write(self.step_signed.value + step_change)

            steps += self.speed.value
            delta = self.speed.value // self.steps_per_hertz
            new_detune = self.cavity_group.detune.value + (freq_move_sign * delta)

            await self.cavity_group.detune.write(new_detune)
            await self.cavity_group.detune_rfs.write(new_detune)
            await sleep(1)

        if self.abort.value == 1:
            await self.motor_moving.write("Not Moving")
            await self.abort.write(0)
            return

        remainder = self.step_des.value - steps
        await self.step_tot.write(self.step_tot.value + remainder)
        step_change = move_sign_des * remainder
        await self.step_signed.write(self.step_signed.value + step_change)

        delta = remainder // self.steps_per_hertz
        new_detune = self.cavity_group.detune.value + (freq_move_sign * delta)

        print(f"Piezo feedback status: {self.piezo_group.feedback_mode_stat.value}")
        if (
            self.piezo_group.enable_stat.value == 1
            and self.piezo_group.feedback_mode_stat.value == "Feedback"
        ):
            freq_change = new_detune - starting_detune
            voltage_change = freq_change * (1 / PIEZO_HZ_PER_VOLT)
            print(f"Changing piezo voltage by {voltage_change} V")
            await self.piezo_group.voltage.write(
                self.piezo_group.voltage.value + voltage_change
            )
        await self.cavity_group.detune.write(new_detune)
        await self.cavity_group.detune_rfs.write(new_detune)

        await self.motor_moving.write("Not Moving")
        await self.motor_done.write("Done")

    @move_neg.putter
    async def move_neg(self, instance, value):
        await self.move(-1)

    @move_pos.putter
    async def move_pos(self, instance, value):
        await self.move(1)


class PiezoPVGroup(PVGroup):
    enable: PvpropertyEnum = pvproperty(name="ENABLE")
    enable_stat = pvproperty(
        name="ENABLESTAT",
        dtype=ChannelType.ENUM,
        value=1,
        enum_strings=("Disabled", "Enabled"),
    )
    feedback_mode = pvproperty(
        value=1,
        name="MODECTRL",
        dtype=ChannelType.ENUM,
        enum_strings=("Manual", "Feedback"),
    )
    feedback_mode_stat = pvproperty(
        name="MODESTAT",
        value=1,
        dtype=ChannelType.ENUM,
        enum_strings=("Manual", "Feedback"),
    )
    dc_setpoint = pvproperty(name="DAC_SP")
    bias_voltage = pvproperty(name="BIAS")
    prerf_test_start = pvproperty(name="TESTSTRT")
    prerf_cha_status = pvproperty(name="CHA_TESTSTAT")
    prerf_chb_status = pvproperty(name="CHB_TESTSTAT")
    prerf_cha_testmsg = pvproperty(name="CHA_TESTMSG1")
    prerf_chb_testmsg = pvproperty(name="CHA_TESTMSG2")
    capacitance_a = pvproperty(name="CHA_C")
    capacitance_b = pvproperty(name="CHB_C")
    prerf_test_status: PvpropertyEnum = pvproperty(
        name="TESTSTS",
        dtype=ChannelType.ENUM,
        value=0,
        enum_strings=("", "Complete", "Running"),
    )
    withrf_run_check = pvproperty(name="RFTESTSTRT")
    withrf_check_status: PvpropertyEnum = pvproperty(
        name="RFTESTSTS",
        dtype=ChannelType.ENUM,
        value=1,
        enum_strings=("", "Complete", "Running"),
    )
    withrf_status = pvproperty(name="RFSTESTSTAT")
    amplifiergain_a = pvproperty(name="CHA_AMPGAIN")
    amplifiergain_b = pvproperty(name="CHB_AMPGAIN")
    withrf_push_dfgain = pvproperty(name="PUSH_DFGAIN.PROC")
    withrf_save_dfgain = pvproperty(name="SAVE_DFGAIN.PROC")
    detunegain_new = pvproperty(name="DFGAIN_NEW")
    hardware_sum = pvproperty(
        value=0,
        name="HWSTATSUM",
        dtype=ChannelType.ENUM,
        enum_strings=("", "Minor Fault", "Fault"),
    )
    feedback_sum = pvproperty(
        value=0,
        name="FBSTATSUM",
        dtype=ChannelType.ENUM,
        enum_strings=("", "Minor Fault", "Fault"),
    )
    integrator_sp: PvpropertyFloat = pvproperty(
        name="INTEG_SP", value=0, dtype=ChannelType.FLOAT
    )

    voltage: PvpropertyInteger = pvproperty(name="V", value=17, dtype=ChannelType.INT)

    def __init__(self, prefix, cavity_group):
        super().__init__(prefix)
        self.cavity_group: CavityPVGroup = cavity_group

    @prerf_test_start.putter
    async def prerf_test_start(self, instance, value):
        await self.prerf_test_status.write("Running")
        await sleep(5)
        await self.prerf_test_status.write("Complete")

    @feedback_mode.putter
    async def feedback_mode(self, instance, value):
        await self.feedback_mode_stat.write(value)


class CavFaultPVGroup(PVGroup):
    prl_fault: SeverityProp = SeverityProp(name="PRLSUM", value=0)
    cryo_summary: PvpropertyEnum = pvproperty(
        value=0, name="CRYO_LTCH", dtype=ChannelType.ENUM, enum_strings=("Ok", "Fault")
    )
    res_link_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="RESLINK_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("OK", "Fault"),
    )
    pll_latch: PvpropertyEnum = pvproperty(
        value=0, name="PLL_LTCH", dtype=ChannelType.ENUM, enum_strings=("Ok", "Fault")
    )
    pll_fault: PvpropertyEnum = pvproperty(
        value=0, name="PLL_FLT", dtype=ChannelType.ENUM, enum_strings=("Ok", "Fault")
    )
    ioc_watchdog_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="IOCWDOG_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("OK", "Fault"),
    )
    coupler_temp1_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="CPLRTEMP1_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )
    coupler_temp2_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="CPLRTEMP2_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Faulted"),
    )
    stepper_temp_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="STEPTEMP_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )
    quench_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="QUENCH_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )
    res_chas_sum: PvpropertyEnum = pvproperty(
        value=0,
        name="RESINTLK_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("Ok", "Fault"),
    )
    cavity_controller: PvpropertyEnum = SeverityProp(
        value=0,
        name="CTRL_SUM",
    )

    amp_feedback_sum: PvpropertyEnum = pvproperty(
        value=0,
        name="AMPFB_SUM",
        dtype=ChannelType.ENUM,
        enum_strings=("Not clipped", "Clipped RF-only mode", "Clipped beam mode"),
    )
    phase_feedback_sum: PvpropertyEnum = pvproperty(
        value=0,
        name="PHAFB_SUM",
        dtype=ChannelType.ENUM,
        enum_strings=("Not clipped", "Clipped RF-only mode", "Clipped beam mode"),
    )
    feedback_sum: PvpropertyEnum = pvproperty(
        value=0,
        name="FB_SUM",
        dtype=ChannelType.ENUM,
        enum_strings=("Not clipped", "Clipped RF-only mode", "Clipped beam mode"),
    )
    cavity_characterization: PvpropertyEnum = pvproperty(
        value=0,
        name="CAV:CALSTATSUM",
        dtype=ChannelType.ENUM,
        enum_strings=("", "", "Fault"),
    )
    offline: PvpropertyEnum = pvproperty(
        name="HWMODE",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=("Online", "Maintenance", "Offline", "Maintenance Done", "Ready"),
    )
    check_phase: PvpropertyInteger = pvproperty(
        name="CKPSUM", value=0, dtype=ChannelType.INT
    )
    quench_interlock: PvpropertyEnum = pvproperty(
        name="QUENCH_BYP_RBV",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=("Not Bypassed", "Bypassed"),
    )
    amplitude_tol: PvpropertyEnum = SeverityProp(
        name="AACTMEAN",
        value=0,
    )
    phase_tol: PvpropertyEnum = SeverityProp(
        name="PACTMEAN",
        value=0,
    )
    local_oscillator: PvpropertyEnum = pvproperty(
        name="LO_LTCH", value=0, dtype=ChannelType.ENUM, enum_strings=("Ok", "Fault")
    )
    waveform_acquisition: PvpropertyDouble = pvproperty(
        name="WFACQSUM", value=0, dtype=ChannelType.DOUBLE
    )
    detune_feedback: PvpropertyDouble = pvproperty(
        name="FBSTATSUM", value=0, dtype=ChannelType.DOUBLE
    )


class CavityPVGroup(PVGroup):
    acon: PvpropertyFloat = pvproperty(value=16.6, name="ACON", precision=2)
    ades: PvpropertyFloat = pvproperty(value=16.6, name="ADES", precision=1)
    aact: PvpropertyFloatRO = pvproperty(
        value=16.6, name="AACT", read_only=True, precision=1
    )
    amean: PvpropertyFloatRO = pvproperty(
        value=16.6, name="AACTMEAN", read_only=True, precision=1
    )
    gdes: PvpropertyFloat = pvproperty(value=16.0, name="GDES", precision=1)
    gact: PvpropertyFloatRO = pvproperty(
        value=16.0, name="GACT", read_only=True, precision=1
    )
    rf_state_des: PvpropertyEnum = pvproperty(
        value=1, name="RFCTRL", dtype=ChannelType.ENUM, enum_strings=("Off", "On")
    )
    # Defaults to pulse
    rf_mode_des: PvpropertyEnum = pvproperty(
        value=4,
        name="RFMODECTRL",
        dtype=ChannelType.ENUM,
        enum_strings=("SELAP", "SELA", "SEL", "SEL Raw", "Pulse", "Chirp"),
    )
    # Defaults to on
    rf_state_act: PvpropertyEnumRO = pvproperty(
        value=1,
        name="RFSTATE",
        dtype=ChannelType.ENUM,
        enum_strings=("Off", "On"),
        read_only=False,
    )
    # Defaults to pulse
    rf_mode_act: PvpropertyEnumRO = pvproperty(
        value=0,
        name="RFMODE",
        dtype=ChannelType.ENUM,
        enum_strings=("SELAP", "SELA", "SEL", "SEL Raw", "Pulse", "Chirp"),
        read_only=True,
    )
    adesMaxSRF: PvpropertyFloat = pvproperty(
        value=21, name="ADES_MAX_SRF", dtype=ChannelType.FLOAT
    )
    adesMax: PvpropertyFloat = pvproperty(
        value=21, name="ADES_MAX", dtype=ChannelType.FLOAT
    )

    pdes: PvpropertyFloat = pvproperty(value=0.0, name="PDES")
    pmean: PvpropertyFloat = pvproperty(value=0.0, name="PMEAN")
    pact: PvpropertyFloatRO = pvproperty(value=0.0, name="PACT", read_only=True)
    rfPermit: PvpropertyEnum = pvproperty(
        value=1,
        name="RFPERMIT",
        dtype=ChannelType.ENUM,
        enum_strings=("RF inhibit", "RF allow"),
    )
    rf_ready_for_beam: PvpropertyEnum = pvproperty(
        value=1,
        name="RFREADYFORBEAM",
        dtype=ChannelType.ENUM,
        enum_strings=("Not Ready", "Ready"),
    )
    parked: PvpropertyEnum = pvproperty(
        value=0,
        name="PARK",
        dtype=ChannelType.ENUM,
        enum_strings=("Not parked", "Parked"),
        record="mbbi",
    )
    # Cavity Summary Display PVs
    cudStatus: PvpropertyString = pvproperty(
        value="TLC", name="CUDSTATUS", dtype=ChannelType.STRING
    )
    cudSevr: PvpropertyEnum = pvproperty(
        value=1,
        name="CUDSEVR",
        dtype=ChannelType.ENUM,
        enum_strings=(
            "NO_ALARM",
            "MINOR",
            "MAJOR",
            "INVALID",
            "MAINTENANCE",
            "OFFLINE",
            "READY",
        ),
    )
    cudDesc: PvpropertyChar = pvproperty(
        value="Name", name="CUDDESC", dtype=ChannelType.CHAR
    )
    ssa_latch: PvpropertyEnum = pvproperty(
        value=0,
        name="SSA_LTCH",
        dtype=ChannelType.ENUM,
        enum_strings=("OK", "Fault"),
        record="mbbi",
    )
    sel_aset: PvpropertyFloat = pvproperty(
        value=0.0, name="SEL_ASET", dtype=ChannelType.FLOAT
    )
    landing_freq = randrange(-10000, 10000)
    detune: PvpropertyInteger = pvproperty(
        value=landing_freq, name="DFBEST", dtype=ChannelType.INT
    )
    detune_rfs: PvpropertyInteger = pvproperty(
        value=landing_freq, name="DF", dtype=ChannelType.INT
    )
    tune_config: PvpropertyEnum = pvproperty(
        name="TUNE_CONFIG",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=("On resonance", "Cold landing", "Parked", "Other"),
    )
    df_cold: PvpropertyFloat = pvproperty(
        value=randint(-10000, 200000), name="DF_COLD", dtype=ChannelType.FLOAT
    )
    step_temp: PvpropertyFloat = pvproperty(
        value=35.0, name="STEPTEMP", dtype=ChannelType.FLOAT
    )

    fscan_stat: PvpropertyEnum = pvproperty(
        name="FSCAN:SEARCHSTAT",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=(
            "No errors",
            "None found",
            "Unknown mode",
            "Wrong freq",
            "Data nonsync",
        ),
    )
    fscan_sel: PvpropertyBoolEnum = pvproperty(
        name="FSCAN:SEL",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=("Not Selected", "Selected"),
    )
    fscan_res = pvproperty(name="FSCAN:8PI9MODE", value=-800000)
    chirp_start: PvpropertyInteger = pvproperty(name="CHIRP:FREQ_START", value=-200000)
    chirp_stop: PvpropertyInteger = pvproperty(name="CHIRP:FREQ_STOP", value=200000)
    qloaded_new = pvproperty(name="QLOADED_NEW", value=4e7)
    scale_new = pvproperty(name="CAV:CAL_SCALEB_NEW", value=30)
    quench_bypass: PvpropertyEnum = pvproperty(
        name="QUENCH_BYP",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=("Not Bypassed", "Bypassed"),
    )
    interlock_reset: PvpropertyEnum = pvproperty(
        dtype=ChannelType.ENUM,
        name="INTLK_RESET_ALL",
        enum_strings=("", "Reset"),
        value=0,
    )
    probe_cal_start: PvpropertyInteger = pvproperty(name="PROBECALSTRT", value=0)
    probe_cal_stat: PvpropertyEnum = pvproperty(
        name="PROBECALSTS",
        dtype=ChannelType.ENUM,
        value=1,
        enum_strings=("Crash", "Complete", "Running"),
    )
    probe_cal_time: PvpropertyString = pvproperty(
        name="PROBECALTS",
        dtype=ChannelType.STRING,
        value=datetime.now().strftime("%Y-%m-%d-%H:%M:%S"),
    )

    ssa_overrange: PvpropertyInteger = pvproperty(
        value=0, name="ASETSUB.VALQ", dtype=ChannelType.INT
    )

    push_ssa_slope: PvpropertyInteger = pvproperty(
        value=0, name="PUSH_SSA_SLOPE.PROC", dtype=ChannelType.INT
    )
    push_loaded_q: PvpropertyInteger = pvproperty(
        value=0, name="PUSH_QLOADED.PROC", dtype=ChannelType.INT
    )

    push_cav_scale: PvpropertyInteger = pvproperty(
        value=0, name="PUSH_CAV_SCALE.PROC", dtype=ChannelType.INT
    )

    data_decim_a: PvpropertyInteger = pvproperty(
        value=255, name="ACQ_DECIM_SEL.A", dtype=ChannelType.INT
    )
    data_decim_c: PvpropertyInteger = pvproperty(
        value=255, name="ACQ_DECIM_SEL.C", dtype=ChannelType.INT
    )

    calc_probe_q: PvpropertyInteger = pvproperty(
        value=0, name="QPROBE_CALC1.PROC", dtype=ChannelType.INT
    )
    sel_poff: PvpropertyFloat = pvproperty(
        value=0.0, name="SEL_POFF", dtype=ChannelType.FLOAT
    )

    q0: PvpropertyFloat = pvproperty(
        value=randrange(int(2.5e10), int(3.5e10), step=int(0.1e10)),
        name="Q0",
        dtype=ChannelType.FLOAT
    )

    def __init__(self, prefix, isHL: bool):
        super().__init__(prefix)

        self.is_hl = isHL

        if isHL:
            self.length = 0.346
        else:
            self.length = 1.038

    @probe_cal_start.putter
    async def probe_cal_start(self, instance, value):
        if value == 1:
            await self.probe_cal_time.write(
                datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
            )
            await self.probe_cal_start.write(0)

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
    on: PvpropertyEnum = pvproperty(
        value=1, name="PowerOn", dtype=ChannelType.ENUM, enum_strings=("False", "True")
    )
    off: PvpropertyEnum = pvproperty(
        value=0, name="PowerOff", dtype=ChannelType.ENUM, enum_strings=("False", "True")
    )
    reset: PvpropertyEnum = pvproperty(
        value=0,
        name="FaultReset",
        dtype=ChannelType.ENUM,
        enum_strings=("Standby", "Resetting..."),
    )
    alarm_sum: PvpropertyEnum = pvproperty(
        value=0,
        name="AlarmSummary",
        dtype=ChannelType.ENUM,
        enum_strings=("NO_ALARM", "MINOR", "MAJOR", "INVALID"),
    )
    status_msg: PvpropertyEnum = pvproperty(
        value=3,
        name="StatusMsg",
        dtype=ChannelType.ENUM,
        enum_strings=(
            "Unknown",
            "Faulted",
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
            "Resetting Processor...",
        ),
    )

    status_480: PvpropertyEnum = pvproperty(
        name="480VACStat",
        value=0,
        dtype=ChannelType.ENUM,
        enum_strings=("Enabled", "Disabled"),
    )

    cal_start: PvpropertyEnum = pvproperty(
        value=0, name="CALSTRT", dtype=ChannelType.ENUM, enum_strings=("Start", "Start")
    )
    cal_status: PvpropertyEnum = pvproperty(
        value=1,
        name="CALSTS",
        dtype=ChannelType.ENUM,
        enum_strings=("Crash", "Complete", "Running"),
    )
    cal_stat: PvpropertyEnum = pvproperty(
        value=0,
        dtype=ChannelType.ENUM,
        name="CALSTAT",
        enum_strings=("Success", "Crash"),
    )
    slope_old: PvpropertyFloat = pvproperty(
        value=0.0, name="SLOPE", dtype=ChannelType.FLOAT
    )
    slope_new: PvpropertyFloat = pvproperty(
        value=0.0, name="SLOPE_NEW", dtype=ChannelType.FLOAT
    )
    drive_max: PvpropertyFloat = pvproperty(
        name="DRV_MAX_REQ", value=0.8, dtype=ChannelType.FLOAT
    )
    drive_max_save: PvpropertyFloat = pvproperty(
        name="DRV_MAX_SAVE", value=0.8, dtype=ChannelType.FLOAT
    )
    power: PvpropertyFloat = pvproperty(
        name="CALPWR", value=4000, dtype=ChannelType.FLOAT
    )

    nirp: PvpropertyEnum = pvproperty(
        value=1, name="NRP_PRMT", dtype=ChannelType.ENUM, enum_strings=("FAULT", "OK")
    )
    fault_sum: PvpropertyEnum = SeverityProp(
        value=0,
        name="FaultSummary",
    )

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
        print("Calibration Status: ", self.cal_status.value)
        await sleep(5)
        await self.cal_status.write("Complete")
        print("Calibration Status: ", self.cal_status.value)
        await self.slope_new.write(uniform(0.5, 1.5))
        print("New Slope: ", self.slope_new.value)
        if random() < 0.2:
            await self.cal_stat.write("Crash")
            print("Calibration Crashed")
        else:
            await self.cal_stat.write("Success")
            print("Calibration Successful")

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


class PPSPVGroup(PVGroup):
    ready_a = pvproperty(
        value=1,
        dtype=ChannelType.ENUM,
        name="BeamReadyA",
        enum_strings=("Not_Ready", "Ready"),
        record="mbbi",
    )
    ready_b = pvproperty(
        value=1,
        dtype=ChannelType.ENUM,
        name="BeamReadyB",
        enum_strings=("Not_Ready", "Ready"),
        record="mbbi",
    )


class BSOICPVGroup(PVGroup):
    sum_a = pvproperty(
        value=1,
        dtype=ChannelType.ENUM,
        name="SumyA",
        enum_strings=("FAULT", "OK"),
        record="mbbi",
    )
    sum_b = pvproperty(
        value=1,
        dtype=ChannelType.ENUM,
        name="SumyB",
        enum_strings=("FAULT", "OK"),
        record="mbbi",
    )


class MAGNETPVGroup(PVGroup):
    cm_magnet_ps: PvpropertyEnum = pvproperty(
        value=0,
        dtype=ChannelType.ENUM,
        name="STATMSG",
        enum_strings=(
            "Good",
            "BCON Warning",
            "Offline",
            "PAU Ctrl",
            "Turned Off",
            "Not Degaus'd",
            "Not Cal'd",
            "Feedback Ctrl",
            "PS Tripped",
            "DAC Error",
            "ADC Error",
            "Not Stdz'd",
            "Out-of-Tol",
            "Bad Ripple",
            "BAD BACT",
            "No Control",
        ),
    )


class CavityService(Service):
    def __init__(self):
        super().__init__()

        self["PHYS:SYS0:1:SC_CAV_QNCH_RESET_HEARTBEAT"] = ChannelInteger(value=0)
        self["PHYS:SYS0:1:SC_CAV_FAULT_HEARTBEAT"] = ChannelInteger(value=0)

        self["ALRM:SYS0:SC_CAV_FAULT:ALHBERR"] = ChannelEnum(
            enum_strings=("RUNNING", "NOT_RUNNING", "INVALID"), value=0
        )
        self.add_pvs(BSOICPVGroup(prefix="BSOC:SYSW:2:"))

        rackA = range(1, 5)
        self.add_pvs(PPSPVGroup(prefix="PPS:SYSW:1:"))
        self.add_pvs(AutoSetupGlobalPVGroup(prefix="ACCL:SYS0:SC:"))

        for linac_idx, (linac_name, cm_list) in enumerate(LINAC_TUPLES):
            linac_prefix = f"ACCL:{linac_name}:1:"
            self[f"{linac_prefix}AACTMEANSUM"] = ChannelFloat(value=len(LINAC_CM_DICT[linac_idx]) * 8 * 16.60)
            self[f"{linac_prefix}ADES_MAX"] = ChannelFloat(value=2800.0)
            if linac_name == "L1B":
                cm_list += L1BHL
                self[f"{linac_prefix}HL_AACTMEANSUM"] = ChannelFloat(value=0.0)

            self.add_pvs(
                AutoSetupLinacPVGroup(prefix=linac_prefix, linac_idx=linac_idx)
            )
            for cm_name in cm_list:
                is_hl = cm_name in L1BHL
                heater_prefix = f"CPIC:CM{cm_name}:0000:EHCV:"

                self[f"CRYO:CM{cm_name}:0:CAS_ACCESS"] = ChannelEnum(
                    enum_strings=("Close", "Open"), value=1
                )
                self[f"ACCL:{linac_name}:{cm_name}00:ADES_MAX"] = ChannelFloat(
                    value=168.0
                )

                cryo_prefix = f"CLL:CM{cm_name}:2601:US:"
                cm_prefix = f"ACCL:{linac_name}:{cm_name}"

                magnet_infix = f"{linac_name}:{cm_name}85:"

                self.add_pvs(MAGNETPVGroup(prefix=f"XCOR:{magnet_infix}"))
                self.add_pvs(MAGNETPVGroup(prefix=f"YCOR:{magnet_infix}"))
                self.add_pvs(MAGNETPVGroup(prefix=f"QUAD:{magnet_infix}"))

                self.add_pvs(
                    AutoSetupCMPVGroup(prefix=cm_prefix + "00:", cm_name=cm_name)
                )

                jt_prefix = f"CLIC:CM{cm_name}:3001:PVJT:"
                liquid_level_prefix = f"CLL:CM{cm_name}:"
                cavities = {}

                for cav_num in range(1, 9):
                    cav_prefix = cm_prefix + f"{cav_num}0:"

                    HOM_prefix = f"CTE:CM{cm_name}:1{cav_num}"

                    cavity_group = CavityPVGroup(prefix=cav_prefix, isHL=is_hl)
                    self.add_pvs(cavity_group)
                    self.add_pvs(
                        SSAPVGroup(prefix=cav_prefix + "SSA:", cavityGroup=cavity_group)
                    )
                    cavities[cav_num] = cavity_group

                    piezo_group = PiezoPVGroup(
                        prefix=cav_prefix + "PZT:", cavity_group=cavity_group
                    )

                    self.add_pvs(piezo_group)
                    self.add_pvs(
                        StepperPVGroup(
                            prefix=cav_prefix + "STEP:",
                            cavity_group=cavity_group,
                            piezo_group=piezo_group,
                        )
                    )
                    self.add_pvs(CavFaultPVGroup(prefix=cav_prefix))

                    # Rack PVs are stupidly inconsistent
                    if cav_num in rackA:
                        hwi_prefix = cm_prefix + "00:RACKA:"
                    else:
                        hwi_prefix = cm_prefix + "00:RACKB:"

                    self.add_pvs(RACKPVGroup(prefix=hwi_prefix))
                    self.add_pvs(HOMPVGroup(prefix=HOM_prefix))
                    self.add_pvs(
                        AutoSetupCavityPVGroup(
                            prefix=cav_prefix,
                            cm_name=cm_name,
                            cav_num=cav_num,
                        )
                    )

                self.add_pvs(CryoPVGroup(prefix=cryo_prefix))
                self.add_pvs(BeamlineVacuumPVGroup(prefix=cm_prefix + "00:"))
                self.add_pvs(CouplerVacuumPVGroup(prefix=cm_prefix + "10:"))

                liquid_level_pv = LiquidLevelPVGroup(prefix=liquid_level_prefix)
                self.add_pvs(liquid_level_pv)
                cryomodule_group = CryomodulePVGroup(prefix=cm_prefix + "00:", cavities=cavities)
                self.add_pvs(cryomodule_group)
                jtpv_group = JTPVGroup(prefix=jt_prefix, ll_group=liquid_level_pv, cm_group=cryomodule_group)
                self.add_pvs(jtpv_group)
                self.add_pvs(HeaterPVGroup(prefix=heater_prefix, jt_group=jtpv_group, cm_group=cryomodule_group))




def main():
    service = CavityService()
    get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix="", desc="Simulated CM Cavity Service"
    )
    run(service, **run_options)


if __name__ == "__main__":
    main()
