"""
Writes out vertex values from a statefile to xdmf
"""

from typing import Union, Tuple, Optional, List

import os
from os import path

from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from lxml import etree

import h5py
import numpy as np
import dolfin as dfn

from femvf.models.transient.base import BaseTransientModel

# from .. import statefile as sf

Model = BaseTransientModel

AxisSize = int
Shape = Tuple[AxisSize, ...]

AxisIndex = Union[int, slice, type(Ellipsis)]
AxisIndices = Tuple[AxisIndex, ...]

# This is a tuple consisting of:
# an `h5py.Dataset` object containing the data
# a string (eg. 'vector', 'scalar') indicating whether the data is vector/scalar
# a string (eg. 'node', 'center') indicating where data is located
XDMFValueType = str
XDMFValueCenter = str
DatasetDescription = Tuple[h5py.Dataset, XDMFValueType, XDMFValueCenter]

def xdmf_shape(shape: Shape) -> str:
    """
    Return a shape tuple as an XDMF string
    """
    return r' '.join(str(dim) for dim in shape)

class XDMFArray:
    """
    Represent an array as defined in the XDMF format

    Parameters
    ----------
    shape: Shape
        The shape of the array
    """

    def __init__(self, shape: Shape):
        self._shape = shape

    @property
    def shape(self) -> Shape:
        return self._shape

    @property
    def ndim(self) -> int:
        return len(self.shape)

    @staticmethod
    def expand_axis_indices(axis_indices: AxisIndices, ndim: int):
        """
        Expand any missing axis indices in an index tuple
        """
        assert axis_indices.count(Ellipsis) < 2

        # Here, we cut out a chunk `axis_indices[split_start:split_stop]`
        # and insert default 'slice(None)' slices to fill any missing axis
        # indices
        if Ellipsis in axis_indices:
            # This is the number of missing, explicit, axis indices
            ndim_expand = ndim - len(axis_indices) + 1
            # If an ellipsis exists, then add missing axis indices at the
            # ellipsis
            split_start = axis_indices.index(Ellipsis)
            split_stop = split_start+1
        else:
            # This is the number of missing, explicit, axis indices
            ndim_expand = ndim - len(axis_indices)
            # If no ellipsis exists, then add missing axis indices to the end
            split_start = len(axis_indices)
            split_stop = len(axis_indices)

        # Here add `[:]` slices to all missing axis indices
        expanded_axis_indices = (
            axis_indices[:split_start]
            + ndim_expand*(slice(None),)
            + axis_indices[split_stop:]
        )

        assert len(expanded_axis_indices) == ndim
        return expanded_axis_indices

    @staticmethod
    def get_start(axis_index: AxisIndex, axis_size: int):
        """
        Return the start of an axis index
        """
        if isinstance(axis_index, slice):
            if axis_index.start is None:
                start = 0
            else:
                start = axis_index.start
        elif isinstance(axis_index, int):
            start = axis_index
        elif axis_index is Ellipsis:
            raise TypeError("Invalid `Ellipsis` axis index")
        return start

    @staticmethod
    def get_stop(axis_index: AxisIndex, axis_size: int):
        """
        Return the stop of an axis index
        """
        if isinstance(axis_index, slice):
            if axis_index.stop is None:
                stop = axis_size
            else:
                stop = axis_index.stop
        elif isinstance(axis_index, int):
            stop = axis_index + 1
        elif axis_index is Ellipsis:
            raise TypeError("Invalid `Ellipsis` axis index")
        return stop

    @staticmethod
    def get_step(axis_index: AxisIndex, axis_size: int):
        """
        Return the step of an axis index
        """
        if isinstance(axis_index, slice):
            if axis_index.step is None:
                step = 1
            else:
                step = axis_index.step
        elif isinstance(axis_index, int):
            step = 1
        elif axis_index is Ellipsis:
            raise TypeError("Invalid `Ellipsis` axis index")
        return step

    def to_xdmf_slice(self, axis_indices: AxisIndices):
        axis_indices = self.expand_axis_indices(axis_indices, self.ndim)

        starts = [
            str(self.get_start(axis_index, axis_size))
            for axis_index, axis_size in zip(axis_indices, self.shape)
        ]
        steps = [
            str(self.get_step(axis_index, axis_size))
            for axis_index, axis_size in zip(axis_indices, self.shape)
        ]
        stops = [
            str(self.get_stop(axis_index, axis_size))
            for axis_index, axis_size in zip(axis_indices, self.shape)
        ]
        return starts, steps, stops

    def to_xdmf_slice_str(self, axis_indices: AxisIndices) -> str:
        """
        Return the XDMF array slice string representation of `index`
        """
        starts, steps, stops = self.to_xdmf_slice(axis_indices)
        col_widths = [
            max(len(start), len(step), len(stop))
            for start, step, stop in zip(starts, steps, stops)
        ]

        row = ' '.join([f'{{:>{width}s}}' for width in col_widths])
        return (
            row.format(*starts) + '\n'
            + row.format(*steps) + '\n'
            + row.format(*stops)
        )


