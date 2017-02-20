import numpy as np
import pickle
import sys
import cyclops_control
import cyclops_base
import RSWE_direct
from spectral_toolbox import SpectralToolbox
from rswe_exponential_integrator import *
from mpi4py import MPI

def P_integrate(control, truth, state):
    """
    """
    integrand = truth - state

    #Perform time integral
    integrand = np.trapz(integrand, axis = 0, dx = control['final_time'])

    #Perform x integral and norm
    integrand = integrand*integrand
    integrand = np.trapz(integrand, dx = control['Lx']/control['Nx'])
    integrand = np.trapz(integrand, dx = control['Lx']/control['Nx'])

    return np.sqrt(integrand)


def main(control):
    """

    """

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    if control['outFileStem'] is None: control['outFileStem'] = ''

    if rank != 0:
        i_g = int((rank - 1) / np.sqrt(size - 1))
        i_m = int((rank - 1) % np.sqrt(size - 1))

    # Hardcoded for now:
    N_avg_g = np.sqrt(size - 1)
    N_avg_m = np.sqrt(size - 1)

    # Set up initial (truth) field
    ICs = cyclops_base.read_ICs(control, control['filename'])
    st = SpectralToolbox(control['Nx'], control['Lx'])

    if rank == 0:
        truth = np.zeros((control['Nt'] + 1, 3, control['Nx'], control['Nx']))
        truth[0, :, :, :] = ICs
        errs = np.zeros((N_avg_m, N_avg_g))

        expInt = ExponentialIntegrator_FullEqs(control)

        print("Running truth")
        for i in range(control['Nt']):
            truth[i + 1, :, :, :] = RSWE_direct.solve('fine_propagator', control, st, expInt, truth[i, :, :, :])

        with open("{}avg_opt_fine.dat".format(control['outFileStem']), "wb") as f:
            truth_out = truth
            for i in range(control['Nt'] + 1):
                truth_out[i,2,:,:] = cyclops_base.inv_geopotential_transform(control, truth_out[i,2,:,:])
            pickle.dump(truth_out,f)

    else:
        if control['rot_stiff']:  # Rot-dominated
            expInt_L = ExpInt_Rotational(control)
            Kop = make_Lop_grav(control)
        else:  # Grav-dominated
            expInt_L = ExpInt_Gravitational(control)
            Kop = make_Lop_rot(control)

        control['HMM_T0_M'] = 0.1*control['coarse_timestep']*(i_m + 1)  # /N_avg_m
        control['HMM_M_bar_M'] = max(10, int(80*control['HMM_T0_M']))

        control['HMM_T0_L'] = 0.1*control['coarse_timestep']*(i_g + 1)  # /N_avg_g
        control['HMM_M_bar_L'] = max(10, int(80*control['HMM_T0_L']))

        expInt_m = expM(control, expInt_L, Kop)
        expInt = (expInt_m, expInt_L)

        test = np.zeros((control['Nt'] + 1, 3, control['Nx'], control['Nx']))
        test[0, :, :, :] = ICs

        #print("Running avg for gwin = {}, mwin = {}".format(control['HMM_T0_L'], control['HMM_T0_M']))
        for i in range(control['Nt']):
            test[i + 1, :, :, :] = RSWE_direct.solve('coarse_propagator', control, st, expInt, test[i, :, :, :])

        with open("{}avg_opt_{}_{}.dat".format(control['outFileStem'], i_m, i_g), "wb") as f:
            test_out = test
            for i in range(control['Nt'] + 1):
                test_out[i,2,:,:] = cyclops_base.inv_geopotential_transform(control, test_out[i,2,:,:])
            pickle.dump(test_out,f)

    comm.Barrier()
    for i_rank in range(1, size):
        i_g = int((i_rank - 1) / np.sqrt(size - 1))
        i_m = int((i_rank - 1) % np.sqrt(size - 1))

        if i_rank == rank:
            data = np.ascontiguousarray(test)
            comm.Send(data, dest=0, tag=13)

        if rank == 0:
            test = np.empty((control['Nt'] + 1, 3, control['Nx'], control['Nx']))
            comm.Recv(test, source=i_rank, tag=13)

            errs[i_m, i_g] = P_integrate(control, truth[:,2,:,:], test[:,2,:,:])

        comm.Barrier()

    if rank == 0:
        with open("{}avg_tests.dat".format(control['outFileStem']), 'wb') as f:
            pickle.dump(errs, f)

if __name__ == "__main__":
    control_in = cyclops_control.setup_control(sys.argv[1:])
    main(control_in)