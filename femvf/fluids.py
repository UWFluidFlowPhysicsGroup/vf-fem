"""
Functionality related to fluids
"""

import numpy as np
import math

import dolfin as dfn
from petsc4py import PETSc


# 1D viscous euler approximation
def fluid_pressure_vasu(x, x0, xr, fluid_props):
    """
    Return fluid surface pressures according to a 1D flow model.

    The flow model is given by "" vasudevan etc.

    Parameters
    ----------
    x : tuple of (u, v, a) each of (#surface vertices, geometric dimension) np.ndarray
        States of the surface vertices, ordered following the flow (increasing x coordinate).
    fluid_props : dict
        A dictionary of fluid properties.
    xr : np.ndarray
        The nodal locations of the fixed reference grid over which the problem is solved.

    Returns
    -------
    q, p : np.ndarray
        An array of flow rate and pressure vectors for each each vertex
    dqdx, dpdx : np.ndarray
        Arrays of sensititivies of nodal flow rates and pressures to the surface displacements and
        velocities
    xy_min, xy_sep: (2,) np.ndarray
        The coordinates of the vertices at minimum and separation areas
    """
    u, v, a = x

    area = 2*u[..., 1]
    darea_dt = 2*v[..., 1]

def res_fluid(n, p_bcs, qp0, qp1, xy_ref, uva0, uva1, fluid_props, dt):
    """
    Return the momentum and continuity equation residuals applied at node `n`.

    Momentum and continuity residuals are returned based on the equation between state 0 and 1
    over a given time step and a guess of the final fluid and solid states.

    Parameters
    ----------
    qp0, qp1 : tuple(array_like, array_like)
        The fluid flow rate and pressure states in a tuple
    uva : tuple(array_like, array_like, array_like)
        The fluid-structure interace displacement, velocity, and acceleration states in a tuple
    xy_ref, uva0, uva1 : tuple(array_like, array_like)
        xy coordinates/displacements of the fluid-structure interace at the reference configuration,
        and current and future timesteps
    fluid_props : femvf.properties.FluidProperties
        The fluid properties
    dt : float
        The timestep between the initial and final states of the iteration.

    Returns
    -------
    tuple(float, float)
        The continuity and momentum equation residuals respectively.
    """
    ## Set the finite differencing stencil according to the node
    fdiff = None
    NUM_NODE = xy_ref.size

    if n == NUM_NODE-1:
        fdiff = bd
    elif n == 0:
        fdiff = fd
    else:
        fdiff = cd

    ## Precompute some variables needed in computing residuals for continuity and momentum
    # The reference grid for ALE is evenly spaced between the first and last FSI interface
    # x-coordinates
    dx = (xy_ref[-1, 0] - xy_ref[0, 0]) / NUM_NODE
    u1, v1, _ = uva1

    rho = fluid_props['rho']

    # Flow rate and pressure
    q0, _ = qp0
    q1, p1 = qp1

    area = 2*u1[..., 1]
    darea_dt = 2*v1[..., 1]

    # The x-coordinates of the moving mesh are the initial surface node values plus the
    # x-displacement
    # This is needed to calculate deformation gradient for use in ALE
    # x0 = xr + u0[..., 0]
    x1 = xy_ref[..., 0] + u1[..., 0]

    def_grad = 1/fdiff(x1, n, dx)
    darea_dx = fdiff(area, n, dx)
    dq_dx = fdiff(q1, n, dx)
    dp_dx = fdiff(p1, n, dx)
    dqarea_dx = fdiff(area*q1, n, dx)

    ## Calculate the momentum and continuity residuals
    res_continuity = darea_dt[n] - darea_dx*def_grad*v1[n, 0] + dqarea_dx*def_grad

    dq_dt = (q1[n]-q0[n])/dt
    sep_criteria = q0[n]*fluid_props['rho']*(-q0[n]*dq_dx - dq_dt)
    xx = separation_factor(0.25, 0.1, sep_criteria)
    tau = (1-xx)*rho*q1[n]*dq_dx*def_grad
    res_momentum = rho*q1[n]*dq_dx*def_grad + rho*(dq_dt-dq_dx*def_grad*v1[n, 0]) \
                   + dp_dx*def_grad - tau

    return res_continuity, res_momentum

