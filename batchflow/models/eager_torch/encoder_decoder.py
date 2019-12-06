""" Encoder, decoder, encoder-decoder architectures. """
import torch
import torch.nn as nn

from .base import EagerTorch
from .utils import get_shape
from .layers import ConvBlock, Upsample, Combine, Crop
from .blocks import DefaultBlock
from ..utils import unpack_args



class EncoderModule(nn.Module):
    """ Encoder: create compressed representation of an input by reducing its spatial dimensions. """
    def __init__(self, inputs=None, return_all=True, **kwargs):
        super().__init__()
        self.return_all = return_all
        self._make_modules(inputs, **kwargs)

    def forward(self, x):
        b_counter, d_counter = 0, 0
        outputs = []

        for _ in range(self.num_stages):
            for letter in self.encoder_layout:
                if letter in ['b']:
                    x = self.encoder_b[b_counter](x)
                    b_counter += 1
                elif letter in ['d', 'p']:
                    x = self.encoder_d[d_counter](x)
                    d_counter += 1
                elif letter in ['s']:
                    outputs.append(x)
        outputs.append(x)

        if self.return_all:
            return outputs
        return outputs[-1]


    def _make_modules(self, inputs, **kwargs):
        num_stages = kwargs.pop('num_stages')
        encoder_layout = ''.join([item[0] for item in kwargs.pop('order')])
        self.num_stages, self.encoder_layout = num_stages, encoder_layout

        block_args = kwargs.pop('blocks')
        downsample_args = kwargs.pop('downsample')

        self.encoder_b, self.encoder_d = nn.ModuleList(), nn.ModuleList()

        for i in range(num_stages):
            for letter in encoder_layout:
                if letter in ['b']:
                    args = {**kwargs, **block_args, **unpack_args(block_args, i, num_stages)}

                    layer = ConvBlock(inputs=inputs, **args)
                    inputs = layer(inputs)
                    self.encoder_b.append(layer)
                elif letter in ['d', 'p']:
                    args = {**kwargs, **downsample_args, **unpack_args(downsample_args, i, num_stages)}

                    layer = ConvBlock(inputs=inputs, **args)
                    inputs = layer(inputs)
                    self.encoder_d.append(layer)
                elif letter in ['s']:
                    pass
                else:
                    raise ValueError('BAD', letter)



class EmbeddingModule(nn.Module):
    """ Embedding: thorough processing of an input tensor. """
    def __init__(self, inputs=None, **kwargs):
        super().__init__()
        inputs = inputs[-1] if isinstance(inputs, list) else inputs
        kwargs = {'layout': 'cna', 'filters': 'same', **kwargs}
        self.embedding = ConvBlock(inputs=inputs, **kwargs)

    def forward(self, x):
        inputs = x if isinstance(x, list) else [x]
        x = inputs[-1]
        inputs.append(self.embedding(x))
        return inputs



class DecoderModule(nn.Module):
    """ Decoder: increasing spatial dimensions. """
    def __init__(self, inputs=None, **kwargs):
        super().__init__()
        self._make_modules(inputs, **kwargs)

    def forward(self, x):
        b_counter, u_counter, c_counter = 0, 0, 0
        inputs = x if isinstance(x, list) else [x]
        x = inputs[-1]

        for i in range(self.num_stages):
            for letter in self.decoder_layout:
                if letter in ['b']:
                    x = self.decoder_b[b_counter](x)
                    b_counter += 1
                elif letter in ['u']:
                    x = self.decoder_u[u_counter](x)
                    u_counter += 1
                elif letter in ['c']:
                    if self.skip and (i < len(inputs) - 2):
                        x = self.decoder_c[c_counter]([inputs[-i - 3], x])
                        c_counter += 1
        return x


    def _make_modules(self, inputs, **kwargs):
        inputs = inputs if isinstance(inputs, list) else [inputs]
        x = inputs[-1]

        num_stages = kwargs.pop('num_stages') or len(inputs) - 2
        decoder_layout = ''.join([item[0] for item in kwargs.pop('order')])
        self.num_stages, self.decoder_layout = num_stages, decoder_layout

        skip = kwargs.pop('skip')
        self.skip = skip

        factor = kwargs.pop('factor') or [2]*num_stages
        if isinstance(factor, int):
            factor = int(factor ** (1/num_stages))
            factor = [factor] * num_stages
        elif not isinstance(factor, list):
            raise TypeError('factor should be int or list of int, but %s was given' % type(factor))

        block_args = kwargs.pop('blocks')
        upsample_args = kwargs.pop('upsample')
        combine_args = kwargs.pop('combine')

        self.decoder_b, self.decoder_u, self.decoder_c = nn.ModuleList(), nn.ModuleList(), nn.ModuleList()

        for i in range(num_stages):
            for letter in decoder_layout:
                if letter in ['b']:
                    args = {'layout': 'cna', 'filters': 'same // 2',
                            **kwargs, **block_args, **unpack_args(block_args, i, num_stages)}

                    layer = ConvBlock(inputs=x, **args)
                    x = layer(x)
                    self.decoder_b.append(layer)
                elif letter in ['u']:
                    args = {'factor': factor[i],
                            **kwargs, **upsample_args, **unpack_args(upsample_args, i, num_stages)}

                    layer = Upsample(inputs=x, **args)
                    x = layer(x)
                    self.decoder_u.append(layer)
                elif letter in ['c']:
                    args = {**kwargs, **combine_args, **unpack_args(combine_args, i, num_stages)}

                    if skip and (i < len(inputs) - 2):
                        layer = Combine(inputs=[inputs[-i - 3], x])
                        x = layer([inputs[-i - 3], x])
                        self.decoder_c.append(layer)
                else:
                    raise ValueError('BAD')



