"""
Test correctness of dynamical model derivatives

Correctness is tested by comparing finite differences against
implemented derivatives along specified perturbations.
"""

from os import path

import pytest
import numpy as np
import dolfin as dfn

from blockarray import linalg as bla
from femvf.models.dynamical import (
    solid as dynsl, fluid as dynfl, base as dynbase
)
from femvf import load

# pylint: disable=redefined-outer-name

# warnings.filterwarnings('error', 'RuntimeWarning')
# np.seterr(invalid='raise')

def _set_dirichlet_bvec(dirichlet_bc, bvec):
    for label in ['u', 'v']:
        if label in bvec:
            dirichlet_bc.apply(dfn.PETScVector(bvec.sub[label]))
    return bvec

@pytest.fixture()
def setup_dynamical_models():
    """
    Setup the dynamical model objects
    """
    mesh_name = 'M5-3layers'
    mesh_name = 'BC-dcov5.00e-02-cl1.00'
    mesh_path = path.join('../meshes', mesh_name+'.xml')

    solid_mesh = mesh_path
    fluid_mesh = None

    SolidType = dynsl.KelvinVoigt
    FluidType = dynfl.BernoulliSmoothMinSep
    model_coupled = load.load_dynamical_fsi_model(
        solid_mesh, fluid_mesh, SolidType, FluidType,
        fsi_facet_labels=('pressure',), fixed_facet_labels=('fixed',)
    )

    SolidType = dynsl.LinearizedKelvinVoigt
    FluidType = dynfl.LinearizedBernoulliSmoothMinSep
    model_coupled_linear = load.load_dynamical_fsi_model(
        solid_mesh, fluid_mesh, SolidType, FluidType,
        fsi_facet_labels=('pressure',), fixed_facet_labels=('fixed',)
    )

    return model_coupled, model_coupled_linear

@pytest.fixture()
def model(setup_dynamical_models):
    """
    Return a dynamical system model residual
    """
    return setup_dynamical_models[0]

@pytest.fixture()
def model_linear(setup_dynamical_models):
    """
    Return a linearized dynamical system model residual
    """
    return setup_dynamical_models[1]

@pytest.fixture()
def linearization(model):
    """
    Return linearization point
    """
    ## Set model properties/control/linearization directions
    model_solid = model.solid

    # (linearization directions for linearized residuals)
    props0 = model.props.copy()
    props0['emod'] = 5e3*10
    props0['rho'] = 1.0

    ymax = np.max(model_solid.XREF[1::2])
    ygap = 0.01 # gap between VF and symmetry plane
    ymid = ymax + ygap
    ycontact = ymid - 0.1*ygap
    props0['ycontact'] = ycontact

    model.ymid = ymid

    props0['zeta_sep'] = 1e-4
    props0['zeta_min'] = 1e-4
    props0['rho_air'] = 1.2e-3
    model.set_props(props0)

    control0 = model.control.copy()
    control0[:] = 1.0
    if 'psub' in control0:
        control0['psub'] = 800*10
    if 'psup' in control0:
        control0['psup'] = 0
    model.set_control(control0)

    del_state = model.state.copy()
    del_state[:] = 0.0
    del_state['u'] = 1.0
    _set_dirichlet_bvec(model_solid.forms['bc.dirichlet'], del_state)
    model.set_dstate(del_state)

    del_statet = model.state.copy()
    del_statet[:] = 1.0e4
    _set_dirichlet_bvec(model_solid.forms['bc.dirichlet'], del_statet)
    model.set_dstatet(del_statet)

    state0 = model.state.copy()
    # Make the initial displacement a pure shear motion
    xref = model.solid.forms['coeff.ref.x'].vector().copy()
    xx = xref[:-1:2]
    yy = xref[1::2]
    state0['u'][:-1:2] = 0.01*(yy/yy.max())
    state0['u'][1::2] = 0.0 * yy
    model.set_state(state0)

    statet0 = state0.copy()
    model.set_statet(statet0)

    return state0, statet0, control0, props0

