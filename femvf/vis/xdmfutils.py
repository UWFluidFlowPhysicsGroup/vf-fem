"""
Writes out vertex values from a statefile to xdmf
"""

import os
from os import path

from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from lxml import etree

import h5py
import numpy as np
import dolfin as dfn

from .. import statefile as sf

def export_vertex_values(model, statefile_path, export_path):
    """
    Exports vertex values from a state file to another h5 file
    """
    solid = model.solid
    if os.path.isfile(export_path):
        os.remove(export_path)

    with sf.StateFile(model, statefile_path, mode='r') as fi:
        with h5py.File(export_path, mode='w') as fo:

            ## Write the mesh and timing info out
            fo.create_dataset('mesh/solid/coordinates', data=fi.file['mesh/solid/coordinates'])
            fo.create_dataset('mesh/solid/connectivity', data=fi.file['mesh/solid/connectivity'])

            fo.create_dataset('time', data=fi.file['time'])

            fspace_dg0 = model.residual.form['coeff.fsi.p1'].function_space()
            fspace_cg1 = model.residual.form['coeff.state.u0'].function_space()
            vert_to_sdof = dfn.vertex_to_dof_map(fspace_dg0)
            vert_to_vdof = dfn.vertex_to_dof_map(fspace_cg1)

            ## Make empty functions to store vector values
            scalar_func = dfn.Function(fspace_dg0)
            vector_func = dfn.Function(fspace_cg1)

            ## Prepare constant variables describing the shape
            N_TIME = fi.size
            N_VERT = solid.residual.mesh().num_vertices()
            VECTOR_VALUE_SHAPE = tuple(vector_func.value_shape())
            SCALAR_VALUE_SHAPE = tuple(scalar_func.value_shape())

            ## Initialize solid/fluid state variables
            labels = ['state/u', 'state/v', 'state/a']
            for label in labels:
                fo.create_dataset(label, shape=(N_TIME, N_VERT, *VECTOR_VALUE_SHAPE), dtype=np.float64)

            # for label in ['p']:
            #     fo.create_dataset(label, shape=(N_TIME, N_VERT, *SCALAR_VALUE_SHAPE), dtype=np.float64)

            ## Write solid/fluid state variables in vertex order
            for ii in range(N_TIME):
                state = fi.get_state(ii)

                u, v, a = state['u'], state['v'], state['a']
                for label, vector in zip(labels, [u, v, a]):
                    vector_func.vector()[:] = vector
                    fo[label][ii, ...] = vector_func.vector()[vert_to_vdof].reshape(-1, *VECTOR_VALUE_SHAPE)

                # p = state['p']
                # for label, vector in zip(['p'], [p]):
                #     scalar_func.vector()[:] = model.map_fsi_scalar_from_fluid_to_solid(p)
                #     fo[label][ii, ...] = scalar_func.vector()[vert_to_sdof].reshape((-1, *SCALAR_VALUE_SHAPE))

            ## Write (q, p) vertex values (pressure only defined)

