"""
Runs the model over a range of elastic moduli.

I want to use this to see if parameter changes over collisions result in
smooth functionals.
"""

import os
from time import perf_counter

import h5py
import numpy as np
import dolfin as dfn

from forward import forward
import constants

if __name__ == '__main__':
    dfn.set_log_level(30)

    save_path = f"out/collision_elasticity_sweep.h5"
    emod = constants.DEFAULT_SOLID_PROPERTIES['elastic_modulus']
    elastic_moduli = np.linspace(2*emod, 3*emod, 500)

    fluid_props = constants.DEFAULT_FLUID_PROPERTIES
    fluid_props['p_sub'] = [1500 * constants.PASCAL_TO_CGS, 1500 * constants.PASCAL_TO_CGS, 1, 1]
    fluid_props['p_sub_time'] = [0, 3e-3, 3e-3, 0.02]

    # fluid_props['p_sub'] = 800

    with h5py.File(save_path, mode='w') as f:
        f.create_dataset('elastic_moduli', data=elastic_moduli)

    for ii, elastic_modulus in enumerate(elastic_moduli):
        solid_props = {'elastic_modulus': elastic_modulus}

        runtime_start = perf_counter()
        forward([0, 0.02], solid_props, fluid_props, save_path, h5group=f'{ii}/', show_figure=False)
        runtime_end = perf_counter()

        runtime = runtime_end-runtime_start
        print(f"Runtime: {runtime:.2f} s")