@pytest.fixture()
def perturbation(model):
    """
    Return parameter perturbations
    """
    model_solid = model.solid

    dstate = model.state.copy()
    if 'u' in dstate and 'v' in dstate:
        dxu = model_solid.state['u'].copy()
        dxu[:] = 1e-3*np.arange(dxu[:].size)
        dxu[:] = 1e-8
        # dxu[:] = 0
        # model_solid.forms['bc.dirichlet'].apply(dxu)
        dstate['u'] = dxu

        dxv = model_solid.state['v'].copy()
        dxv[:] = 1e-8
        # model_solid.forms['bc.dirichlet'].apply(dxv)
        dstate['v'] = dxv
    if 'q' in dstate:
        dstate['q'] = 1e-3
    if 'p' in dstate:
        dstate['p'] = 1e-3
    _set_dirichlet_bvec(model_solid.forms['bc.dirichlet'], dstate)

    dstatet = dstate.copy()
    dstatet[:] = 1e-6
    _set_dirichlet_bvec(model_solid.forms['bc.dirichlet'], dstatet)

    props0 = model.props.copy()
    dprops = props0.copy()
    dprops[:] = 0
    dprops['emod'] = 1.0

    # Use a uniaxial y stretching motion
    fspace = model_solid.forms['fspace.vector']
    VDOF_TO_VERT = dfn.dof_to_vertex_map(fspace)
    coords = model_solid.forms['mesh.REF_COORDINATES']
    umesh = coords.copy()
    umesh[:, 0] = 0
    umesh[:, 1] = 1e-5*coords[:, 1]/coords[:, 1].max()
    dprops['umesh'] = umesh.reshape(-1)[VDOF_TO_VERT]
    # dprops['umesh'] = 0

    dcontrol = model.control.copy()
    dcontrol[:] = 1e0
    return dstate, dstatet, dcontrol, dprops

@pytest.fixture()
def dstate(perturbation):
    """Return a state perturbation"""
    return perturbation[0]

@pytest.fixture()
def dstatet(perturbation):
    """Return a state derivative perturbation"""
    return perturbation[1]

@pytest.fixture()
def dcontrol(perturbation):
    """Return a control perturbation"""
    return perturbation[2]

@pytest.fixture()
def dprops(perturbation):
    """Return a properties perturbation"""
    return perturbation[3]


def set_linearization(model: dynbase.BaseDynamicalModel, linearization):
    """
    Set the model linearization point
    """
    state, statet, control, props = linearization
    model.set_state(state)
    model.set_statet(statet)
    model.set_control(control)
    model.set_props(props)

def set_and_assemble(x, set_x, assem):
    set_x(x)
    # A copy is needed because the assembler functions often return the same matrix/vector object
    # As a result, not creating copies will keep overwriting 'previous' instances of an assembled
    # tensor
    return assem().copy()

def _test_taylor(x0, dx, res, jac):
    """
    Test that the Taylor convergence order is 2
    """
    alphas = 2**np.arange(4)[::-1] # start with the largest step and move to original
    res_ns = [res(x0+float(alpha)*dx) for alpha in alphas]
    res_0 = res(x0)

    dres_exacts = [res_n-res_0 for res_n in res_ns]
    dres_linear = bla.mult_mat_vec(jac(x0), dx)

    errs = [
        (dres_exact-float(alpha)*dres_linear).norm()
        for dres_exact, alpha in zip(dres_exacts, alphas)
    ]
    magnitudes = [
        1/2*(dres_exact+float(alpha)*dres_linear).norm()
        for dres_exact, alpha in zip(dres_exacts, alphas)
    ]
    with np.errstate(invalid='ignore'):
        conv_rates = [
            np.log(err_0/err_1)/np.log(alpha_0/alpha_1)
            for err_0, err_1, alpha_0, alpha_1
            in zip(errs[:-1], errs[1:], alphas[:-1], alphas[1:])]
        rel_errs = np.array(errs)/np.array(magnitudes)*100

    print("")
    print(f"||dres_linear||, ||dres_exact|| = {dres_linear.norm()}, {dres_exacts[-1].norm()}")
    print("Relative errors: ", rel_errs)
    print("Convergence rates: ", np.array(conv_rates))


def test_assem_dres_dstate(model, linearization, dstate):
    """
    Test `model.assem_dres_dstate`
    """
    set_linearization(model, linearization)
    state, statet, control, props = linearization
    res = lambda state: set_and_assemble(state, model.set_state, model.assem_res)
    jac = lambda state: set_and_assemble(state, model.set_state, model.assem_dres_dstate)

    _test_taylor(state, dstate, res, jac)