def res_fluid_quasistatic(n, p_bcs, qp0, xy_ref, uva0, fluid_props):
    """
    Return the momentum and continuity equation residuals applied at node `n`.

    Momentum and continuity residuals are returned based on the equation between state 0 and 1
    over a given time step and a guess of the final fluid and solid states.

    Parameters
    ----------
    n : int
        The node number to compute the residual at
    p_bcs : tuple(float, float)
        The pressure boundary conditions at the inlet and outlet
    qp0 : tuple(array_like[:], array_like[:])
        The fluid flow rate and pressure states in a tuple
    uva0 : tuple(array_like[:, 2], array_like[:, 2], array_like[:, 2])
        The fluid-structure interace displacement, velocity, and acceleration states in a tuple
    xy_ref : array_like[:, 2]
        The fluid-structure interace coordinates in the reference configuration
    fluid_props : femvf.properties.FluidProperties
        The fluid properties

    Returns
    -------
    tuple(float, float)
        The continuity and momentum equation residuals respectively.
    """
    ## Set the finite differencing stencil according to the node
    fdiff = None
    NUM_NODE = xy_ref.shape[0]

    # breakpoint()
    if n == NUM_NODE-1:
        fdiff = bd
    elif n == 0:
        fdiff = fd
    else:
        fdiff = cd

    ## Precompute some variables needed in computing residuals for continuity and momentum
    # The reference grid for ALE is evenly spaced between the first and last FSI interface
    # x-coordinates
    dx = (xy_ref[-1, 0] - xy_ref[0, 0]) / NUM_NODE
    u0, v0, _ = uva0

    rho = fluid_props['rho']

    # Flow rate and pressure
    q0, p0 = qp0
    p0[0], p0[-1] = p_bcs[0], p_bcs[1]

    # The x-coordinates of the moving mesh are the initial surface node values plus the
    # x-displacement
    xy0 = xy_ref[..., :] + u0[..., :]
    area = 2*(fluid_props['y_midline'] - xy0[..., 1])

    def_grad = 1/fdiff(xy0[..., 0], n, dx)
    # darea_dx = fdiff(area, n, dx)
    dq_dx = fdiff(q0, n, dx)
    dp_dx = fdiff(p0, n, dx)
    dqarea_dx = fdiff(area*q0, n, dx)

    ## Calculate the momentum and continuity residuals
    res_continuity = dqarea_dx*def_grad

    # The separation criteria is based on q dp/dx but most suggest using the inviscid approximation,
    # which is dp/dx = -rho*q*dq/dx
    sep_criteria = q0[n]*fluid_props['rho'] * (-q0[n]*dq_dx)
    xx = separation_factor(0.0, 0.1, sep_criteria)
    tau = (1-xx)*rho*q0[n]*dq_dx*def_grad
    res_momentum = rho*q0[n]*dq_dx*def_grad + dp_dx*def_grad - tau

    info = {'tau': tau, 'separation_factor': xx}

    return res_continuity, res_momentum, info

def separation_factor(sep_factor_min, alpha_max, alpha):
    """
    Return the separation factor (a fancy x)

    parameters
    ----------
    alpha : float
        A separation criteria given by :math:`\alpha=q\frac{dp}{dx}` or approximated by the inviscid
        approximation using :math:`\alpha \approx q*(-\rho q \frac{dq}{dx}-rho\frac{dq}{dt})`
    """
    sep_factor = None
    if alpha < 0:
        sep_factor = 1
    elif alpha < alpha_max:
        sep_factor = sep_factor_min/2*(1-math.cos(math.pi*alpha/alpha_max))
    else:
        sep_factor = sep_factor_min

    return sep_factor

def cd(f, n, dx):
    """
    Return the central difference approximation of f at n.
    """
    return (f[n+1]-f[n-1]) / (2*dx)

def cd_df(f, n, dx):
    """
    Return the derivative of the central difference approximation of f at n, to the vector of f.
    """
    idxs = [n-1, n+1]
    vals = [-1/(2*dx), 1/(2*dx)]