def export_vertex_values(model, state_file, export_path, post_file=None):
    """
    Exports vertex values from a state file to another h5 file
    """
    solid = model.solid
    if os.path.isfile(export_path):
        os.remove(export_path)

    ## Input data
    with h5py.File(export_path, mode='w') as fo:

        ## Write the mesh and timing info out
        # TODO: Use consistents paths for storage
        fo.create_dataset(
            'mesh/solid/coordinates',
            data=state_file.file['mesh/solid/coordinates']
        )
        fo.create_dataset(
            'mesh/solid/connectivity',
            data=state_file.file['mesh/solid/connectivity']
        )
        fo.create_dataset(
            'mesh/solid/dim',
            data=state_file.file['mesh/solid/dim']
        )

        fo.create_dataset('time', data=state_file.file['time'])

        solid = model.solid
        fspace_dg0 = dfn.FunctionSpace(solid.residual.mesh(), 'DG', 0)
        fspace_cg1_scalar = solid.residual.form['coeff.fsi.p1'].function_space()
        fspace_cg1_vector = solid.residual.form['coeff.state.u1'].function_space()
        vert_to_sdof = dfn.vertex_to_dof_map(fspace_cg1_scalar)
        vert_to_vdof = dfn.vertex_to_dof_map(fspace_cg1_vector)

        ## Make empty functions to store vector values
        scalar_func = dfn.Function(fspace_cg1_scalar)
        vector_func = dfn.Function(fspace_cg1_vector)

        ## Prepare constant variables describing the shape
        N_TIME = state_file.size
        N_VERT = solid.residual.mesh().num_vertices()
        VECTOR_VALUE_SHAPE = tuple(vector_func.value_shape())
        SCALAR_VALUE_SHAPE = tuple(scalar_func.value_shape())

        ## Initialize solid/fluid state variables
        vector_labels = ['state/u', 'state/v', 'state/a']
        for label in vector_labels:
            fo.create_dataset(
                label, shape=(N_TIME, N_VERT, *VECTOR_VALUE_SHAPE),
                dtype=np.float64
            )

        scalar_labels = ['p']
        for label in scalar_labels:
            fo.create_dataset(
                label, shape=(N_TIME, N_VERT, *SCALAR_VALUE_SHAPE),
                dtype=np.float64
            )

        ## Write solid/fluid state variables in vertex order
        for ii in range(N_TIME):
            state = state_file.get_state(ii)
            model.set_fin_state(state)
            model.set_ini_state(state)

            u, v, a = state['u'], state['v'], state['a']
            for label, vector in zip(vector_labels, [u, v, a]):
                vector_func.vector()[:] = vector
                fo[label][ii, ...] = vector_func.vector()[vert_to_vdof].reshape(-1, *VECTOR_VALUE_SHAPE)

            p = model.solid.control['p']
            for label, scalar in zip(scalar_labels, [p]):
                scalar_func.vector()[:] = scalar
                fo[label][ii, ...] = scalar_func.vector()[vert_to_sdof].reshape((-1, *SCALAR_VALUE_SHAPE))

        ## Write (q, p) vertex values (pressure only defined)

        ## Write post-processed scalars
        if post_file is not None:
            labels = ['field.tavg_strain_energy', 'field.tavg_viscous_rate', 'field.vswell']
            for label in labels:
                fo[label] = post_file[label][:]


