import asyncio
from caproto import ChannelType
from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run

import simulacrum


class DecaradPV(PVGroup):
    powerControl = pvproperty(value=0, name="HVCTRL", dtype=ChannelType.ENUM,
                              enum_strings=("Off", "On"))
    powerStatus = pvproperty(value=0, name="HVSTATUS", dtype=ChannelType.ENUM,
                             enum_strings=("Off", "On"))
    voltage = pvproperty(value=250.0, name="HVMON", dtype=ChannelType.FLOAT)
    
    @powerControl.putter
    async def powerControl(self, instance, value):
        await self.powerStatus.write(value)


class DecaradHeadPV(PVGroup):
    doseRate = pvproperty(value=4, name="GAMMA_DOSE_RATE", dtype=ChannelType.FLOAT)
    doseRateAvg = pvproperty(value=4, name="GAMMAAVE", dtype=ChannelType.FLOAT)


class DecaradService(simulacrum.Service):
    def __init__(self):
        super().__init__()
        
        decaradPVs = {}
        
        for num in [1, 2]:
            prefix = "RADM:SYS0:{num}00:".format(num=num)
            decaradPVs[prefix] = DecaradPV(prefix=prefix)
            
            for headNum in range(1, 11):
                headPrefix = prefix + "{:02d}:".format(headNum)
                decaradPVs[headPrefix] = DecaradHeadPV(prefix=headPrefix)
        
        self.add_pvs(decaradPVs)


def main():
    service = DecaradService()
    asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
            default_prefix='',
            desc="Simulated Decarad")
    run(service, **run_options)


if __name__ == '__main__':
    main()
