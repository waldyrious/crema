#!/usr/bin/env python
'''crema data layer'''

import numpy as np
import six
import jams
import pescador
import shove


def init_cache(uri):
    '''Instantiate a feature cache with shove`

    Parameters
    ----------
    uri : str
        See shove.Shove() for details
    '''

    return shove.Shove(uri)


def jams_mapping(jams_in, task_map):
    '''Convert jams annotations to crema outputs.

    Given a jams file and a collection of TaskTransformers,
    each TaskTransformer is applied to the jams annotations,
    and the results are collected in a single dictionary.

    All data is cast to a numpy array, and reshaped to have a new
    batch axis 0.

    Parameters
    ----------
    jams_in : str or file-like
        path to a jams object.  See ``jams.load`` for acceptable formats

    task_map: iterable of BaseTaskTransformers
        The task transformation objects to apply

    Returns
    -------
    output : dict
        All task transformer outputs, collected in one dictionary
        and reshaped.
    '''
    jam = jams.load(jams_in)

    output = {}
    for task in task_map:
        for key, value in six.iteritems(task.transform(jam)):
            output[key] = np.asarray(value)[np.newaxis]

    return output


def slice_data(data, sample):
    '''Slice a feed_dict down to a specified slice.

    Parameters
    ----------
    data : dict
        As returned by ``make_task_data``

    sample : slice
        A slice indicating the window to extract

    Returns
    -------
    sample : dict
        For each key in data:
          If ``ndim > 2`` then ``sample[key] = data[key][sl]``.
          Otherwise, ``sample[key] == data[key]``.
    '''

    data_slice = dict()

    for key in data:
        if data[key].ndim > 2:
            _sl = [slice(None)] * data[key].ndim
            _sl[1] = sample
            data_slice[key] = data[key][_sl]
        else:
            data_slice[key] = data[key]

    return data_slice


def data_duration(data):
    '''Compute the maximum valid duration of an annotated feature object.

    Static data has ``ndim <= 2``.

    For all time-series data, the second dimension indexes time.

    The valid duration of a data collection is then the minimum ``n`` such that
    for all ``k`` with ``data[k].ndim > 2``, we have ``data[k].shape[1] <= n``.

    Parameters
    ----------
    data : dict
        As generated by ``make_task_data``

    Returns
    -------
    n : int
        The valid duration

    Raises
    ------
    RuntimeError
        If no element of ``data`` has a time dimension
    '''
    n = np.inf
    for key in data:
        if data[key].ndim > 2:
            n = min(n, data[key].shape[1])

    if not np.isfinite(n):
        raise RuntimeError('No time-series data available!')

    return int(n)


def make_task_data(audio_in, jams_in, task_map, crema_input, cache=None):
    '''Construct a full-length data point

    Parameters
    ----------
    audio_in : str
        Path to the audio on disk

    jams_in : str or file-like
        Path to a jams object

    task_map : iterable of crema.task.BaseTaskTransformers
        Objects to transform jams annotations into crema targets

    crema_input : crema.pre.CremaInput
        The input feature extraction object

    cache : Shove or None
        A cache object for pre-computed input features

    Returns
    -------
    data : dict
        Contains the input features and all output variables
        and masks as specified by ``task_map``.

        Each entry of ``data`` is a numpy array.
    '''

    # Convert the annotations
    data = jams_mapping(jams_in, task_map)

    # Load the audio data
    if cache is not None:
        if audio_in not in cache:
            cache[audio_in] = crema_input.extract(audio_in)
            cache.sync()

        features = cache[audio_in]
    else:
        features = crema_input.extract(audio_in)

    for key in features:
        data[key] = features[key][np.newaxis]

    return data


def sampler(audio_in, jams_in, task_map, crema_input, n_samples, n_duration, cache=None):
    '''Construct sample data for learning

    Parameters
    ----------
    audio_in : str
        Path to the audio on disk

    jams_in : str or file-like
        Path to a jams object

    task_map : iterable of crema.task.BaseTaskTransformers
        Objects to transform jams annotations into crema targets

    crema_input : crema.pre.CremaInput
        The input feature extraction object

    n_samples : int > 0
        The number of example patches to generate

    n_duration : int > 0
        The duration (in frames) for each patch

    cache : Shove or None
        Feature cache object

    Generates
    ---------
    data : dict
        An example patch drawn uniformly at random from the track
    '''

    data = make_task_data(audio_in, jams_in, task_map, crema_input, cache=cache)

    feature_duration = data_duration(data)

    for _ in range(n_samples):
        start = np.random.randint(0, feature_duration - n_duration)

        yield slice_data(data, slice(start, start + n_duration))


def create_stream(sources, tasks, cqt, n_per_track=128, n_duration=16, n_alive=32, cache=None):
    '''Create a crema data stream

    Parameters
    ----------
    sources : pd.DataFrame
        Must contain columns `audio` and `jams`

    task_map : iterable of crema.task.BaseTaskTransformers
        Objects to transform jams annotations into crema targets

    cqt : crema.pre.CQT
        The CQT feature extraction object

    n_per_track : int > 0
        The number of example patches to generate from each source file

    n_duration : int > 0
        The duration (in frames) of each generated patch

    n_alive : int > 0
        The number of sources to keep active

    cache : Shove or None
        feature cache object

    Returns
    -------
    mux : pescador.Streamer
        A multiplexing stream object over the sources
    '''
    # Create the seed bank
    seeds = [pescador.Streamer(sampler, audf, jamf, tasks, cqt, n_per_track, n_duration, cache=cache)
             for audf, jamf in zip(sources.audio, sources.jams)]

    # Multiplex these seeds together
    return pescador.Streamer(pescador.mux, seeds, None, n_alive)


def mux_streams(streams, n_samples, n_batch=64):
    '''Multiplex data source streams

    Parameters
    ----------
    streams: list of pescador.Streamer
        The streams to merge

    n_samples : int >0 or None
        The total number of samples to draw

    n_batch : int > 0
        The size of each batch

    Returns
    -------
    mux : pescador.Streamer
        A multiplexing stream object that generates batches of size n_batch from
        the merged input streams
    '''
    # Mux all incoming streams
    stream_mux = pescador.Streamer(pescador.mux, streams, n_samples, len(streams))

    return pescador.Streamer(pescador.buffer_streamer, stream_mux, n_batch)
