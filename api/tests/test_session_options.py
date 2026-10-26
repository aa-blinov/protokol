"""Every model in the sidecar gets one session policy: the configured threads, no spinning.

The segmentation model used to be created without options at all, which left it on
onnxruntime's default thread count and outside INFERENCE_THREADS. These tests pin the
shared helper; the models that call it are exercised by the pipeline tests.
"""

import config


def test_session_options_cap_threads_and_turn_spinning_off():
    options = config.session_options(3)
    assert options.intra_op_num_threads == 3
    assert options.inter_op_num_threads == 1
    assert options.get_session_config_entry("session.intra_op.allow_spinning") == "0"


def test_session_options_default_to_the_configured_thread_count():
    assert config.session_options().intra_op_num_threads == config.INFERENCE_THREADS
