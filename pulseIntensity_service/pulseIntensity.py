# saturation length as a function of beta function (beta,m),wigger period
# (xp,m),wiggler K (xk),current (I, A), energy (E, MeV),
# emittance(emittance_n, um),energy spread (sigmae1, keV)

# the felwave in meter will be calculated with the given parameters or 
# be set directly,for optimization the beta function,set wavelength directly will run much faster ;
# is for the optimization at this felwave length;
#
# beta, xp, xk = 10, 0.03, 3.5
# I, E, emittance_n, sigmae1 = 4000, 12000, .4,  3000
import numpy as np
import scipy.special as sp
from math import pi, log
def FELparameters(beta,xp,xk,I,E,emittance_n,sigmae1):
    IA=17045
    sigmae=sigmae1*0.001
    gama=E/0.511
    #felwave=7.9063e-10
    felwave=xp*(1+xk**2/2)/2/gama**2
    emittance=1e-6*emittance_n/gama
    sigmax=(beta*emittance)**0.5 # get the beam size

    aw=xk/2**0.5
    #aw=xk # for circular polarized laser    
    xx=(aw**2)/(2*(1+aw**2))
    Aw=aw*(sp.j0(xx)-sp.j1(xx))

    rou=((I/IA)*((xp*Aw)/sigmax/(2*pi))**2*(0.5/gama)**3)**(1/3)
    L1d=xp/(4*pi*rou*3**0.5)

    Lr=4*pi*sigmax**2/felwave #rayley length
    yd=L1d/Lr  # Xie's three parameters for 3D
    yr=(4*pi*L1d*sigmae)/(xp*E)
    ye=(((L1d/beta)*4*pi)*emittance)/felwave
    y=0.45*yd**0.57+0.55*ye**1.6+3*yr**2+0.35*(ye**2.9)*yr**2.4+51*(yd**0.95)*yr**3+5.4*(yd**0.7)*ye**1.9+1140*((yd**2.2)*ye**2.9)*yr**3.2
    Lg=(1+y)*L1d 

    Pbeam=I*E*1000000
    Psat=(1.6*rou*(L1d/Lg)**2)*Pbeam
    alpha=1/9
    Pn=rou**2*E*3*1.6e-5/felwave
    Lsat=Lg*log(Psat/Pn/alpha)
    yy=Lsat

    return (Lsat,Psat,felwave,Lg)
