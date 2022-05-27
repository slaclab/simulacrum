import asyncio
from caproto import ChannelType
from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run

import simulacrum
from lcls_tools.superconducting.scLinac import ALL_CRYOMODULES, CRYOMODULE_OBJECTS, L1BHL


class MagnetPV(PVGroup):
    bdes = pvproperty(value=0.0, name="BDES",
                      dtype=ChannelType.FLOAT)
    bact = pvproperty(value=0.0, name="BACT",
                      dtype=ChannelType.FLOAT)
    ctrl = pvproperty(value=0, name="CTRL", dtype=ChannelType.ENUM,
                      enum_strings=("Ready", "TRIM", "PERTURB", "BCON_TO_BDES",
                                    "SAVE_BDES", "LOAD_BDES", "UNDO_BDES",
                                    "DAC_ZERO", "CALIB", "STDZ", "RESET",
                                    "TURN_ON", "TURN_OFF", "DEGAUSS"))
    intlkstatus = pvproperty(value=0, name="INTLKSUMY", dtype=ChannelType.ENUM,
                             enum_strings=("OK", "FAULT"))
    ps_status = pvproperty(value=0, name="STATE", dtype=ChannelType.ENUM,
                           enum_strings=("OFF", "ON"))
    
    @bdes.putter
    async def bdes(self, instance, value):
        await self.bact.write(value)
    
    @ctrl.putter
    async def ctrl(self, instance, value):
        print('Setting magnet control to {value}'.format(value=value))
        if value == "TURN_OFF":
            await self.ps_status.write(0)
        elif value == "TURN_ON":
            await self.ps_status.write(1)
        else:
            print('magnet control handling not implemented')


class SCMagnetService(simulacrum.Service):
    def __init__(self):
        super().__init__()
        
        quads = {}
        xcors = {}
        ycors = {}
        
        for cmName in ALL_CRYOMODULES:
            if cmName in L1BHL:
                continue
            cm = CRYOMODULE_OBJECTS[cmName]
            quads[cm.quad.pvprefix] = MagnetPV(prefix=cm.quad.pvprefix)
            xcors[cm.xcor.pvprefix] = MagnetPV(prefix=cm.xcor.pvprefix)
            ycors[cm.ycor.pvprefix] = MagnetPV(prefix=cm.ycor.pvprefix)
        
        self.add_pvs(quads)
        self.add_pvs(xcors)
        self.add_pvs(ycors)


def main():
    service = SCMagnetService()
    asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
            default_prefix='',
            desc="Simulated SC Magnet Service")
    run(service, **run_options)


if __name__ == '__main__':
    main()