def test_assem_dres_dstatet(model, linearization, dstatet):
    """
    Test `model.assem_dres_dstatet`
    """
    set_linearization(model, linearization)
    state, statet, control, props = linearization
    res = lambda state: set_and_assemble(state, model.set_statet, model.assem_res)
    jac = lambda state: set_and_assemble(state, model.set_statet, model.assem_dres_dstatet)

    _test_taylor(statet, dstatet, res, jac)

def test_assem_dres_dcontrol(model, linearization, dcontrol):
    """
    Test `model.assem_dres_dcontrol`
    """
    set_linearization(model, linearization)
    state, statet, control, props = linearization
    # model_fluid.control['psub'][:] = 1
    # model_fluid.control['psup'][:] = 0
    res = lambda state: set_and_assemble(state, model.set_control, model.assem_res)
    jac = lambda state: set_and_assemble(state, model.set_control, model.assem_dres_dcontrol)

    _test_taylor(control, dcontrol, res, jac)

def test_assem_dres_dprops(model, linearization, dprops):
    """
    Test `model.assem_dres_dprops`
    """
    set_linearization(model, linearization)
    state, statet, control, props = linearization
    res = lambda state: set_and_assemble(state, model.set_props, model.assem_res)
    jac = lambda state: set_and_assemble(state, model.set_props, model.assem_dres_dprops)

    _test_taylor(props, dprops, res, jac)

def test_dres_dstate_vs_dres_state(model, model_linear, linearization, dstate):
    """
    Test consistency between `model` and `model_linear_state`

    `model` represents a residual F(...)
    `model_linear_state` represents the linearized residual (dF/dstate * del_state)(...)
    This test checks that:
        dF/dstate(...) * del_state    (computed from `model`)
        is equal to
        (dF/dstate * del_state)(...)  (computed from `model_linear_state`)
    """
    set_linearization(model, linearization)
    set_linearization(model_linear, linearization)
    state, statet, control, props = linearization

    # compute the linearized residual from `model`
    dres_dstate = set_and_assemble(state, model.set_state, model.assem_dres_dstate)
    dres_state_a = bla.mult_mat_vec(dres_dstate, dstate)

    model_linear.set_dstate(dstate)
    _zero_del_xt = model_linear.dstatet.copy()
    _zero_del_xt[:] = 0
    model_linear.set_dstatet(_zero_del_xt)

    dres_state_b = set_and_assemble(state, model_linear.set_state, model_linear.assem_res)
    err = dres_state_a - dres_state_b

    for vec, name in zip([dres_state_a, dres_state_b, err], ["from model", "from linear_state_model", "error"]):
        print(f"\n{name}")
        for key, subvec in vec.sub_items():
            print(key, subvec.norm())

def test_dres_dstatet_vs_dres_statet(model, model_linear, linearization, dstatet):
    """
    Test consistency between `model` and `model_linear_state`

    `model` represents a residual F(...)
    `model_linear_state` represents the linearized residual (dF/dstate * del_state)(...)
    This test checks that:
        dF/dstate(...) * del_state    (computed from `model`)
        is equal to
        (dF/dstate * del_state)(...)  (computed from `model_linear_state`)
    """
    set_linearization(model, linearization)
    set_linearization(model_linear, linearization)
    state, statet, control, props = linearization

    # compute the linearized residual from `model`
    dres_dstatet = set_and_assemble(statet, model.set_state, model.assem_dres_dstatet)
    dres_statet_a = bla.mult_mat_vec(dres_dstatet, dstatet)

    model_linear.set_dstatet(dstatet)
    _zero_del_x = model_linear.dstate.copy()
    _zero_del_x[:] = 0
    model_linear.set_dstate(_zero_del_x)

    dres_statet_b = set_and_assemble(statet, model_linear.set_state, model_linear.assem_res)
    err = dres_statet_a - dres_statet_b

    for vec, name in zip([dres_statet_a, dres_statet_b, err], ["from model", "from linear_state_model", "error"]):
        print(f"\n{name}")
        for key, subvec in vec.sub_items():
            print(key, subvec.norm())