class Encoder(EagerTorch):
    """ Encoder architecture. Allows to combine blocks from different models,
    e.g. ResNet and DenseNet, in order to create new ones with just a few lines of code.
    Intended to be used for classification tasks.

    Parameters
    ----------
    body : dict
        encoder : dict, optional
            num_stages : int
                Number of downsampling stages.

            order : str, sequence of str
                Determines order of applying layers.
                If str, then each letter stands for operation:
                'b' for 'block', 'd'/'p' for 'downsampling', 's' for 'skip'.
                If sequence, than the first letter of each item stands for operation:
                For example, `'sbd'` allows to use throw skip connection -> block -> downsampling.

            downsample : dict, optional
                Parameters for downsampling (see :class:`~.layers.ConvBlock`)

            blocks : dict, optional
                Parameters for pre-processing blocks.

                base : callable
                    Tensor processing function. Default is :class:`~.layers.ConvBlock`.
                other args : dict
                    Parameters for the base block.
    """
    @classmethod
    def default_config(cls):
        config = super().default_config()

        config['body/encoder'] = dict(num_stages=None,
                                      order=['skip', 'block', 'downsampling'])
        config['body/encoder/downsample'] = dict(layout='p', pool_size=2, pool_strides=2)
        config['body/encoder/blocks'] = dict(base=DefaultBlock)
        return config

    @classmethod
    def body(cls, inputs, **kwargs):
        kwargs = cls.get_defaults('body', kwargs)
        encoder = kwargs.pop('encoder')
        return EncoderModule(inputs=inputs, return_all=False, **{**kwargs, **encoder})



