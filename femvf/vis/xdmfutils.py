"""
Writes out vertex values from a statefile to xdmf
"""

from typing import Union, Tuple, Optional, List, Callable

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
    def xdmf_shape(self) -> str:
        return r' '.join(str(dim) for dim in self.shape)

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

Format = Union[None, dfn.FunctionSpace]
def export_vertex_values(
        datasets: List[Union[h5py.Dataset, h5py.Group]],
        formats: List[Format],
        output_group: h5py.Group
    ):
    """
    Exports vertex values from a state file to another h5 file
    """
    for dataset_or_group, format in zip(datasets, formats):
        if isinstance(dataset_or_group, h5py.Dataset):
            dataset = dataset_or_group
            format_dataset = make_format_dataset(format)
            export_dataset(dataset, output_group, format_dataset=format_dataset)
        elif isinstance(dataset_or_group, h5py.Group):
            input_group = dataset_or_group
            export_group(input_group, output_group.create_group(input_group.name))
        else:
            raise TypeError()

FormatDataset = Callable[[h5py.Dataset], np.ndarray]
def make_format_dataset(
        data_format: Union[dfn.FunctionSpace, None]
    ) -> FormatDataset:
    if isinstance(data_format, dfn.FunctionSpace):
        vert_to_dof = dfn.vertex_to_dof_map(data_format)
        value_dim = data_format.num_sub_spaces()
        def format_dataset(dataset: h5py.Dataset):
            array = dataset[()][..., vert_to_dof]
            new_shape = (
                array.shape[:-1] + (array.shape[-1]//value_dim,) + (value_dim,)
            )
            array = np.reshape(array, new_shape)
            return array
    else:
        def format_dataset(dataset: h5py.Dataset):
            return dataset[()]
    return format_dataset

def export_dataset(
        input_dataset: h5py.Dataset,
        output_group: h5py.Group, output_dataset_name=None,
        format_dataset=None
    ):
    if output_dataset_name is None:
        output_dataset_name = input_dataset.name
    if format_dataset is None:
        format_dataset = lambda x: x

    dataset = output_group.create_dataset(
        output_dataset_name, data=format_dataset(input_dataset)
    )
    return dataset

def export_group(
        input_group: h5py.Group,
        output_group: h5py.Group,
        idx=None
    ):

    for key, dataset in input_group.items():
        if isinstance(dataset, h5py.Dataset):
            export_dataset(
                dataset, output_group, output_dataset_name=key,
                format_dataset=idx
            )
    return output_group


def write_xdmf(
        mesh_group: h5py.Group,
        static_dataset_descrs: List[DatasetDescription]=None,
        static_dataset_idxs: List[AxisIndices]=None,
        time_dataset: h5py.Dataset=None,
        temporal_dataset_descrs: List[DatasetDescription]=None,
        temporal_dataset_idxs: List[AxisIndices]=None,
        xdmf_name: Optional[str]=None
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

    root = Element('Xdmf')
    root.set('version', '2.0')

    domain = SubElement(root, 'Domain')

    ## Add info for a static grid
    grid = add_xdmf_uniform_grid(
        domain, 'Static',
        mesh_group,
        static_dataset_descrs, static_dataset_idxs
    )

    ## Add info for a time-varying Grid
    if time_dataset is not None:
        n_time = time_dataset.size
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
                mesh_group,
                temporal_dataset_descrs, _temporal_dataset_idxs,
                time=time_dataset[ii]
            )

    ## Write the XDMF file
    lxml_root = etree.fromstring(ElementTree.tostring(root))
    etree.indent(lxml_root, space="    ")
    pretty_xml = etree.tostring(lxml_root, pretty_print=True)

    if xdmf_name is None:
        h5file_name = path.split(mesh_group.file.filename)[-1]
        xdmf_fpath = f'{path.splitext(h5file_name)[0]}.xdmf'
    else:
        xdmf_fpath = f'{xdmf_name}.xdmf'

    with open(xdmf_fpath, 'wb') as fxml:
        fxml.write(pretty_xml)

def add_xdmf_uniform_grid(
        parent: Element,
        grid_name: str,
        mesh_group: h5py.Group,
        dataset_descrs: List[DatasetDescription],
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
    mesh_dim = mesh_group['dim'][()]
    add_xdmf_grid_topology(
        grid, mesh_group['connectivity'], mesh_dim
    )
    add_xdmf_grid_geometry(
        grid, mesh_group['coordinates'], mesh_dim
    )

    # Write arrays to grid
    for (dataset, value_type, value_center), idx in zip(
            dataset_descrs, dataset_idxs
        ):
        add_xdmf_grid_array(
            grid, dataset.name, dataset, idx,
            value_type=value_type, value_center=value_center
        )

    return grid

def add_xdmf_grid_topology(
        grid: Element, dataset: h5py.Dataset, mesh_dim=2
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

    xdmf_array = XDMFArray(dataset.shape)
    conn = SubElement(
        topo, 'DataItem', {
            'Name': 'MeshConnectivity',
            'ItemType': 'Uniform',
            'NumberType': 'Int',
            'Format': 'HDF',
            'Dimensions': xdmf_array.xdmf_shape
        }
    )
    conn.text = f'{dataset.file.filename}:/mesh/solid/connectivity'

def add_xdmf_grid_geometry(
        grid: Element, dataset: h5py.Dataset, mesh_dim=2
    ):
    if mesh_dim == 3:
        geometry_type = 'XYZ'
    else:
        geometry_type = 'XY'

    geom = SubElement(grid, 'Geometry', {'GeometryType': geometry_type})

    xdmf_array = XDMFArray(dataset.shape)
    coords = SubElement(
        geom, 'DataItem', {
            'Name': 'MeshCoordinates',
            'ItemType': 'Uniform',
            'NumberType': 'Float',
            'Precision': '8',
            'Format': 'HDF',
            'Dimensions': xdmf_array.xdmf_shape
        }
    )
    coords.text = f'{dataset.file.filename}:{dataset.name}'

def add_xdmf_grid_array(
        grid: Element,
        label: str,
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

    xdmf_array = XDMFArray(dataset[axis_indices].shape)
    data_subset = SubElement(
        comp, 'DataItem', {
            'ItemType': 'HyperSlab',
            'NumberType': 'Float',
            'Precision': '8',
            'Format': 'HDF',
            'Dimensions': xdmf_array.xdmf_shape
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
            'Dimensions': xdmf_array.xdmf_shape,
            'Format': 'HDF'
        }
    )

    slice_data.text = f'{dataset.file.filename}:{dataset.name}'
    return comp

def add_xdmf_grid_finite_element_function(
        grid: Element,
        label: str,
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

    xdmf_array = XDMFArray(dataset_dofmap.shape)
    dofmap = SubElement(
        comp, 'DataItem', {
            'Name': 'dofmap',
            'ItemType': 'Uniform',
            'NumberType': 'Int',
            'Format': 'HDF',
            'Dimensions': xdmf_array.xdmf_shape
        }
    )
    dofmap.text = f'{dataset_dofmap.file.filename}:{dataset_dofmap.name}'

    xdmf_array = XDMFArray(dataset[axis_indices].shape)
    data_subset = SubElement(
        comp, 'DataItem', {
            'ItemType': 'HyperSlab',
            'NumberType': 'Float',
            'Precision': '8',
            'Format': 'HDF',
            'Dimensions': xdmf_array.xdmf_shape
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
            'Dimensions': xdmf_array.xdmf_shape,
            'Format': 'HDF'
        }
    )
    slice_data.text = f'{dataset.file.filename}:{label}'