def write_xdmf(
        h5_fpath: str,
        static_dataset_descrs: List[DatasetDescription]=None,
        static_dataset_idxs: List[AxisIndices]=None,
        temporal_dataset_descrs: List[DatasetDescription]=None,
        temporal_dataset_idxs: List[AxisIndices]=None,
        xdmf_fpath: Optional[str]=None
    ):
    """
    Parameters
    ----------
    h5file_path : str
        path to a file with exported vertex values
    """
    # Set default empty data sets
    if static_dataset_descrs is None:
        static_dataset_descrs = []
    if static_dataset_idxs is None:
        static_dataset_idxs = []
    if temporal_dataset_descrs is None:
        temporal_dataset_descrs = []
    if temporal_dataset_idxs is None:
        temporal_dataset_idxs = []

    root_dir = path.split(h5_fpath)[0]

    with h5py.File(h5_fpath, mode='r') as f:

        root = Element('Xdmf')
        root.set('version', '2.0')

        domain = SubElement(root, 'Domain')

        ## Add info for a static grid
        grid = add_xdmf_uniform_grid(
            domain, 'Static',
            h5_fpath, f['mesh/solid'],
            h5_fpath, static_dataset_descrs, static_dataset_idxs
        )

        ## Add info for a time-varying Grid
        n_time = f['state/u'].shape[0]
        temporal_grid = SubElement(
            domain, 'Grid', {
                'GridType': 'Collection',
                'CollectionType': 'Temporal',
                'Name': 'Temporal'
            }
        )
        for ii in range(n_time):
            # Temporal dataset indices are assumed to apply to the non-time
            # axes and the time axis is assumed to be the first one
            _temporal_dataset_idxs = [
                (ii,)+idx for idx in temporal_dataset_idxs
            ]
            grid = add_xdmf_uniform_grid(
                temporal_grid, f'Time{ii}',
                h5_fpath, f['mesh/solid'],
                h5_fpath, temporal_dataset_descrs, _temporal_dataset_idxs,
                time=f['time'][ii]
            )

    ## Write the XDMF file
    lxml_root = etree.fromstring(ElementTree.tostring(root))
    etree.indent(lxml_root, space="    ")
    pretty_xml = etree.tostring(lxml_root, pretty_print=True)

    if xdmf_fpath is None:
        h5file_name = path.split(h5_fpath)[1]
        xdmf_fpath = f'{path.splitext(h5file_name)[0]}.xdmf'

    with open(path.join(root_dir, xdmf_fpath), 'wb') as fxml:
        fxml.write(pretty_xml)

def add_xdmf_uniform_grid(
        parent: Element,
        grid_name: str,
        mesh_h5_fpath: str, mesh_group: h5py.Group,
        dataset_h5_fpath: str, dataset_descrs: List[DatasetDescription],
        dataset_idxs: List[AxisIndices],
        time: float=None
    ):
    grid = SubElement(
        parent, 'Grid', {
            'GridType': 'Uniform',
            'Name': grid_name
        }
    )

    if time is not None:
        time = SubElement(
            grid, 'Time', {
                'TimeType': 'Single',
                'Value': f"{time}"
            }
        )

    # Write mesh info to grid
    with h5py.File(mesh_h5_fpath, mode='r') as f:
        mesh_dim = mesh_group['dim'][()]
        add_xdmf_grid_topology(
            grid, mesh_h5_fpath, mesh_group['connectivity'], mesh_dim
        )
        add_xdmf_grid_geometry(
            grid, mesh_h5_fpath, mesh_group['coordinates'], mesh_dim
        )

    # Write arrays to grid
    for (dataset, value_type, value_center), idx in zip(
            dataset_descrs, dataset_idxs
        ):
        add_xdmf_grid_array(
            grid, dataset.name, dataset_h5_fpath, dataset, idx,
            value_type=value_type, value_center=value_center
        )

    return grid

def add_xdmf_grid_topology(
        grid: Element, h5_fpath: str, dataset: h5py.Dataset, mesh_dim=2
    ):

    if mesh_dim == 3:
        topology_type = 'Tetrahedron'
    else:
        topology_type = 'Triangle'

    N_CELL = dataset.shape[0]

    topo = SubElement(
        grid, 'Topology', {
            'TopologyType': topology_type,
            'NumberOfElements': f'{N_CELL}'
        }
    )

    conn = SubElement(
        topo, 'DataItem', {
            'Name': 'MeshConnectivity',
            'ItemType': 'Uniform',
            'NumberType': 'Int',
            'Format': 'HDF',
            'Dimensions': xdmf_shape(dataset.shape)
        }
    )
    conn.text = f'{h5_fpath}:/mesh/solid/connectivity'