class Decoder(EagerTorch):
    """ Decoder architecture. Allows to combine blocks from different models,
    e.g. ResNet and DenseNet, in order to create new ones with just a few lines of code.
    Intended to be used for increasing spatial dimensionality of inputs.

    Parameters
    ----------
    body : dict
        decoder : dict, optional
            num_stages : int
                Number of upsampling blocks.

            factor : int or list of int
                If int, the total upsampling factor for all stages combined.
                If list, upsampling factors for each stage.

            skip : bool, dict
                If bool, then whether to combine upsampled tensor with stored pre-downsample encoding by
                using `combine` parameters that can be specified for each of blocks separately.

            order : str, sequence of str
                Determines order of applying layers.
                If str, then each letter stands for operation:
                'b' for 'block', 'u' for 'upsampling', 'c' for 'combine'
                If sequence, than the first letter of each item stands for operation.
                For example, `'ucb'` allows to use upsampling -> combine -> block.

            upsample : dict
                Parameters for upsampling (see :class:`~.layers.Upsample`).

            blocks : dict
                Parameters for post-processing blocks:

                base : callable
                    Tensor processing function. Default is :class:`~.layers.ConvBlock`.
                other args : dict
                    Parameters for the base block.

            combine : dict
                If dict, then parameters for combining tensors, see :class:`~.layers.Combine`.

    head : dict, optional
        Parameters for the head layers, usually :class:`~.layers.ConvBlock` parameters. Note that an extra 1x1
        convolution may be applied in order to make predictions compatible with the shape of the targets.
    """
    @classmethod
    def default_config(cls):
        config = super().default_config()

        config['body/decoder'] = dict(skip=True, num_stages=None, factor=None,
                                      order=['upsampling', 'block', 'combine'])
        config['body/decoder/upsample'] = dict(layout='tna')
        config['body/decoder/blocks'] = dict(base=None)
        config['body/decoder/combine'] = dict(op='concat')
        return config


    @classmethod
    def body(cls, inputs, **kwargs):
        kwargs = cls.get_defaults('body', kwargs)
        decoder = kwargs.pop('decoder')
        return DecoderModule(inputs=inputs, **{**kwargs, **decoder})

    @classmethod
    def head(cls, inputs, target_shape, classes, **kwargs):
        kwargs = cls.get_defaults('head', kwargs)
        layers = []
        layer = super().head(inputs, target_shape, classes, **kwargs)
        if layer is not None:
            inputs = layer(inputs)
            layers.append(layer)

        if target_shape:
            if get_shape(inputs) != target_shape:
                layer = Crop(resize_to=target_shape)
                inputs = layer(inputs)
                layers.append(layer)

                if get_shape(inputs)[1] != classes:
                    layer = ConvBlock(inputs=inputs, layout='c', filters=classes, kernel_size=1)
                    layers.append(layer)
        return nn.Sequential(*layers)