def fd(f, n, dx):
    """
    Return the central difference approximation of f at n.
    """
    return (f[n+1]-f[n]) / dx

def fd_df(f, n, dx):
    """
    Return the derivative of the central difference approximation of f at n, to the vector of f.
    """
    idxs = [n, n+1]
    vals = [-1/dx, 1/dx]

def bd(f, n, dx):
    """
    Return the central difference approximation of f at n.
    """
    return (f[n]-f[n-1]) / dx

def bd_df(f, n, dx):
    """
    Return the derivative of the central difference approximation of f at n, to the vector of f.
    """
    idxs = [n-1, n]
    vals = [-1/dx, 1/dx]

# 1D Bernoulli approximation codes
SEPARATION_FACTOR = 1.0000000000000000001

def fluid_pressure(x, fluid_props):
    """
    Computes the pressure loading at a series of surface nodes according to Pelorson (1994)

    Parameters
    ----------
    x : tuple of (u, v, a) each of (NUM_VERTICES, GEOMETRIC_DIM) np.ndarray
        States of the surface vertices, ordered following the flow (increasing x coordinate).
    fluid_props : dict
        A dictionary of fluid properties.

    Returns
    -------
    p : np.ndarray
        An array of pressure vectors for each each vertex
    xy_min, xy_sep: (2,) np.ndarray
        The coordinates of the vertices at minimum and separation areas
    """
    y_midline = fluid_props['y_midline']
    p_sup, p_sub = fluid_props['p_sup'], fluid_props['p_sub']
    rho = fluid_props['rho']
    a_sub = fluid_props['a_sub']

    # Calculate transverse plane areas using the y component of 'u' (aka x[0]) of the surface
    # and also minimum and separation locations
    area = 2 * (y_midline - x[0][:, 1])
    dt_area = -2 * (x[1][:, 1])

    ## Modify areas by limiting to a minimum value based on the buffer area; this prevents negative
    # areas due to collision
    # a_coll = 2*0.002

    # a_coll_buffer = 2.5 * a_coll
    # idx_coll = area < a_coll_buffer
    # blend_coll = (a_coll_buffer - area[idx_coll])/(a_coll_buffer-a_coll)
    # blend_area = (area[idx_coll]-a_coll)/(a_coll_buffer-a_coll)
    # dt_area_blend_factor = dt_area[idx_coll]/(a_coll_buffer-a_coll)
    # area[idx_coll] = blend_area*area[idx_coll] + blend_coll*a_coll
    # dt_area[idx_coll] = dt_area_blend_factor*a_coll

    # idx_coll = area < a_coll
    # area[idx_coll] = a_coll
    # dt_area[idx_coll] = 0

    # Calculate minimum and separation area locations
    idx_min = area.size-1-np.argmin(area[::-1])
    # idx_min = np.argmin(area)
    a_min = area[idx_min]
    dt_a_min = dt_area[idx_min]
    # The separation pressure is computed at the node before 'total' separation
    a_sep = SEPARATION_FACTOR * area[idx_min]
    idx_sep = np.argmax(np.logical_and(area >= a_sep, np.arange(area.size) > idx_min)) - 1
    dt_a_sep = SEPARATION_FACTOR * dt_a_min

    # 1D Bernoulli approximation of the flow
    p_sep = p_sup
    flow_rate_sqr = 2/rho*(p_sep - p_sub)/(a_sub**-2 - a_sep**-2)
    dt_flow_rate_sqr = 2/rho*(p_sep - p_sub)*-1*(a_sub**-2 - a_sep**-2)**-2 * (2*a_sep**-3 * dt_a_sep)

    p = p_sub + 1/2*rho*flow_rate_sqr*(1/a_sub**2 - 1/area**2)

    # Calculate the pressure along the separation edge
    # Separation happens inbetween vertex i and i+1, so adjust the bernoulli pressure at vertex i
    # based on where separation occurs
    # breakpoint()
    num = (a_sep - area[idx_sep])
    den = (area[idx_sep+1] - area[idx_sep])
    factor = num/den
    factor = 0

    separation = np.zeros(x[0].shape[0], dtype=np.bool)
    separation[idx_sep] = 1

    attached = np.ones(x[0].shape[0], dtype=np.bool)
    attached[idx_sep:] = 0

    p = attached*p + separation*factor*p[idx_sep]

    flow_rate = flow_rate_sqr**0.5
    dt_flow_rate = 0.5*flow_rate_sqr**(-0.5) * dt_flow_rate_sqr

    xy_min = x[0][idx_min]
    xy_sep = x[0][idx_sep]
    info = {'flow_rate': flow_rate,
            'dt_flow_rate': dt_flow_rate,
            'idx_min': idx_min,
            'idx_sep': idx_sep,
            'xy_min': xy_min,
            'xy_sep': xy_sep,
            'a_min': a_min,
            'a_sep': a_sep,
            'area': area,
            'pressure': p}
    return p, info

