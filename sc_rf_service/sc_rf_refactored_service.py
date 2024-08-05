from asyncio import get_event_loop, sleep
from datetime import datetime
from random import randrange
from typing import Callable, Optional, Dict

from caproto import ChannelFloat, ChannelEnum, ChannelInteger, ChannelString
from caproto.server import ioc_arg_parser, run
from lcls_tools.superconducting.sc_cavity import Cavity
from lcls_tools.superconducting.sc_cryomodule import Cryomodule
from lcls_tools.superconducting.sc_linac import Linac, Machine
from simulacrum import Service


class PropertyFloatChannel(ChannelFloat):
    def __init__(self, putter: Callable = None, precision=0, **kwargs):
        super().__init__(precision=precision, **kwargs)
        self.putter = putter

    async def verify_value(self, value):
        value = await super().verify_value(value)
        if self.putter:
            await self.putter(value)
        return value


class SimulacrumCavity(Cavity):
    def __init__(self, cavity_num: int, rack_object: "Rack"):
        super().__init__(cavity_num, rack_object)
        self.channels = {self.aact_pv: PropertyFloatChannel(value=16.6, putter=self.aact_amp_change),
                         self.pv_addr("Q0"): ChannelFloat(value=randrange(int(2.5e10), int(3.5e10), step=int(0.1e10))),
                         self.acon_pv: ChannelFloat(value=16.6, precision=2),
                         self.ades_pv: ChannelFloat(value=16.6, precision=2),
                         self.rf_mode_ctrl_pv: ChannelEnum(value=4,
                                                           enum_strings=(
                                                               "SELAP", "SELA", "SEL", "SEL Raw", "Pulse", "Chirp")),
                         self.rf_mode_pv: ChannelEnum(value=0,
                                                      enum_strings=(
                                                          "SELAP", "SELA", "SEL", "SEL Raw", "Pulse", "Chirp")),
                         self.rf_state_pv: ChannelEnum(value=1, enum_strings=("Off", "On")),
                         self.ades_max_pv: ChannelFloat(value=21.0),
                         self.rf_permit_pv: ChannelEnum(value=1, enum_strings=("RF inhibit", "RF allow")),
                         self.calc_probe_q_pv: ChannelInteger(value=0),
                         self.push_ssa_slope_pv: ChannelInteger(value=0),
                         self.interlock_reset_pv: ChannelEnum(value=0, enum_strings=("", "Reset")),
                         self.drive_level_pv: ChannelFloat(value=0.0),
                         self.characterization_start_pv: ChannelInteger(value=0),
                         self.characterization_status_pv: ChannelString(
                             value=datetime.now().strftime("%Y-%m-%d-%H:%M:%S")),
                         self.push_scale_factor_pv: ChannelInteger(value=0),
                         self.stepper_temp_pv: ChannelFloat(value=35.0),
                         self.detune_best_pv: ChannelInteger(value=randrange(-10000, 10000)),
                         self.quench_latch_pv: ChannelEnum(value=0, enum_strings=("Ok", "Fault")),
                         }

    async def aact_amp_change(self, value: float):
        cm = self.cryomodule
        cm.jt_stable_pos = cm.total_heat_load(amp_change={self.number: value})
        await cm.adjust_liquid_level()


class SimulacrumCM(Cryomodule):
    def __init__(self, cryo_name: str, linac_object: "Linac"):
        super().__init__(cryo_name, linac_object)
        self.channels = {}
        self.heater_prefix = f"CPIC:CM{self.name}:0000:EHCV:"
        self.heater_setpoint = self.heater_prefix + "MANPOS_RQST"
        self.heater_mode = self.heater_prefix + "MODE_STRING"
        self.channels[self.ds_level_pv] = ChannelFloat(value=93.0)
        self.channels[self.us_level_pv] = ChannelFloat(value=75.0)
        self.channels[self.jt_valve_readback_pv] = ChannelFloat(value=30.0)
        self.channels[self.jt_prefix + "MANPOS_RQST"] = PropertyFloatChannel(value=40.0, putter=self.jt_valve_update)
        self.channels[self.jt_valve_readback_pv] = ChannelFloat(value=40.0)
        self.channels[self.heater_setpoint] = PropertyFloatChannel(value=24.0, putter=self.heater_setpoint_update)
        self.channels[self.heater_readback_pv] = ChannelFloat(value=24.0)
        self.channels[self.heater_mode] = ChannelString(value="MANUAL")

        self.jt_stable_pos: Optional[float] = self.total_heat_load()

    def total_heat_load(self, heater_value: Optional[float] = None, amp_change: Optional[Dict[int, float]] = None):
        rf_heat = 0
        for cavity in self.cavities.values():
            channels = cavity.channels
            aact = channels[cavity.aact_pv].value
            if amp_change and cavity.number == list(amp_change.keys())[0]:
                aact = amp_change[cavity.number]
            rf_heat += (aact * 1e6) ** 2 / (1012 * channels[cavity.pv_addr("Q0")].value)
        heater = self.channels[self.heater_setpoint].value if not heater_value else heater_value
        return rf_heat + heater

    async def adjust_liquid_level(self):
        # TODO: calculate sleep + liquid gained/lost function
        LOSS_AMOUNT = 0.01
        GAIN_AMOUNT = LOSS_AMOUNT
        SLEEP_AMOUNT = 1

        jt_setpoint = self.channels[self.jt_valve_readback_pv].value
        print(self.jt_stable_pos)
        if jt_setpoint * 0.9 > self.jt_stable_pos:
            while (self.channels[self.jt_valve_readback_pv].value * 0.9 > self.jt_stable_pos
                   and 70 <= self.channels[self.ds_level_pv].value <= 100):
                curr = self.channels[self.ds_level_pv].value
                await self.channels[self.ds_level_pv].write(curr - LOSS_AMOUNT)
                await sleep(SLEEP_AMOUNT)
        elif jt_setpoint * 1.1 < self.jt_stable_pos:
            while (self.channels[self.jt_valve_readback_pv].value * 1.1 < self.jt_stable_pos
                   and 70 <= self.channels[self.ds_level_pv].value <= 100):
                curr = self.channels[self.ds_level_pv].value
                await self.channels[self.ds_level_pv].write(curr + GAIN_AMOUNT)
                await sleep(SLEEP_AMOUNT)

    async def jt_valve_update(self, value):
        await self.channels[self.jt_valve_readback_pv].write(value)
        await self.adjust_liquid_level()

    async def heater_setpoint_update(self, value: float):
        self.jt_stable_pos = self.total_heat_load(heater_value=value)
        if self.channels[self.heater_mode].value == "MANUAL":
            await self.channels[self.heater_readback_pv].write(value)
            await self.adjust_liquid_level()


class CavityService(Service):
    def __init__(self):
        super().__init__()
        machine = Machine(cavity_class=SimulacrumCavity, cryomodule_class=SimulacrumCM)
        for cryomodule in machine.cryomodules.values():
            for p, c in cryomodule.channels.items():
                self[p] = c
            for cavity in cryomodule.cavities.values():
                for pv, channel in cavity.channels.items():
                    self[pv] = channel


def main():
    service = CavityService()
    get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix="", desc="Simulated CM Cavity Service"
    )
    run(service, **run_options)


if __name__ == "__main__":
    main()