class EncoderDecoder(Decoder):
    """ Encoder-decoder architecture. Allows to combine blocks from different models,
    e.g. ResNet and DenseNet, in order to create new ones with just a few lines of code.
    Intended to be used for segmentation tasks.

    Parameters
    ----------
    body : dict
        encoder : dict, optional
            num_stages : int
                Number of downsampling stages.

            order : str, sequence of str
                Determines order of applying layers.
                If str, then each letter stands for operation:
                'b' for 'block', 'd'/'p' for 'downsampling', 's' for 'skip'.
                If sequence, than the first letter of each item stands for operation:
                For example, `'sbd'` allows to use throw skip connection -> block -> downsampling.

            downsample : dict, optional
                Parameters for downsampling (see :class:`~.layers.ConvBlock`)

            blocks : dict, optional
                Parameters for pre-processing blocks.

                base : callable
                    Tensor processing function. Default is :class:`~.layers.ConvBlock`.
                other args : dict
                    Parameters for the base block.

        embedding : dict or None, optional
            If None no embedding block is created.
            If dict, then parameters for tensor processing function.

            base : callable
                Tensor processing function. Default is :class:`~.layers.ConvBlock`.
            other args
                Parameters for the base block.

        decoder : dict, optional
            num_stages : int
                Number of upsampling blocks.

            factor : int or list of int
                If int, the total upsampling factor for all stages combined.
                If list, upsampling factors for each stage.

            skip : bool, dict
                If bool, then whether to combine upsampled tensor with stored pre-downsample encoding by
                using `combine` parameters that can be specified for each of blocks separately.

            order : str, sequence of str
                Determines order of applying layers.
                If str, then each letter stands for operation:
                'b' for 'block', 'u' for 'upsampling', 'c' for 'combine'
                If sequence, than the first letter of each item stands for operation.
                For example, `'ucb'` allows to use upsampling -> combine -> block.

            upsample : dict
                Parameters for upsampling (see :class:`~.layers.Upsample`).

            blocks : dict
                Parameters for post-processing blocks:

                base : callable
                    Tensor processing function. Default is :class:`~.layers.ConvBlock`.
                other args : dict
                    Parameters for the base block.

            combine : dict
                If dict, then parameters for combining tensors, see :class:`~.layers.Combine`.

    head : dict, optional
        Parameters for the head layers, usually :class:`~.layers.ConvBlock` parameters. Note that an extra 1x1
        convolution may be applied in order to make predictions compatible with the shape of the targets.

    Examples
    --------
    Use ResNet as an encoder with desired number of blocks and filters in them (total downsampling factor is 4),
    create an embedding that contains 256 channels, then upsample it to get 8 times the size of initial image.

    >>> config = {
            'inputs': dict(images={'shape': B('image_shape')},
                           masks={'name': 'targets', 'shape': B('mask_shape')}),
            'initial_block/inputs': 'images',
            'body/encoder': {'base': ResNet,
                             'num_blocks': [2, 3, 4]
                             'filters': [16, 32, 128]},
            'body/embedding': {'layout': 'cna', 'filters': 256},
            'body/decoder': {'num_stages': 5, 'factor': 32},
        }

    Preprocess input image with 7x7 convolutions, downsample it 5 times with DenseNet blocks in between,
    use MobileNet block in the bottom, then restore original image size with subpixel convolutions and
    ResNeXt blocks in between:

    >>> config = {
            'inputs': dict(images={'shape': B('image_shape')},
                           masks={'name': 'targets', 'shape': B('mask_shape')}),
            'initial_block': {'inputs': 'images',
                              'layout': 'cna', 'filters': 4, 'kernel_size': 7},
            'body/encoder': {'num_stages': 5,
                             'blocks': {'base': DenseNet.block,
                                        'num_layers': [2, 2, 3, 4, 5],
                                        'growth_rate': 6, 'skip': True}},
            'body/embedding': {'base': MobileNet.block,
                               'width_factor': 2},
            'body/decoder': {'upsample': {'layout': 'X'},
                             'blocks': {'base': ResNet.block,
                                        'filters': [256, 128, 64, 32, 16],
                                        'resnext': True}},
        }
    """
    @classmethod
    def default_config(cls):
        config = super().default_config()

        config['body/encoder'] = dict(num_stages=None,
                                      order=['skip', 'block', 'downsampling'])
        config['body/encoder/downsample'] = dict(layout='p', pool_size=2, pool_strides=2)
        config['body/encoder/blocks'] = dict(base=DefaultBlock)

        config['body/embedding'] = dict(base=None)

        config['body/decoder'] = dict(skip=True, num_stages=None, factor=None,
                                      order=['upsampling', 'block', 'combine'])
        config['body/decoder/upsample'] = dict(layout='tna')
        config['body/decoder/blocks'] = dict(base=None)
        config['body/decoder/combine'] = dict(op='concat')
        return config


    @classmethod
    def body(cls, inputs, **kwargs):
        kwargs = cls.get_defaults('body', kwargs)
        encoder = kwargs.pop('encoder')
        embedding = kwargs.pop('embedding')
        decoder = kwargs.pop('decoder')

        layers = []
        encoder = cls.encoder(inputs=inputs, **{**kwargs, **encoder})
        encoder_outputs = encoder(inputs)
        layers.append(encoder)

        if embedding is not None:
            embedding = cls.embedding(inputs=encoder_outputs, **{**kwargs, **embedding})
        else:
            embedding = nn.Identity()
        encoder_outputs = embedding(encoder_outputs)
        layers.append(embedding)

        decoder = cls.decoder(inputs=encoder_outputs, **{**kwargs, **decoder})
        layers.append(decoder)

        return nn.Sequential(*layers)

    @classmethod
    def encoder(cls, inputs, **kwargs):
        return EncoderModule(inputs=inputs, **kwargs)

    @classmethod
    def embedding(cls, inputs, **kwargs):
        return EmbeddingModule(inputs=inputs, **kwargs)

    @classmethod
    def decoder(cls, inputs, **kwargs):
        return DecoderModule(inputs=inputs, **kwargs)



class AutoEncoder(EncoderDecoder):
    """ Model without skip-connections between corresponding stages of encoder and decoder. """
    @classmethod
    def default_config(cls):
        config = super().default_config()
        config['body/decoder'] += dict(skip=False)
        return config



class VariationalBlock(nn.Module):
    """ Reparametrization trick block. """
    def __init__(self, inputs=None, base_mu=None, base_std=None, **kwargs):
        super().__init__()
        self.mean = base_mu(inputs=inputs, **kwargs)
        self.std = base_std(inputs=inputs, **kwargs)

    def forward(self, x):
        mean = self.mean(x)
        std = self.std(x)
        return mean + std * torch.randn_like(std)


class VariationalAutoEncoder(AutoEncoder):
    """ Autoencoder that maps input into distribution. Based on
    Kingma, Diederik P; Welling, Max "`Auto-Encoding Variational Bayes
    <https://arxiv.org/abs/1312.6114>`_"

    Notes
    -----
    Distribution that is learned is always normal.
    """
    @classmethod
    def default_config(cls):
        config = super().default_config()
        config['body/embedding'] += dict(base=VariationalBlock, base_mu=None, base_std=None)
        return config
