from asyncio import get_event_loop, sleep
from random import randrange
from typing import Callable, Optional, Dict

from caproto import ChannelFloat
from caproto.server import ioc_arg_parser, run
from lcls_tools.superconducting.sc_cavity import Cavity
from lcls_tools.superconducting.sc_cryomodule import Cryomodule
from lcls_tools.superconducting.sc_linac import Linac, Machine
from simulacrum import Service


class PropertyFloatChannel(ChannelFloat):
    def __init__(self, putter: Callable=None, precision=0, **kwargs):
        super().__init__(precision=precision, **kwargs)
        self.putter = putter

    async def verify_value(self, value):
        value = await super().verify_value(value)
        if self.putter is not None:
            return await self.putter(value)

class SimulacrumCavity(Cavity):
    def __init__(self, cavity_num: int, rack_object: "Rack"):
        super().__init__(cavity_num, rack_object)
        self.channels = {self.aact_pv: PropertyFloatChannel(value=16.6, putter=self.aact_amp_change),
                         self.pv_addr("Q0"): ChannelFloat(value=randrange(int(2.5e10), int(3.5e10), step=int(0.1e10)))}

    async def aact_amp_change(self, value: float):
        cm = self.cryomodule
        cm.jt_stable_pos = cm.total_heat_load(amp_change={self.number: value})
        jt_man_pos = cm.channels[cm.jt_prefix + "MANPOS_RQST"].value
        if jt_man_pos * 1.1 > cm.jt_stable_pos:
            while jt_man_pos * 1.1 > cm.jt_stable_pos:
                await cm.adjust_liquid_level()
        elif jt_man_pos * 0.9 < cm.jt_stable_pos:
            while jt_man_pos * 0.9 < cm.jt_stable_pos:
                await cm.adjust_liquid_level()


class SimulacrumCM(Cryomodule):
    def __init__(self, cryo_name: str, linac_object: "Linac", ):
        super().__init__(cryo_name, linac_object)
        self.channels = {}
        self.heater_setpoint = f"CPIC:CM{self.name}:0000:EHCV:MANPOS_RQST"
        self.channels[self.ds_level_pv] = ChannelFloat(value=93.0)
        self.channels[self.us_level_pv] = ChannelFloat(value=75.0)
        self.channels[self.jt_valve_readback_pv] = ChannelFloat(value=30.0)
        self.channels[self.jt_prefix + "MANPOS_RQST"] = PropertyFloatChannel(value=40.0, putter=self.jt_valve_update)
        self.channels[self.heater_setpoint] = PropertyFloatChannel(value=24.0, putter=self.heater_setpoint_update)
        self.jt_stable_pos = self.total_heat_load()

    def total_heat_load(self, heater_value: Optional[float] = None, amp_change: Optional[Dict[int, float]] = None):
        rf_heat = 0
        for _, cavity in self.cavities.items():
            channels = cavity.channels
            aact = channels[cavity.aact_pv].value
            if amp_change:
                if cavity.number == list(amp_change.keys())[0]:
                    aact = amp_change[cavity.number]
            rf_heat += (aact * 1e6) ** 2 / (1012 * channels[cavity.pv_addr("Q0")].value)
        heater = self.channels[self.heater_setpoint].value if not heater_value else heater_value
        return rf_heat + heater

    async def adjust_liquid_level(self):
        # TODO: calculate sleep + liquid gained/lost function
        LOSS_AMOUNT = 0.01
        GAIN_AMOUNT = LOSS_AMOUNT
        SLEEP_AMOUNT = 1

        jt_setpoint = self.channels[self.jt_prefix + "MANPOS_RQST"].value
        curr = self.channels[self.ds_level_pv].value
        if jt_setpoint * 1.1 > self.jt_stable_pos:
            await self.channels[self.ds_level_pv].write(curr - LOSS_AMOUNT)
            await sleep(SLEEP_AMOUNT)
        elif jt_setpoint * 0.9 < self.jt_stable_pos:
            await self.channels[self.ds_level_pv].write(curr + GAIN_AMOUNT)
            await sleep(SLEEP_AMOUNT)

    async def jt_valve_update(self, instance, value: float):
        if value * 1.1 > self.jt_stable_pos:
            while value * 1.1 > self.jt_stable_pos:
                await sleep(1)
        elif value * 0.9 < self.jt_stable_pos:
            while value * 0.9 < self.jt_stable_pos:
                await sleep(1)

    async def heater_setpoint_update(self, value: float):
        self.jt_stable_pos = self.total_heat_load(heater_value=value)
        jt_man_pos = self.channels[self.jt_prefix + "MANPOS_RQST"].value
        if jt_man_pos * 1.1 > self.jt_stable_pos:
            while jt_man_pos * 1.1 > self.jt_stable_pos:
                await self.adjust_liquid_level()
        elif jt_man_pos * 0.9 < self.jt_stable_pos:
            while jt_man_pos * 0.9 < self.jt_stable_pos:
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