def add_xdmf_grid_geometry(
        grid: Element, h5_fpath: str, dataset: h5py.Dataset, mesh_dim=2
    ):
    if mesh_dim == 3:
        geometry_type = 'XYZ'
    else:
        geometry_type = 'XY'

    geom = SubElement(grid, 'Geometry', {'GeometryType': geometry_type})

    coords = SubElement(
        geom, 'DataItem', {
            'Name': 'MeshCoordinates',
            'ItemType': 'Uniform',
            'NumberType': 'Float',
            'Precision': '8',
            'Format': 'HDF',
            'Dimensions': xdmf_shape(dataset.shape)
        }
    )
    coords.text = f'{h5_fpath}:{dataset.name}'

def add_xdmf_grid_array(
        grid: Element,
        label: str,
        h5_fpath: str,
        dataset: h5py.Dataset,
        axis_indices: Optional[AxisIndices]=None,
        value_type='Vector',
        value_center='Node'
    ):
    comp = SubElement(
        grid, 'Attribute', {
            'Name': label,
            'AttributeType': value_type,
            'Center': value_center
        }
    )

    shape = dataset.shape

    data_subset = SubElement(
        comp, 'DataItem', {
            'ItemType': 'HyperSlab',
            'NumberType': 'Float',
            'Precision': '8',
            'Format': 'HDF',
            'Dimensions': xdmf_shape(dataset[axis_indices].shape)
        }
    )
    slice_sel = SubElement(
        data_subset, 'DataItem', {
            'Dimensions': f'3 {len(shape):d}',
            'Format': 'XML'
        }
    )
    xdmf_array = XDMFArray(shape)
    slice_sel.text = xdmf_array.to_xdmf_slice_str(axis_indices)

    slice_data = SubElement(
        data_subset, 'DataItem', {
            'Dimensions': xdmf_shape(shape),
            'Format': 'HDF'
        }
    )

    slice_data.text = f'{h5_fpath}:{dataset.name}'
    return comp

def add_xdmf_grid_finite_element_function(
        grid: Element,
        label: str,
        h5_fpath: str,
        dataset: h5py.Dataset,
        dataset_dofmap: h5py.Dataset,
        axis_indices: Optional[AxisIndices]=None,
        elem_family='CG', elem_degree=1, elem_cell='triangle',
        elem_value_type='vector'
    ):
    comp = SubElement(
        grid, 'Attribute', {
            'Name': label,
            'AttributeType': elem_value_type,
            'Center': 'Other',
            'ItemType': 'FiniteElementFunction',
            'ElementFamily': elem_family,
            'ElementDegree': elem_degree,
            'ElementCell': elem_cell
        }
    )

    dofmap = SubElement(
        comp, 'DataItem', {
            'Name': 'dofmap',
            'ItemType': 'Uniform',
            'NumberType': 'Int',
            'Format': 'HDF',
            'Dimensions': xdmf_shape(dataset_dofmap.shape)
        }
    )
    dofmap.text = f'{h5_fpath}:{dataset_dofmap.name}'

    data_subset = SubElement(
        comp, 'DataItem', {
            'ItemType': 'HyperSlab',
            'NumberType': 'Float',
            'Precision': '8',
            'Format': 'HDF',
            'Dimensions': xdmf_shape(dataset[axis_indices].shape)
        }
    )

    shape = dataset.shape
    slice_sel = SubElement(
        data_subset, 'DataItem', {
            'Dimensions': f'3 {len(shape)}',
            'Format': 'XML'
        }
    )
    xdmf_array = XDMFArray(shape)
    slice_sel.text = xdmf_array.to_xdmf_slice_str(axis_indices)

    slice_data = SubElement(
        data_subset, 'DataItem', {
            'Dimensions': xdmf_shape(shape),
            'Format': 'HDF'
        }
    )
    slice_data.text = f'{h5_fpath}:{label}'
