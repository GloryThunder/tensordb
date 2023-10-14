import dask
import fsspec
import numpy as np
import pytest
import xarray as xr

from tensordb.storages import ZarrStorage


# TODO: Add more tests for the dataset cases


class TestZarrStorage:

    @pytest.fixture(autouse=True)
    def setup_tests(self, tmpdir):
        sub_path = tmpdir.strpath
        self.storage = ZarrStorage(
            base_map=fsspec.get_mapper(sub_path + '/zarr_storage'),
            tmp_map=fsspec.get_mapper(sub_path + '/tmp/zarr_storage'),
            data_names='data_test',
            chunks={'index': 3, 'columns': 2},
            # synchronizer='process',
            synchronize_only_write=True
        )
        self.storage_dataset = ZarrStorage(
            base_map=fsspec.get_mapper(sub_path + '/zarr_dataset'),
            tmp_map=fsspec.get_mapper(sub_path + '/tmp/zarr_dataset'),
            data_names=['a', 'b', 'c'],
            chunks={'index': 3, 'columns': 2},
            synchronizer='process',
            synchronize_only_write=True
        )
        self.storage_sorted_unique = ZarrStorage(
            base_map=fsspec.get_mapper(sub_path + '/zarr_sorted_unique'),
            tmp_map=fsspec.get_mapper(sub_path + '/tmp/zarr_sorted_unique'),
            data_names='data_test',
            chunks={'index': 3, 'columns': 2},
            unique_coords={"index": True, "columns": True},
            sorted_coords={'index': False, 'columns': False},
            # synchronizer='thread',
            synchronize_only_write=True
        )
        self.storage_dataset_sorted_unique = ZarrStorage(
            base_map=fsspec.get_mapper(sub_path + '/zarr_dataset_sorted_unique'),
            tmp_map=fsspec.get_mapper(sub_path + '/tmp/zarr_dataset_sorted_unique'),
            data_names=['a', 'b', 'c'],
            chunks={'index': 3, 'columns': 2},
            unique_coords={"index": True, "columns": True},
            sorted_coords={'index': False, 'columns': False},
            # synchronizer='process',
            synchronize_only_write=True
        )
        self.arr = xr.DataArray(
            data=np.array([
                [1, 2, 7, 4, 5],
                [2, 3, 5, 5, 6],
                [3, 3, 11, 5, 6],
                [4, 3, 10, 5, 6],
                [5, 7, 8, 5, 6],
            ], dtype=float),
            dims=['index', 'columns'],
            coords={'index': [0, 1, 2, 3, 4], 'columns': [0, 1, 2, 3, 4]},
        )

        self.arr2 = xr.DataArray(
            data=np.array([
                [1, 2, 7, 4, 5, 10, 13],
                [2, 3, 5, 5, 6, 11, 15],
                [2, 3, 5, 5, 6, 11, 15],
            ], dtype=float),
            dims=['index', 'columns'],
            coords={'index': [6, 7, 8], 'columns': [0, 1, 2, 3, 4, 5, 6]},
        )

        self.arr3 = xr.DataArray(
            data=np.array([
                [1, 2, 3, 4, 5],
            ], dtype=float),
            dims=['index', 'columns'],
            coords={'index': [5], 'columns': [0, 1, 2, 3, 4]},
        )

        self.arr4 = self.arr.astype(float) + 5
        self.arr5 = self.arr.astype(np.uint) + 3

        self.dataset = xr.Dataset(
            data_vars=dict(
                a=self.arr,
                b=self.arr4,
                c=self.arr5
            )
        )

    @pytest.mark.parametrize('keep_order', [True, False])
    def test_store_data(self, keep_order: bool):
        storage = self.storage_sorted_unique if keep_order else self.storage
        storage.store(self.arr2)
        if keep_order:
            assert storage.read().equals(
                self.arr2.sel(index=self.arr2.index[::-1], columns=self.arr2.columns[::-1])
            )
        else:
            assert storage.read().equals(self.arr2)
        storage.delete_tensor()

    @pytest.mark.parametrize('keep_order', [True, False])
    @pytest.mark.parametrize('as_dask', [True, False])
    def test_append_data(self, keep_order: bool, as_dask: bool):
        storage = self.storage_sorted_unique if keep_order else self.storage

        arr, arr2 = self.arr, self.arr2
        # TODO: Check why If the data is chunked and then stored in Zarr it add nan values
        if as_dask:
            arr, arr2 = arr.chunk((2, 3)), arr2.chunk((1, 4))

        for i in range(len(arr.index)):
            storage.append(arr.isel(index=[i]))

        for i in range(len(arr2.index)):
            storage.append(arr2.isel(index=[i]))

        total_data = xr.concat([arr, arr2], dim='index')

        if keep_order:
            assert storage.read().equals(
                total_data.sel(
                    index=total_data.index[::-1],
                    columns=total_data.columns[::-1]
                )
            )
        else:
            assert storage.read().equals(total_data)

        storage.delete_tensor()

    @pytest.mark.parametrize('keep_order', [True, False])
    @pytest.mark.parametrize('as_dask', [True, False])
    @pytest.mark.parametrize('only_diagonal_data', [True, False])
    @pytest.mark.parametrize('compute', [True, False])
    def test_append_diagonal(self, keep_order: bool, as_dask: bool, only_diagonal_data, compute):
        storage = self.storage_sorted_unique if keep_order else self.storage
        arr = self.arr
        if as_dask:
            arr = arr.chunk((2, 3))

        storage.store(arr)

        data = xr.DataArray(
            np.arange(16).reshape((4, 4)),
            dims=["index", "columns"],
            coords={
                "index": [5, 6, 7, 8], "columns": [5, 6, 7, 8]
            }
        )

        delayed = []
        if only_diagonal_data:
            for i in range(4):
                delayed.append(
                    storage.append(
                        data.isel(
                            index=[i],
                            columns=[i]
                        ),
                        compute=compute
                    )
                )
            diagonal = data.where(data.isin([0, 5, 10, 15]))
            expected = xr.concat([self.arr, diagonal], dim="index")
        else:
            delayed.append(storage.append(data, compute=compute))
            expected = xr.concat([self.arr, data], dim="index")

        if keep_order:
            expected = expected.sel(
                index=np.sort(expected.coords["index"])[::-1],
                columns=np.sort(expected.coords["columns"])[::-1]
            )

        if not compute:
            dask.compute(delayed)

        assert expected.equals(storage.read())
        storage.delete_tensor()

    @pytest.mark.parametrize('as_dask', [True, False])
    @pytest.mark.parametrize('index', [
        [0, 2, 4],
        [2, 4],
        [1, 4]
    ])
    @pytest.mark.parametrize('columns', [
        [1, 3, 4],
        [1, 4],
        [0, 3]
    ])
    def test_update_data(self, as_dask, index, columns):
        self.storage.store(self.arr)

        expected = self.arr.copy()

        for i, v in enumerate(index):
            expected.loc[v, columns] = i

        if as_dask:
            expected = expected.chunk((2, 1))

        self.storage.update(expected.sel(index=index, columns=columns))

        assert self.storage.read().equals(expected)

    def test_update_complete_data(self):
        self.storage.store(self.arr)

        arr_sliced = self.arr.sel(index=slice(2, None), columns=[0, 1, 3]) + 5
        self.storage.update(arr_sliced, complete_update_dims=["columns"])

        self.arr.loc[2:] = arr_sliced.reindex(columns=self.arr.columns)

        assert self.storage.read().equals(self.arr)

    @pytest.mark.parametrize('keep_order', [True, False])
    def test_store_dataset(self, keep_order: bool):
        storage_dataset = self.storage_dataset_sorted_unique if keep_order else self.storage_dataset
        storage_dataset.store(self.dataset)

        if keep_order:
            assert storage_dataset.read().equals(
                self.dataset.sel(index=self.dataset.index[::-1], columns=self.dataset.columns[::-1])
            )
        else:
            assert storage_dataset.read().equals(self.dataset)

    @pytest.mark.parametrize('keep_order', [True, False])
    def test_append_dataset(self, keep_order: bool):
        storage_dataset = self.storage_dataset_sorted_unique if keep_order else self.storage_dataset
        storage_dataset.store(self.dataset)

        dataset = self.dataset.reindex(
            index=list(self.dataset.index.values) + [self.dataset.index.values[-1] + 1],
            fill_value=1
        )
        storage_dataset.append(dataset.isel(index=[-1]))
        if keep_order:
            assert storage_dataset.read().equals(
                dataset.sel(index=dataset.index[::-1], columns=dataset.columns[::-1])
            )
        else:
            assert storage_dataset.read().equals(dataset)

    def test_update_dataset(self):
        self.storage_dataset.store(self.dataset)

        expected = xr.concat([
            self.dataset.sel(index=slice(0, 1)),
            self.dataset.sel(index=slice(2, None)) + 5
        ], dim='index')
        self.storage_dataset.update(expected.sel(index=slice(2, None)))
        assert self.storage_dataset.read().equals(expected)

    def test_drop_data(self):
        self.storage.store(self.arr)
        coords = {'index': [0, 2, 4], 'columns': [1, 3]}
        self.storage.drop(coords)
        assert self.storage.read().equals(
            self.arr.drop_sel(coords)
        )

    def test_keep_sorted(self):
        arr = self.arr.chunk((3, 2))
        new_data = arr.sel(index=[3, 2, 0, 4, 1], columns=[3, 4, 2, 0, 1])
        result = self.storage_sorted_unique._keep_sorted_coords(new_data=new_data)
        assert result.chunks == ((1, 1, 1, 1, 1), (1, 1, 1, 2))

        new_data = arr.sel(columns=[3, 4, 2, 0, 1], index=[4, 3, 2, 1, 0])
        result = self.storage_sorted_unique._keep_sorted_coords(new_data=new_data)
        assert result.chunks == ((2, 3), (5,))


if __name__ == "__main__":
    test = TestZarrStorage()
    # test.test_store_data()
    # test.test_append_data(remote=False)
    # test.test_update_data()
    # test.test_backup()
