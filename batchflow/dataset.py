""" Dataset """

import numpy as np
from .base import Baseset
from .batch import Batch
from .dsindex import DatasetIndex
from .pipeline import Pipeline


class Dataset(Baseset):
    """
    The Dataset holds an index of all data items
    (e.g. customers, transactions, etc)
    and a specific action class to process a small subset of data (batch).

    Attributes
    ----------
    batch_class : Batch

    index : DatasetIndex or FilesIndex

    indices : class:`numpy.ndarray`
        an array with the indices

    is_split: bool
        True if dataset has been split into train / test / validation subsets

    p : Pipeline
        Actions which will be applied to this dataset

    preloaded : data-type
        For small dataset it could be convenient to preload data at first

    train : Dataset
        The train part of this dataset. It appears after splitting

    test : Dataset
        The test part of this dataset. It appears after splitting

    validation : Dataset
        The validation part of this dataset. It appears after splitting
    """
    def __init__(self, index, batch_class=Batch, preloaded=None, *args, **kwargs):
        """ Create Dataset

            Parameters
            ----------
            index : DatasetIndex or FilesIndex or int
                Stores an index for a dataset

            batch_class : Batch or inherited-from-Batch
                Batch class holds the data and contains processing functions

            preloaded : data-type
                For smaller dataset it might be convenient to preload all data at once
                As a result, all created batches will contain a portion of some_data.
        """
        super().__init__(index, *args, **kwargs)
        self.batch_class = batch_class
        self.preloaded = preloaded

    @classmethod
    def from_dataset(cls, dataset, index, batch_class=None):
        """ Create Dataset object from another dataset with a new index
            (usually a subset of the source dataset index)

            Parameters
            ----------
            dataset : Dataset
                Source dataset

            index : DatasetIndex
                Set of items from source dataset which should be in the new Dataset

            batch_class : Batch
                type of Batch for the new Dataset

            Returns
            -------
            Dataset
        """
        if (batch_class is None or (batch_class == dataset.batch_class)) and cls._is_same_index(index, dataset.index):
            return dataset
        bcl = batch_class if batch_class is not None else dataset.batch_class
        return cls(index, batch_class=bcl, preloaded=dataset.preloaded)

    @staticmethod
    def build_index(index):
        """ Check if instance of the index is DatasetIndex
            if it is not - create DatasetIndex from input index

            Parameters
            ----------
            index : DatasetIndex or any

            Returns
            -------
            DatasetIndex
        """
        if isinstance(index, DatasetIndex):
            return index
        return DatasetIndex(index)

    @staticmethod
    def _is_same_index(index1, index2):
        """ Check if index1 and index2 are equals

            Parameters
            ----------
            index1 : DatasetIndex

            index2 : DatasetIndex

            Returns
            -------
            bool
        """
        return (isinstance(index1, type(index2)) or isinstance(index2, type(index1))) and \
               index1.indices.shape == index2.indices.shape and \
               np.all(index1.indices == index2.indices)

    def create_subset(self, index):
        """ Create a dataset based on the given subset of indices

            Parameters
            ----------
            index : DatasetIndex

            Returns
            -------
            Dataset

            Raises
            ------
            IndexError
                When a user wants to create a subset from source dataset it is necessary to be confident
                that the index of new subset lies in the range of source dataset's index.
                If the index lies out of the source dataset index's range, the IndexError raises.

        """
        if not np.isin(index.indices, self.indices).all():
            raise IndexError
        return type(self).from_dataset(self, index)

    def create_batch(self, index, pos=False, *args, **kwargs):
        """ Create a batch from given indices.

            Parameters
            ----------
            index : DatasetIndex
                DatasetIndex object which consists of mast be included to the batch elements

            pos : bool
                Flag, which shows does index contain positions of elements or indices

            Returns
            -------
            Batch

            Notes
            -----
            if `pos` is `False`, then `index` should contain the indices
            that should be included in the batch
            otherwise `index` should contain their positions in the current index
        """
        if not isinstance(index, DatasetIndex):
            index = self.index.create_batch(index, pos, *args, **kwargs)
        return self.batch_class(index, preloaded=self.preloaded, **kwargs)

    def pipeline(self, config=None):
        """ Start a new data processing workflow

            Parameters
            ----------
            config : Config or dict
                Config lets you initialize variables in the Pipeline object, e.g. for the augmentation task
                https://analysiscenter.github.io/batchflow/intro/pipeline.html#initializing-a-variable

            Returns
            -------
            Pipeline
        """
        return Pipeline(self, config=config)

    @property
    def p(self):
        """A short alias for `pipeline()` """
        return self.pipeline()

    def __rshift__(self, other):
        """
            Parameters
            ----------
            other : Pipeline

            Returns
            -------
            Pipeline
                Pipeline object which now has Dataset object as attribute

            Raises
            ------
            TypeError
                If the type of other is not a Pipeline
        """
        if not isinstance(other, Pipeline):
            raise TypeError("Pipeline is expected, but got %s. Use as dataset >> pipeline" % type(other))
        return other << self