def write_xdmf(model, h5file_path, xdmf_name=None):
    """
    Parameters
    ----------
    h5file_path : str
        path to a file with exported vertex values
    """

    root_dir = path.split(h5file_path)[0]
    h5file_name = path.split(h5file_path)[1]

    with h5py.File(h5file_path, mode='r') as f:

        N_TIME = f['state/u'].shape[0]
        N_VERT = f['mesh/solid/coordinates'].shape[0]
        N_CELL = f['mesh/solid/connectivity'].shape[0]

        # breakpoint()

        root = Element('Xdmf')
        root.set('version', '2.0')

        domain = SubElement(root, 'Domain')

        temporal_grid = SubElement(
            domain, 'Grid', {
                'GridType': 'Collection',
                'CollectionType': 'Temporal'
            }
        )

        for ii in range(N_TIME):
            ## Make the grid (they always reference the same h5 dataset)
            grid = SubElement(temporal_grid, 'Grid', {'GridType': 'Uniform'})

            time = SubElement(
                grid, 'Time', {
                    'TimeType': 'Single',
                    'Value': f"{f['time'][ii]}"
                }
            )

            ## Set the mesh topology

            # Handle options for 2D/3D meshes
            mesh = model.solid.residual.mesh()
            if mesh.topology().dim() == 3:
                topology_type = 'Tetrahedron'
                geometry_type = 'XYZ'
            else:
                topology_type = 'Triangle'
                geometry_type = 'XY'

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
                    'Dimensions': format_shape_tuple(f['mesh/solid/connectivity'].shape)
                }
            )
            conn.text = f'{h5file_name}:/mesh/solid/connectivity'

            geom = SubElement(grid, 'Geometry', {'GeometryType': geometry_type})

            coords = SubElement(
                geom, 'DataItem', {
                    'Name': 'MeshCoordinates',
                    'ItemType': 'Uniform',
                    'NumberType': 'Float',
                    'Precision': '8',
                    'Format': 'HDF',
                    'Dimensions': format_shape_tuple(f['mesh/solid/coordinates'].shape)
                }
            )
            coords.text = f'{h5file_name}:/mesh/solid/coordinates'

            ## Write u, v, a data to xdmf
            solid_labels = ['state/u', 'state/v', 'state/a']
            # solid_labels = []
            for label in solid_labels:

                ## This assumes the data is the raw fenics data

                # comp = SubElement(
                #     grid, 'Attribute', {
                #         'Name': label,
                #         'AttributeType': 'Vector',
                #         'Center': 'Other',
                #         'ItemType': 'FiniteElementFunction',
                #         'ElementFamily': 'CG',
                #         'ElementDegree': '1',
                #         'ElementCell': 'tetrahedron'
                #     }
                # )

                # dofmap = SubElement(
                #     comp, 'DataItem', {
                #         'Name': 'dofmap',
                #         'ItemType': 'Uniform',
                #         'NumberType': 'Int',
                #         'Format': 'HDF',
                #         'Dimensions': format_shape_tuple(f['dofmap/CG1'].shape)
                #     }
                # )
                # dofmap.text = f'{h5file_name}:dofmap/CG1'

                # data_subset = SubElement(
                #     comp, 'DataItem', {
                #         'ItemType': 'HyperSlab',
                #         'NumberType': 'Float',
                #         'Precision': '8',
                #         'Format': 'HDF',
                #         'Dimensions': format_shape_tuple(f[label][ii:ii+1, ...].shape)
                #     }
                # )

                # slice_sel = SubElement(
                #     data_subset, 'DataItem', {
                #         'Dimensions': '3 2',
                #         'Format': 'XML'
                #     }
                # )
                # slice_sel.text = (
                #     f"{ii} 0\n"
                #     "1 1\n"
                #     f"{ii+1} {f[label].shape[-1]}"
                # )

                # slice_data = SubElement(
                #     data_subset, 'DataItem', {
                #         'Dimensions': format_shape_tuple(f[label].shape),
                #         'Format': 'HDF'
                #     }
                # )
                # slice_data.text = f'{h5file_name}:{label}'

                ## This assumes data is in vertex order

                comp = SubElement(
                    grid, 'Attribute', {
                        'Name': label,
                        'AttributeType': 'Vector',
                        'Center': 'Node'
                    }
                )

                data_subset = SubElement(
                    comp, 'DataItem', {
                        'ItemType': 'HyperSlab',
                        'NumberType': 'Float',
                        'Precision': '8',
                        'Format': 'HDF',
                        'Dimensions': format_shape_tuple(f[label][ii:ii+1, ...].shape)
                    }
                )

                slice_sel = SubElement(
                    data_subset, 'DataItem', {
                        'Dimensions': '3 3',
                        'Format': 'XML'
                    }
                )

                slice_sel.text = (
                    f"{ii} 0 0\n"
                    "1 1 1\n"
                    f"1 {format_shape_tuple(f[label].shape[-2:])}"
                )

                slice_data = SubElement(
                    data_subset, 'DataItem', {
                        'Dimensions': format_shape_tuple(f[label].shape),
                        'Format': 'HDF'
                    }
                )
                slice_data.text = f'{h5file_name}:{label}'

            # Write q, p data to xdmf
            fluid_state_labels = ['state/q', 'state/p']
            fluid_state_labels = []
            for label in fluid_state_labels:
                comp = SubElement(
                    grid, 'Attribute', {
                        'Name': label,
                        'AttributeType': 'Scalar',
                        'Center': 'Node'
                    }
                )

                slice = SubElement(
                    comp, 'DataItem', {
                        'ItemType': 'HyperSlab',
                        'NumberType': 'Float',
                        'Precision': '8',
                        'Format': 'HDF',
                        'Dimensions': format_shape_tuple(f[label][ii:ii+1, ...].shape)
                    }
                )

                slice_sel = SubElement(
                    slice, 'DataItem', {
                        'Dimensions': '3 2',
                        'Format': 'XML'
                    }
                )
                slice_sel.text = f"{ii} 0\n1 1\n1 {format_shape_tuple(f[label].shape[-1:])}"

                slice_data = SubElement(
                    slice, 'DataItem', {
                        'Dimensions': format_shape_tuple(f[label].shape),
                        'Format': 'HDF'
                    }
                )
                slice_data.text = f'{h5file_name}:{label}'

    ## Write the XDMF file
    lxml_root = etree.fromstring(ElementTree.tostring(root))
    etree.indent(lxml_root, space="    ")
    pretty_xml = etree.tostring(lxml_root, pretty_print=True)

    if xdmf_name is None:
        xdmf_name = f'{path.splitext(h5file_name)[0]}.xdmf'

    with open(path.join(root_dir, xdmf_name), 'wb') as fxml:
        fxml.write(pretty_xml)

def format_shape_tuple(shape):
    """
    Return an array shape tuple as an XDMF formatted string
    """
    return r' '.join(str(dim) for dim in shape)