def get_pressure_form(model, x, fluid_props):
    """
    Returns the ufl.Coefficient pressure.

    Parameters
    ----------
    model : ufl.Coefficient
        The coefficient representing the pressure
    x : tuple of (u, v, a) each of (NUM_VERTICES, GEOMETRIC_DIM) np.ndarray
        States of the surface vertices, ordered following the flow (increasing x coordinate).
    fluid_props : dict
        A dictionary of fluid property keyword arguments.

    Returns
    -------
    xy_min, xy_sep :
        Locations of the minimum and separation areas, as well as surface pressures.
    """
    pressure = dfn.Function(model.scalar_function_space)

    pressure_vector, info = fluid_pressure(x, fluid_props)
    surface_verts = model.surface_vertices
    pressure.vector()[model.vert_to_sdof[surface_verts]] = pressure_vector

    return pressure, info

def flow_sensitivity(x, fluid_props):
    """
    Returns the sensitivities of flow properties at a surface state.

    Parameters
    ----------
    x : tuple of (u, v, a) each of (NUM_VERTICES, GEOMETRIC_DIM) np.ndarray
        States of the surface vertices, ordered following the flow (increasing x coordinate).
    fluid_props : dict
        A dictionary of fluid property keyword arguments.
    """
    y_midline = fluid_props['y_midline']
    p_sup, p_sub = fluid_props['p_sup'], fluid_props['p_sub']
    rho = fluid_props['rho']

    area = 2 * (y_midline - x[0][:, 1])
    darea_dy = -2 # darea_dx = 0

    # a_sub = area[0]
    a_sub = fluid_props['a_sub']

    idx_min = np.argmin(area)
    a_min = area[idx_min]

    a_sep = SEPARATION_FACTOR * a_min
    da_sep_da_min = SEPARATION_FACTOR
    idx_sep = np.argmax(np.logical_and(area >= a_sep, np.arange(area.size) > idx_min)) - 1

    # 1D Bernoulli approximation of the flow
    coeff = 2*(p_sup - p_sub)/rho
    flow_rate_sqr = coeff/(1/a_sub**2-1/a_sep**2)
    dflow_rate_sqr_da_sub = -coeff / (1/a_sub**2-1/a_sep**2)**2 * (-2/a_sub**3)
    dflow_rate_sqr_da_sep = -coeff / (1/a_sub**2-1/a_sep**2)**2 * (2/a_sep**3)

    assert x[0].size%2 == 0
    j_sep = 2*idx_sep + 1
    j_min = 2*idx_min + 1
    j_sub = 1

    ## Calculate the pressure sensitivity
    dp_du = np.zeros((x[0].size//2, x[0].size))
    for i in range(idx_sep+1):
        j = 2*i + 1

        # p[i] = p_sub + 1/2*rho*flow_rate_sqr*(1/a_sub**2 + 1/area[i]**2)
        dp_darea = 1/2*rho*flow_rate_sqr*(2/area[i]**3)
        dp_darea_sep = 1/2*rho*dflow_rate_sqr_da_sep*(1/a_sub**2 - 1/area[i]**2)
        dp_darea_sub = 1/2*rho*dflow_rate_sqr_da_sub*(1/a_sub**2 - 1/area[i]**2) \
                       + 1/2*rho*flow_rate_sqr*(-2/a_sub**3)

        dp_du[i, j] += dp_darea * darea_dy
        dp_du[i, j_min] += dp_darea_sep * da_sep_da_min * darea_dy
        dp_du[i, j_sub] += dp_darea_sub * darea_dy

    # Account for factor on separation pressure
    p_sep = p_sub + 1/2*rho*flow_rate_sqr*(1/a_sub**2 - 1/area[idx_sep]**2)
    p = p_sub + 1/2*rho*flow_rate_sqr*(1/a_sub**2 - 1/area**2)
    p_sep = p[idx_sep]
    dp_sep_du = dp_du[idx_sep, :]

    num = (a_sep - area[idx_sep])
    dnum_dy_min = da_sep_da_min*darea_dy
    dnum_dy_sep = -1*darea_dy

    den = (area[idx_sep+1] - area[idx_sep])
    dden_dy_sep1 = 1*darea_dy
    dden_dy_sep = -darea_dy

    factor = num/den

    dfactor_du = np.zeros(x[0].size)
    dfactor_du[j_min] += dnum_dy_min/den
    dfactor_du[j_sep] += dnum_dy_sep/den - num/den**2*dden_dy_sep
    dfactor_du[j_sep+2] = -num/den**2*dden_dy_sep1
    factor = 0
    dfactor_du = 0

    dp_du[idx_sep, :] = factor*dp_sep_du + dfactor_du*p_sep

    ## Calculate the flow rate sensitivity
    dflow_rate_du = np.zeros(x[0].size)
    dflow_rate_du[j_min] += dflow_rate_sqr_da_sep / (2*flow_rate_sqr**(1/2)) * da_sep_da_min * darea_dy
    dflow_rate_du[j_sub] += dflow_rate_sqr_da_sub / (2*flow_rate_sqr**(1/2)) * darea_dy

    #dp_du = pressure_sensitivity_ad(coordinates, fluid_props)

    return dp_du, dflow_rate_du

def get_flow_sensitivity(model, x, fluid_props):
    """
    Returns sparse matrices/vectors for the sensitivity of pressure and flow rate to displacement.

    Parameters
    ----------
    model
    x : tuple of (u, v, a) each of (NUM_VERTICES, GEOMETRIC_DIM) np.ndarray
        States of the surface vertices, ordered following the flow (increasing x coordinate).
    fluid_props : dict
        A dictionary of fluid properties.

    Returns
    -------
    dp_du : PETSc.Mat
        Sensitivity of pressure with respect to displacement
    dq_du : PETSc.Vec
        Sensitivity of flow rate with respect to displacement
    """
    _dp_du, _dq_du = flow_sensitivity(x, fluid_props)

    dp_du = PETSc.Mat().create(PETSc.COMM_SELF)
    dp_du.setType('aij')
    dp_du.setSizes([model.vert_to_sdof.size, model.vert_to_vdof.size])

    pressure_vertices = model.surface_vertices
    nnz = np.zeros(model.vert_to_sdof.size, dtype=np.int32)
    nnz[model.vert_to_sdof[pressure_vertices]] = pressure_vertices.size*2
    dp_du.setPreallocationNNZ(list(nnz))

    dp_du.setValues(model.vert_to_sdof[pressure_vertices],
                    model.vert_to_vdof[pressure_vertices].reshape(-1), _dp_du)
    dp_du.assemblyBegin()
    dp_du.assemblyEnd()

    # You should be able to create your own vector from scratch too but there are a couple of things
    # you have to set like local to global mapping that need to be there in order to interface with
    # a particular fenics setup. I just don't know what it needs to use.
    # TODO: Figure this out, since it also applies to matrices

    # dq_du = PETSc.Vec().create(PETSc.COMM_SELF).createSeq(vert_to_vdof.size)
    # dq_du.setValues(vert_to_vdof[surface_verts].reshape(-1), _dq_du)
    # dq_du.assemblyBegin()
    # dq_du.assemblyEnd()

    dq_du = dfn.Function(model.vector_function_space).vector()
    dq_du[model.vert_to_vdof[pressure_vertices].reshape(-1)] = _dq_du

    return dp_du, dq_du
